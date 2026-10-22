from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from scantext.ocr import PageResult

JAPANESE_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
]


def japanese_font_path() -> str | None:
    return next((p for p in JAPANESE_FONT_CANDIDATES if Path(p).is_file()), None)


def tesseract_has_japanese() -> bool:
    cmd = shutil.which("tesseract")
    if not cmd:
        return False
    out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True)
    return "jpn" in (out.stdout + out.stderr).split()


requires_tesseract = pytest.mark.skipif(not tesseract_has_japanese(), reason="Tesseract (jpn) が入っていない")
requires_jp_font = pytest.mark.skipif(japanese_font_path() is None, reason="日本語フォントがない")


def render_lines(lines: list[str | tuple[str, ...]], size=(1800, 1000), font_size=44) -> Image.Image:
    """文字列 (またはセルのタプル) を白地に黒で描いた画像を作る。タプルは表の列として横に並べる。"""
    font = ImageFont.truetype(japanese_font_path(), font_size)
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for row, line in enumerate(lines):
        y = 80 + row * int(font_size * 2.2)
        cells = line if isinstance(line, tuple) else (line,)
        for col, cell in enumerate(cells):
            draw.text((80 + col * 520, y), cell, font=font, fill="black")
    return image


class FakeEngine:
    """Tesseract を使わずに処理の流れだけを確かめるための代役。"""

    def __init__(self, text="テスト", rows=None):
        self.text = text
        self.rows = rows if rows is not None else [["氏名", "山田太郎"]]
        self.calls = []

    def recognize(self, page, with_pdf=False):
        import pymupdf

        self.calls.append((page.image.size, with_pdf))
        pdf = None
        if with_pdf:
            with pymupdf.open() as doc:
                doc.new_page()
                pdf = doc.tobytes()
        return PageResult(text=f"{self.text}{len(self.calls)}", rows=self.rows, searchable_pdf=pdf)


@pytest.fixture
def fake_engine():
    return FakeEngine()


@pytest.fixture
def sample_jpg(tmp_path) -> Path:
    path = tmp_path / "scan.jpg"
    Image.new("RGB", (2000, 1400), "white").save(path, dpi=(300, 300))
    return path


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    import pymupdf

    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        for _ in range(3):
            doc.new_page(width=595, height=842)
        doc.save(path)
    return path
