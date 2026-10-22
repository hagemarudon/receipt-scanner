"""入力ファイル (画像 / PDF) をページごとの画像に変換する。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}

PDF_RENDER_DPI = 300
DEFAULT_DPI = 300
# これより幅が小さい画像は拡大してから読み取る (小さい文字の認識率が上がる)
MIN_WIDTH_FOR_OCR = 1500


class LoadError(Exception):
    """ファイルを開けなかったときのエラー。メッセージはそのまま画面に出す。"""


@dataclass
class PageImage:
    image: Image.Image
    dpi: int


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def count_pages(path: Path) -> int:
    path = Path(path)
    _check(path)
    try:
        if path.suffix.lower() == ".pdf":
            with pymupdf.open(path) as doc:
                return doc.page_count
        with Image.open(path) as img:
            return getattr(img, "n_frames", 1)
    except (pymupdf.FileDataError, UnidentifiedImageError, OSError) as e:
        raise LoadError(f"ファイルを開けません: {path.name}") from e


def iter_pages(path: Path) -> Iterator[PageImage]:
    """1 ページずつ画像を返す (大きな PDF でもメモリを使いすぎないように)。"""
    path = Path(path)
    _check(path)
    try:
        if path.suffix.lower() == ".pdf":
            yield from _iter_pdf(path)
        else:
            yield from _iter_image(path)
    except (pymupdf.FileDataError, UnidentifiedImageError, OSError) as e:
        raise LoadError(f"ファイルを開けません: {path.name}") from e


def _check(path: Path) -> None:
    if not path.is_file():
        raise LoadError(f"ファイルが見つかりません: {path}")
    if not is_supported(path):
        raise LoadError(f"対応していないファイル形式です: {path.name}")


def _iter_pdf(path: Path) -> Iterator[PageImage]:
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise LoadError(f"パスワード付きの PDF は開けません: {path.name}")
        for page in doc:
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            yield _prepare(image, PDF_RENDER_DPI)


def _iter_image(path: Path) -> Iterator[PageImage]:
    with Image.open(path) as img:
        dpi = _dpi_of(img)
        for frame in ImageSequence.Iterator(img):
            yield _prepare(ImageOps.exif_transpose(frame.copy()), dpi)


def _dpi_of(img: Image.Image) -> int:
    dpi = img.info.get("dpi")
    try:
        value = int(round(float(dpi[0])))
    except (TypeError, ValueError, IndexError):
        return DEFAULT_DPI
    # 72dpi などはスキャナではなく画面用の値なので当てにしない
    return value if 150 <= value <= 1200 else DEFAULT_DPI


def _prepare(image: Image.Image, dpi: int) -> PageImage:
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if 0 < image.width < MIN_WIDTH_FOR_OCR:
        scale = 2
        image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
        dpi *= scale
    return PageImage(image, dpi)
