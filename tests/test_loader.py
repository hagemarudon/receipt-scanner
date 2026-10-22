import pytest
from PIL import Image

from scantext.loader import LoadError, count_pages, iter_pages


def test_jpg_is_one_page_with_its_dpi(sample_jpg):
    pages = list(iter_pages(sample_jpg))
    assert count_pages(sample_jpg) == 1
    assert len(pages) == 1
    assert pages[0].image.size == (2000, 1400)
    assert pages[0].dpi == 300


def test_pdf_pages_are_rendered_at_300dpi(sample_pdf):
    pages = list(iter_pages(sample_pdf))
    assert count_pages(sample_pdf) == 3
    assert len(pages) == 3
    assert pages[0].dpi == 300
    assert pages[0].image.width == pytest.approx(595 / 72 * 300, abs=2)


def test_small_images_are_enlarged(tmp_path):
    path = tmp_path / "small.png"
    Image.new("RGB", (600, 400), "white").save(path)
    page = next(iter_pages(path))
    assert page.image.size == (1200, 800)
    assert page.dpi == 600  # dpi 情報なし → 300 とみなして 2 倍


def test_transparent_png_gets_white_background(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (1600, 100), (0, 0, 0, 0)).save(path)
    page = next(iter_pages(path))
    assert page.image.mode == "RGB"
    assert page.image.getpixel((0, 0)) == (255, 255, 255)


def test_exif_rotation_is_applied(tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # 90° 回転して表示する指定 (スマホ撮影でよくある)
    Image.new("RGB", (2000, 1600), "white").save(path, exif=exif)
    assert next(iter_pages(path)).image.size == (1600, 2000)


def test_multi_page_tiff(tmp_path):
    path = tmp_path / "multi.tif"
    frames = [Image.new("RGB", (1600, 1600), c) for c in ("white", "gray")]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    assert count_pages(path) == 2
    assert len(list(iter_pages(path))) == 2


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("memo.docx", b"x", "対応していない"),
        ("broken.jpg", b"not an image", "開けません"),
        ("broken.pdf", b"%PDF-broken", "開けません"),
    ],
)
def test_bad_files_raise_load_error(tmp_path, name, content, message):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(LoadError, match=message):
        list(iter_pages(path))


def test_missing_file(tmp_path):
    with pytest.raises(LoadError, match="見つかりません"):
        count_pages(tmp_path / "nothing.jpg")


def test_password_pdf(tmp_path):
    import pymupdf

    path = tmp_path / "locked.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    with pytest.raises(LoadError, match="パスワード"):
        list(iter_pages(path))


def test_16bit_grayscale_keeps_gray_levels(tmp_path):
    """16 ビットのスキャンで、中間の濃さが真っ白にならない (以前は薄い文字が消えていた)。"""
    path = tmp_path / "gray16.tif"
    image = Image.new("I;16", (1600, 100), 65535)
    image.paste(Image.new("I;16", (1600, 50), 30000), (0, 0))
    image.save(path)
    page = next(iter_pages(path))
    assert page.image.mode == "L"
    assert 100 < page.image.getpixel((10, 10)) < 140  # 30000/65535 ≒ 117
    assert page.image.getpixel((10, 90)) == 255


def test_bilevel_and_cmyk_scans_are_converted(tmp_path):
    bilevel = tmp_path / "fax.tif"
    Image.new("1", (1600, 100), 1).save(bilevel)
    cmyk = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (1600, 100), (0, 0, 0, 0)).save(cmyk)
    for path in (bilevel, cmyk):
        page = next(iter_pages(path))
        assert page.image.mode in ("L", "RGB")
        assert page.image.convert("L").getpixel((5, 5)) > 240
