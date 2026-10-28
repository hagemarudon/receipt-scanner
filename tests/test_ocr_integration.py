"""実際の Tesseract で読み取るテスト。Tesseract と日本語フォントがない環境では飛ばす。"""

import csv
import io

import pymupdf
import pytest
from PIL import ImageDraw, ImageFilter

from scantext.cli import main as cli_main
from scantext.layout import BAR_CHARS, _text_width
from scantext.loader import PageImage
from scantext.ocr import OcrEngine, OcrError
from scantext.processor import process_file
from scantext.settings import Settings

from .conftest import render_lines, render_vertical, requires_jp_font, requires_tesseract, requires_vertical

pytestmark = [pytest.mark.tesseract, requires_tesseract, requires_jp_font]

LETTER = ["診療情報提供書", "患者氏名　山田太郎　様", "令和6年4月1日に受診されました。", "血圧は128/80でした。"]
TABLE = [("検査項目", "結果", "単位"), ("血糖", "98", "mg/dL"), ("総コレステロール", "210", "mg/dL")]


@pytest.fixture(scope="module")
def engine():
    return OcrEngine(lang="jpn")


def _save_scan_pdf(image, path):
    """スキャナが作る PDF と同じく「画像だけが入った PDF」を作る。"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with pymupdf.open() as doc:
        page = doc.new_page(width=image.width * 72 / 300, height=image.height * 72 / 300)
        page.insert_image(page.rect, stream=buffer.getvalue())
        doc.save(path)


def test_reads_japanese_letter(engine):
    text = engine.recognize(PageImage(render_lines(LETTER), 300)).text
    for expected in ("診療情報提供書", "山田太郎", "様", "令和6年4月1日", "128/80"):
        assert expected in text


def test_rotated_scan_is_straightened(engine):
    image = render_lines(LETTER).rotate(90, expand=True)
    assert "診療情報提供書" in engine.recognize(PageImage(image, 300)).text


def test_table_scan_becomes_csv_columns(engine, tmp_path):
    source = tmp_path / "検査結果.jpg"
    render_lines(TABLE).save(source, dpi=(300, 300))
    result = process_file(source, Settings(output_format="csv"), engine)
    with open(result.output, encoding="utf-8-sig", newline="") as f:
        rows = [row[2:5] for row in list(csv.reader(f))[1:]]
    assert rows[0] == ["検査項目", "結果", "単位"]
    assert rows[1][0] == "血糖" and rows[1][1] == "98"


def _ruled_table_scan():
    """罫線で囲んだ表を、少しぼかしてスキャンしたような画像にする。"""
    image = render_lines(TABLE)
    draw = ImageDraw.Draw(image)
    columns = [60, 580, 1100, 1620]
    top, pitch = 80 - 25, 97
    for row in range(len(TABLE) + 1):
        draw.line([(columns[0], top + row * pitch), (columns[-1], top + row * pitch)], fill="black", width=4)
    for x in columns:
        draw.line([(x, top), (x, top + len(TABLE) * pitch)], fill="black", width=4)
    return image.filter(ImageFilter.GaussianBlur(1))


def test_ruled_table_text_has_no_bars_and_columns_line_up(engine):
    text = engine.recognize(PageImage(_ruled_table_scan(), 300)).text
    assert not any(char in text for char in BAR_CHARS)
    lines = {line.lstrip("　").split("　")[0]: line for line in text.splitlines() if line.strip()}
    header, sugar = lines["検査項目"], lines["血糖"]
    # 「結果」と「98」が同じ桁から始まる (等幅フォントに貼り付けたときに列がそろう)
    assert _text_width(header[: header.index("結果")]) == _text_width(sugar[: sugar.index("98")])


def test_scanned_pdf_to_searchable_pdf(engine, tmp_path):
    source = tmp_path / "紹介状.pdf"
    _save_scan_pdf(render_lines(LETTER), source)
    result = process_file(source, Settings(output_format="pdf", pdf_mode="searchable"), engine)
    with pymupdf.open(result.output) as doc:
        assert doc.page_count == 1
        assert "山田太郎" in doc[0].get_text().replace(" ", "")
        # 元の画像も残っている
        assert doc[0].get_images()


def test_cli_folder_to_txt(tmp_path, capsys):
    render_lines(LETTER).save(tmp_path / "a.jpg")
    render_lines(TABLE).save(tmp_path / "b.png")
    (tmp_path / "memo.docx").write_bytes(b"x")  # 対象外は無視される
    out = tmp_path / "out"
    assert cli_main([str(tmp_path), "-f", "txt", "-o", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["a.txt", "b.txt"]
    assert "山田太郎" in (out / "a.txt").read_text(encoding="utf-8-sig")


def test_missing_language_data_is_explained():
    with pytest.raises(OcrError, match="xyz.traineddata"):
        OcrEngine(lang="jpn+xyz")


def test_missing_tesseract_is_explained(monkeypatch):
    monkeypatch.setattr("scantext.ocr.find_tesseract", lambda configured="": None)
    with pytest.raises(OcrError, match="見つかりません"):
        OcrEngine()


def test_blank_page_gives_empty_result(engine):
    """両面スキャンの裏面など、白紙のページで止まらない。"""
    from PIL import Image

    result = engine.recognize(PageImage(Image.new("L", (2480, 3508), 255), 300), with_pdf=True)
    assert result.text == "" and result.rows == []
    assert result.searchable_pdf


def test_cli_reports_bad_files_but_continues(tmp_path, capsys):
    render_lines(LETTER).save(tmp_path / "good.jpg")
    (tmp_path / "bad.jpg").write_bytes(b"broken")
    assert cli_main([str(tmp_path / "bad.jpg"), str(tmp_path / "good.jpg")]) == 1
    assert (tmp_path / "good.txt").exists()
    assert "bad.jpg" in capsys.readouterr().err


@requires_vertical
def test_reads_vertical_japanese_in_order():
    lines = ["診療情報提供書", "患者氏名山田太郎様", "令和六年四月一日に受診されました。"]
    result = OcrEngine(lang="jpn_vert").recognize(PageImage(render_vertical(lines), 300))
    for line in lines:
        assert line in result.text
    assert [row[0] for row in result.rows] == lines
