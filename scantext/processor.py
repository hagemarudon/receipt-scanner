"""1 ファイル分の処理: 読み込み → 文字認識 → 書き出し。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .exporters import combined_text, write_output
from .loader import count_pages, iter_pages
from .ocr import OcrEngine, PageResult
from .settings import Settings


class Cancelled(Exception):
    pass


@dataclass
class FileResult:
    source: Path
    output: Path
    pages: list[PageResult]

    @property
    def text(self) -> str:
        return combined_text(self.pages)


def output_path_for(source: Path, settings: Settings) -> Path:
    """「元の名前.拡張子」。同名ファイルがあれば上書きせず「元の名前 (2).拡張子」にする。"""
    folder = Path(settings.output_dir) if settings.output_dir else source.parent
    suffix = "." + settings.output_format
    # 入力が PDF で出力も PDF のとき、元ファイルを上書きしないよう名前を変える
    stem = source.stem + ("_文字起こし" if suffix == source.suffix.lower() else "")
    candidate = folder / f"{stem}{suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def process_file(
    source: Path,
    settings: Settings,
    engine: OcrEngine,
    on_page: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> FileResult:
    source = Path(source)
    total = count_pages(source)
    with_pdf = settings.output_format == "pdf" and settings.pdf_mode == "searchable"

    pages = []
    for number, page in enumerate(iter_pages(source), 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if on_page:
            on_page(number, total)
        pages.append(engine.recognize(page, with_pdf=with_pdf))

    output = output_path_for(source, settings)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_output(output, pages, settings.output_format, settings.encoding, settings.pdf_mode)
    return FileResult(source, output, pages)
