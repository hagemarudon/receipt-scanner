"""コマンドラインで使う場合: python -m scantext --cli 書類.pdf --format csv"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import SUPPORTED_EXTENSIONS, is_supported
from .ocr import OcrEngine, OcrError
from .processor import process_file
from .settings import ENCODINGS, OUTPUT_FORMATS, PDF_MODES, Settings


def collect_files(paths: list[str]) -> list[Path]:
    files = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files += sorted(p for p in path.iterdir() if p.is_file() and is_supported(p))
        else:
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scantext", description="スキャンした書類を文字起こしします")
    parser.add_argument("inputs", nargs="+", help="画像 / PDF ファイル、またはフォルダ")
    parser.add_argument("-f", "--format", choices=OUTPUT_FORMATS, default="txt")
    parser.add_argument("-o", "--output-dir", default="", help="保存先 (省略時は元ファイルと同じフォルダ)")
    parser.add_argument("--pdf-mode", choices=PDF_MODES, default="searchable")
    parser.add_argument("--encoding", choices=ENCODINGS, default="utf-8-sig")
    parser.add_argument("--lang", default="jpn", help="jpn / jpn_vert / eng")
    parser.add_argument("--no-rotate", action="store_true", help="向きの自動補正をしない")
    parser.add_argument("--tesseract", default="", help="tesseract 実行ファイルの場所")
    args = parser.parse_args(argv)

    settings = Settings(
        output_format=args.format,
        pdf_mode=args.pdf_mode,
        encoding=args.encoding,
        output_dir=args.output_dir,
        language=args.lang,
        auto_rotate=not args.no_rotate,
        tesseract_path=args.tesseract,
    )
    try:
        engine = OcrEngine(settings.tesseract_path, settings.language, settings.auto_rotate)
    except OcrError as e:
        print(e, file=sys.stderr)
        return 2

    files = collect_files(args.inputs)
    if not files:
        print(f"対象のファイルがありません ({' '.join(sorted(SUPPORTED_EXTENSIONS))})", file=sys.stderr)
        return 1

    failed = 0
    for source in files:
        try:
            result = process_file(source, settings, engine)
            print(f"{source} → {result.output}")
        except Exception as e:  # 1 ファイルの失敗で全体を止めない
            print(f"エラー: {source}: {e}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0
