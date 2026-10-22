"""Tesseract を呼ばずに確かめられる ocr モジュールの分岐。"""

import pytesseract
from PIL import Image

from scantext import ocr
from scantext.loader import PageImage


def _engine(auto_rotate=True):
    engine = object.__new__(ocr.OcrEngine)  # Tesseract の存在確認を飛ばす
    engine.lang, engine.auto_rotate = "jpn", auto_rotate
    return engine


def _page():
    return PageImage(Image.new("L", (300, 100), 255), 300)


def test_straighten_disabled_does_not_call_tesseract(monkeypatch):
    monkeypatch.setattr(pytesseract, "image_to_osd", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    page = _page()
    assert _engine(auto_rotate=False).straighten(page) is page


def test_straighten_keeps_page_when_orientation_unknown(monkeypatch):
    def fail(*a, **k):
        raise pytesseract.TesseractError(1, "Too few characters")

    monkeypatch.setattr(pytesseract, "image_to_osd", fail)
    page = _page()
    assert _engine().straighten(page) is page


def test_straighten_ignores_low_confidence(monkeypatch):
    monkeypatch.setattr(pytesseract, "image_to_osd", lambda *a, **k: {"rotate": 90, "orientation_conf": 0.3})
    page = _page()
    assert _engine().straighten(page) is page


def test_straighten_rotates_when_confident(monkeypatch):
    monkeypatch.setattr(pytesseract, "image_to_osd", lambda *a, **k: {"rotate": 90, "orientation_conf": 5})
    assert _engine().straighten(_page()).image.size == (100, 300)


def test_vertical_text_uses_vertical_page_mode():
    engine = _engine()
    engine.lang = "jpn_vert"
    assert "--psm 5" in engine._config(_page())


def test_bundled_tesseract_is_preferred(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract" / ("tesseract.exe" if ocr.os.name == "nt" else "tesseract")
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(ocr, "app_dir", lambda: tmp_path)
    assert ocr.find_tesseract() == str(exe)
    assert ocr.find_tesseract(configured=str(tmp_path / "missing.exe")) == str(exe)


def test_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr, "WINDOWS_TESSERACT_PATHS", [])
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert ocr.find_tesseract() is None
