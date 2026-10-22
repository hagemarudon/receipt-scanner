"""設定の読み書き。設定ファイルが壊れていても既定値で起動できるようにする。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .ocr import LANGUAGES, app_dir

OUTPUT_FORMATS = ("txt", "csv", "pdf")
PDF_MODES = ("searchable", "text")
ENCODINGS = ("utf-8-sig", "cp932")


@dataclass
class Settings:
    output_format: str = "txt"
    # searchable: 元の画像の上に透明な文字を重ねた PDF / text: 文字だけの PDF
    pdf_mode: str = "searchable"
    # utf-8-sig: BOM 付き UTF-8 (Excel・メモ帳で文字化けしない) / cp932: Shift_JIS
    encoding: str = "utf-8-sig"
    # 空なら元ファイルと同じフォルダに保存
    output_dir: str = ""
    language: str = "jpn"
    auto_rotate: bool = True
    tesseract_path: str = ""

    def validated(self) -> Settings:
        default = Settings()
        if self.output_format not in OUTPUT_FORMATS:
            self.output_format = default.output_format
        if self.pdf_mode not in PDF_MODES:
            self.pdf_mode = default.pdf_mode
        if self.encoding not in ENCODINGS:
            self.encoding = default.encoding
        if self.language not in LANGUAGES.values():
            self.language = default.language
        for f in fields(self):
            if not isinstance(getattr(self, f.name), type(getattr(default, f.name))):
                setattr(self, f.name, getattr(default, f.name))
        return self


def default_settings_path() -> Path:
    """exe 化したときは exe の隣 (USB で持ち運べるように)。書けなければユーザーフォルダ。"""
    if getattr(sys, "frozen", False):
        portable = app_dir() / "settings.json"
        if os.access(app_dir(), os.W_OK):
            return portable
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / "ScanText" / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or default_settings_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known}).validated()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = Path(path or default_settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
