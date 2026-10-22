import socket
import threading

import pytest

from scantext.processor import Cancelled, output_path_for, process_file
from scantext.settings import Settings


def test_output_next_to_source_by_default(sample_jpg):
    assert output_path_for(sample_jpg, Settings(output_format="txt")) == sample_jpg.with_suffix(".txt")


def test_output_to_chosen_folder(sample_jpg, tmp_path):
    out = tmp_path / "結果"
    assert output_path_for(sample_jpg, Settings(output_format="csv", output_dir=str(out))) == out / "scan.csv"


def test_existing_output_is_never_overwritten(sample_jpg):
    sample_jpg.with_suffix(".txt").write_text("前の結果")
    (sample_jpg.parent / "scan (2).txt").write_text("前の結果")
    assert output_path_for(sample_jpg, Settings()).name == "scan (3).txt"


def test_pdf_to_pdf_does_not_overwrite_the_scan(sample_pdf):
    assert output_path_for(sample_pdf, Settings(output_format="pdf")).name == "scan_文字起こし.pdf"


@pytest.mark.parametrize(
    ("fmt", "pdf_mode", "wants_pdf"),
    [("txt", "searchable", False), ("csv", "searchable", False), ("pdf", "text", False), ("pdf", "searchable", True)],
)
def test_every_format_writes_a_file(sample_pdf, fake_engine, fmt, pdf_mode, wants_pdf):
    result = process_file(sample_pdf, Settings(output_format=fmt, pdf_mode=pdf_mode), fake_engine)
    assert result.output.suffix == f".{fmt}"
    assert result.output.stat().st_size > 0
    assert len(result.pages) == 3
    assert all(with_pdf == wants_pdf for _size, with_pdf in fake_engine.calls)


def test_progress_is_reported_per_page(sample_pdf, fake_engine):
    seen = []
    process_file(sample_pdf, Settings(), fake_engine, on_page=lambda n, total: seen.append((n, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_cancel_stops_before_writing(sample_pdf, fake_engine):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        process_file(sample_pdf, Settings(), fake_engine, cancel=cancel)
    assert not sample_pdf.with_suffix(".txt").exists()


def test_processing_never_touches_the_network(sample_jpg, fake_engine, monkeypatch):
    """電子カルテ PC はオフライン。通信しようとしたら失敗させて確かめる。"""

    def blocked(*args, **kwargs):
        raise AssertionError("ネットワークに接続しようとしました")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for fmt in ("txt", "csv", "pdf"):
        process_file(sample_jpg, Settings(output_format=fmt, pdf_mode="text"), fake_engine)
