"""文字起こし結果を .txt / .csv / .pdf に書き出す。"""

from __future__ import annotations

import csv
from pathlib import Path

import pymupdf

from .ocr import PageResult

A4 = pymupdf.paper_rect("a4")
PDF_MARGIN = 50
PDF_FONT_SIZE = 10.5
PDF_LINE_HEIGHT = PDF_FONT_SIZE * 1.6


def page_heading(number: int) -> str:
    return f"―― {number}ページ ――"


def combined_text(pages: list[PageResult]) -> str:
    if len(pages) == 1:
        return pages[0].text
    return "\n\n".join(f"{page_heading(i)}\n{p.text}" for i, p in enumerate(pages, 1))


def write_txt(path: Path, pages: list[PageResult], encoding: str = "utf-8-sig") -> None:
    # Shift_JIS で表せない文字 (一部の旧字体・記号) は「?」に置き換える
    with open(path, "w", encoding=encoding, errors="replace", newline="\r\n") as f:
        f.write(combined_text(pages) + "\n")


def write_csv(path: Path, pages: list[PageResult], encoding: str = "utf-8-sig") -> None:
    width = max((len(row) for p in pages for row in p.rows), default=1)
    with open(path, "w", encoding=encoding, errors="replace", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ページ", "行"] + [f"列{i}" for i in range(1, width + 1)])
        for page_number, page in enumerate(pages, 1):
            for row_number, row in enumerate(page.rows, 1):
                writer.writerow([page_number, row_number] + row + [""] * (width - len(row)))


def write_searchable_pdf(path: Path, pages: list[PageResult]) -> None:
    """Tesseract が作った「画像＋透明テキスト」の PDF をページ順につなげる。"""
    with pymupdf.open() as out:
        for page in pages:
            if page.searchable_pdf is None:
                raise ValueError("検索可能 PDF のデータがありません")
            with pymupdf.open("pdf", page.searchable_pdf) as part:
                out.insert_pdf(part)
        out.save(path, garbage=3, deflate=True)


def _wrap(text: str, font: pymupdf.Font, width: float) -> list[str]:
    """日本語は単語の区切りがないので 1 文字ずつ幅を測って折り返す。"""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for char in paragraph:
            if line and font.text_length(line + char, PDF_FONT_SIZE) > width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


def write_text_pdf(path: Path, pages: list[PageResult]) -> None:
    font = pymupdf.Font("japan")
    usable = A4 + (PDF_MARGIN, PDF_MARGIN, -PDF_MARGIN, -PDF_MARGIN)
    lines = _wrap(combined_text(pages), font, usable.width)
    per_page = max(int(usable.height // PDF_LINE_HEIGHT), 1)

    with pymupdf.open() as doc:
        for start in range(0, max(len(lines), 1), per_page):
            page = doc.new_page(width=A4.width, height=A4.height)
            writer = pymupdf.TextWriter(page.rect)
            y = usable.y0 + PDF_FONT_SIZE
            for line in lines[start : start + per_page]:
                if line:
                    writer.append((usable.x0, y), line, font=font, fontsize=PDF_FONT_SIZE)
                y += PDF_LINE_HEIGHT
            writer.write_text(page)
        doc.subset_fonts()
        doc.save(path, garbage=3, deflate=True)


def write_output(path: Path, pages: list[PageResult], fmt: str, encoding: str, pdf_mode: str) -> None:
    if fmt == "txt":
        write_txt(path, pages, encoding)
    elif fmt == "csv":
        write_csv(path, pages, encoding)
    elif fmt == "pdf" and pdf_mode == "searchable":
        write_searchable_pdf(path, pages)
    elif fmt == "pdf":
        write_text_pdf(path, pages)
    else:
        raise ValueError(f"未対応の出力形式: {fmt}")
