"""Tesseract OCR の呼び出し。ネットワークは一切使わない。"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract

from .layout import reading_order_text, table_rows, words_from_tesseract
from .loader import PageImage

WINDOWS_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# 画面に出す名前 → Tesseract の言語指定
# jpn だけで英数字も読める。jpn+eng にすると「様」が「tk」になるなど日本語が崩れやすい
LANGUAGES = {
    "日本語（横書き）": "jpn",
    "日本語（縦書き）": "jpn_vert",
    "英語": "eng",
}


class OcrError(Exception):
    """OCR が使えないときのエラー。メッセージはそのまま画面に出す。"""


@dataclass
class PageResult:
    text: str
    rows: list[list[str]] = field(default_factory=list)
    searchable_pdf: bytes | None = None


def app_dir() -> Path:
    """exe 化したときは exe のあるフォルダ、開発時はリポジトリのフォルダ。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_tesseract(configured: str = "") -> str | None:
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    candidates = [configured, str(app_dir() / "tesseract" / exe), shutil.which("tesseract")]
    if os.name == "nt":
        candidates += WINDOWS_TESSERACT_PATHS
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Programs" / "Tesseract-OCR" / exe))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class OcrEngine:
    def __init__(self, tesseract_cmd: str = "", lang: str = "jpn", auto_rotate: bool = True):
        cmd = find_tesseract(tesseract_cmd)
        if cmd is None:
            raise OcrError(
                "Tesseract (文字認識エンジン) が見つかりません。\n"
                "アプリと同じフォルダに「tesseract」フォルダがあるか確認するか、"
                "メニューの「設定」→「Tesseract の場所を指定…」で tesseract.exe を選んでください。"
            )
        pytesseract.pytesseract.tesseract_cmd = cmd
        self.cmd = cmd
        self.lang = lang
        self.auto_rotate = auto_rotate
        self._check_languages()

    def _check_languages(self) -> None:
        try:
            installed = set(pytesseract.get_languages(config=""))
        except (pytesseract.TesseractError, OSError) as e:
            raise OcrError(f"Tesseract を起動できません: {e}") from e
        missing = [code for code in self.lang.split("+") if code not in installed]
        if missing:
            files = "、".join(f"{code}.traineddata" for code in missing)
            raise OcrError(f"言語データが入っていません: {files}\ntessdata フォルダに追加してください。")

    @property
    def _psm(self) -> int:
        # 縦書きは「縦書きの 1 ブロック」として読ませた方が精度が良い
        return 5 if "vert" in self.lang else 3

    def _config(self, page: PageImage) -> str:
        return f"--psm {self._psm} --dpi {page.dpi}"

    def straighten(self, page: PageImage) -> PageImage:
        """横向き・逆さまにスキャンされたページを正しい向きに直す。"""
        if not self.auto_rotate:
            return page
        try:
            osd = pytesseract.image_to_osd(
                page.image, config=f"--psm 0 --dpi {page.dpi}", output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractError:
            return page  # 文字が少なくて向きを判定できないときはそのまま
        rotate = int(osd.get("rotate", 0)) % 360
        if rotate == 0 or float(osd.get("orientation_conf", 0)) < 1.0:
            return page
        return PageImage(page.image.rotate(-rotate, expand=True, fillcolor="white"), page.dpi)

    def recognize(self, page: PageImage, with_pdf: bool = False) -> PageResult:
        page = self.straighten(page)
        data = pytesseract.image_to_data(
            page.image, lang=self.lang, config=self._config(page), output_type=pytesseract.Output.DICT
        )
        words = words_from_tesseract(data)
        result = PageResult(text=reading_order_text(words), rows=table_rows(words))
        if with_pdf:
            result.searchable_pdf = pytesseract.image_to_pdf_or_hocr(
                page.image, lang=self.lang, config=self._config(page), extension="pdf"
            )
        return result
