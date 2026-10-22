"""画面の動作確認。ディスプレイがない環境では飛ばす (Linux は xvfb-run で実行できる)。"""

import time

import pytest

tk = pytest.importorskip("tkinter")

from scantext import gui  # noqa: E402
from scantext.settings import load_settings  # noqa: E402

from .conftest import FakeEngine  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def app(tmp_path):
    try:
        root = gui.TkinterDnD.Tk() if gui.TkinterDnD else tk.Tk()
    except tk.TclError:
        pytest.skip("ディスプレイがない")
    root.withdraw()
    application = gui.App(root, settings_path=tmp_path / "settings.json")
    yield application
    try:
        root.destroy()
    except tk.TclError:
        pass  # テスト内で閉じ済み


def _wait_until_finished(app, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.root.update()
        if not app._running and app.events.empty():
            app.root.update()
            return
        time.sleep(0.02)
    raise AssertionError("終わらない")


def test_add_paths_filters_and_deduplicates(app, sample_jpg, sample_pdf, tmp_path):
    (tmp_path / "memo.docx").write_bytes(b"x")
    assert app.add_paths([str(sample_jpg), str(sample_jpg)]) == 1
    assert app.add_paths([str(tmp_path)]) == 1  # フォルダ内の PDF だけ増える (jpg は登録済み、docx は対象外)
    assert sorted(p.name for p in app.files.values()) == ["scan.jpg", "scan.pdf"]
    assert not app.empty_label.winfo_ismapped()


def test_run_shows_result_and_writes_file(app, sample_pdf, monkeypatch):
    monkeypatch.setattr(gui, "OcrEngine", lambda *a, **k: FakeEngine(text="結果"))
    app.format_var.set("csv")
    app.add_paths([str(sample_pdf)])
    app.start()
    _wait_until_finished(app)

    item = next(iter(app.files))
    assert app.tree.set(item, "status") == gui.STATUS_DONE
    assert sample_pdf.with_suffix(".csv").exists()
    assert "結果1" in app.text.get("1.0", "end")
    assert str(app.copy_button["state"]) == "normal"
    assert "1 件完了" in app.status.get()


def test_one_bad_file_does_not_stop_the_rest(app, sample_jpg, tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "OcrEngine", lambda *a, **k: FakeEngine())
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    app.add_paths([str(broken), str(sample_jpg)])
    app.start()
    _wait_until_finished(app)
    statuses = [app.tree.set(item, "status") for item in app.files]
    assert statuses[0].startswith("エラー")
    assert statuses[1] == gui.STATUS_DONE


def test_missing_tesseract_shows_message(app, sample_jpg, monkeypatch):
    def not_found(*a, **k):
        raise gui.OcrError("Tesseract が見つかりません")

    shown = []
    monkeypatch.setattr(gui, "OcrEngine", not_found)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message: shown.append(message))
    app.add_paths([str(sample_jpg)])
    app.start()
    _wait_until_finished(app)
    assert shown == ["Tesseract が見つかりません"]
    assert str(app.start_button["state"]) == "normal"


def test_settings_are_saved_on_close(app, tmp_path):
    app.format_var.set("pdf")
    app.pdf_mode_var.set(gui.PDF_MODE_LABELS["text"])
    app.dest_mode.set("custom")
    app.output_dir_var.set(str(tmp_path / "out"))
    app.on_close()
    saved = load_settings(tmp_path / "settings.json")
    assert (saved.output_format, saved.pdf_mode, saved.output_dir) == ("pdf", "text", str(tmp_path / "out"))


def test_format_choice_enables_only_relevant_options(app):
    app.format_var.set("pdf")
    app._sync_widgets()
    assert str(app.pdf_mode_box["state"]) == "readonly"
    assert str(app.encoding_box["state"]) == "disabled"
    app.format_var.set("txt")
    app._sync_widgets()
    assert str(app.pdf_mode_box["state"]) == "disabled"


def test_start_again_after_changing_format_reruns_done_files(app, sample_jpg, monkeypatch):
    """完了後に形式を変えて「開始」したら、もう一度処理できる (以前は何も起きなかった)。"""
    monkeypatch.setattr(gui, "OcrEngine", lambda *a, **k: FakeEngine())
    app.add_paths([str(sample_jpg)])
    app.start()
    _wait_until_finished(app)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a: True)
    app.format_var.set("csv")
    app.start()
    _wait_until_finished(app)
    assert sample_jpg.with_suffix(".txt").exists()
    assert sample_jpg.with_suffix(".csv").exists()


def test_start_with_no_files_shows_message(app, monkeypatch):
    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message: shown.append(message))
    app.start()
    assert shown and not app._running
