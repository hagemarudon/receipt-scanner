import json

from scantext.settings import Settings, load_settings, save_settings


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(output_format="csv", encoding="cp932", output_dir="D:/文字起こし", auto_rotate=False)
    save_settings(original, path)
    assert load_settings(path) == original


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "none.json") == Settings()


def test_broken_json_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ broken", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_invalid_and_unknown_values_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"output_format": "docx", "encoding": "euc-jp", "auto_rotate": "yes", "old_key": 1, "pdf_mode": "text"}
        ),
        encoding="utf-8",
    )
    s = load_settings(path)
    assert (s.output_format, s.encoding, s.auto_rotate, s.pdf_mode) == ("txt", "utf-8-sig", True, "text")


def test_non_object_json_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_frozen_app_keeps_settings_next_to_exe(tmp_path, monkeypatch):
    import scantext.settings as settings_module

    monkeypatch.setattr(settings_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_module, "app_dir", lambda: tmp_path)
    assert settings_module.default_settings_path() == tmp_path / "settings.json"
