import csv

import pymupdf
import pytest

from scantext.exporters import write_csv, write_output, write_searchable_pdf, write_text_pdf, write_txt
from scantext.ocr import PageResult

PAGES = [
    PageResult("診療情報提供書\n患者氏名　山田太郎", [["患者氏名", "山田太郎"], ["生年月日", "昭和20年1月2日"]]),
    PageResult("2枚目の内容", [["検査", "結果", "単位"]]),
]


def test_txt_utf8_has_bom_and_page_headings(tmp_path):
    path = tmp_path / "out.txt"
    write_txt(path, PAGES)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # メモ帳・Excel で文字化けしない
    text = raw.decode("utf-8-sig")
    assert "1ページ" in text and "2ページ" in text
    assert "山田太郎\r\n" in text  # Windows の改行


def test_txt_single_page_has_no_heading(tmp_path):
    path = tmp_path / "out.txt"
    write_txt(path, PAGES[:1])
    assert "ページ" not in path.read_text(encoding="utf-8-sig")


def test_txt_shift_jis_replaces_unsupported_chars(tmp_path):
    path = tmp_path / "out.txt"
    write_txt(path, [PageResult("髙橋 🙂")], encoding="cp932")
    assert path.read_text(encoding="cp932").strip() == "髙橋 ?"


def test_csv_has_header_page_and_row_numbers(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, PAGES)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["ページ", "行", "列1", "列2", "列3"]
    assert rows[1] == ["1", "1", "患者氏名", "山田太郎", ""]
    assert rows[3] == ["2", "1", "検査", "結果", "単位"]


def test_csv_quotes_commas_and_newlines(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [PageResult("", [["1,000円", '"注"']])])
    with open(path, encoding="utf-8-sig", newline="") as f:
        assert list(csv.reader(f))[1] == ["1", "1", "1,000円", '"注"']


def test_text_pdf_contains_searchable_japanese(tmp_path):
    path = tmp_path / "out.pdf"
    long_page = PageResult("あ" * 5000)  # 折り返しと改ページ
    write_text_pdf(path, PAGES + [long_page])
    with pymupdf.open(path) as doc:
        assert doc.page_count >= 2
        text = "".join(page.get_text() for page in doc)
    assert "山田太郎" in text
    assert text.count("あ") == 5000


def test_searchable_pdf_merges_pages_in_order(tmp_path):
    parts = []
    for label in ("one", "two"):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((50, 50), label)
            parts.append(PageResult(label, searchable_pdf=doc.tobytes()))
    path = tmp_path / "out.pdf"
    write_searchable_pdf(path, parts)
    with pymupdf.open(path) as doc:
        assert [p.get_text().strip() for p in doc] == ["one", "two"]


def test_searchable_pdf_without_data_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        write_searchable_pdf(tmp_path / "out.pdf", PAGES)


def test_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        write_output(tmp_path / "x.doc", PAGES, "doc", "utf-8-sig", "searchable")
