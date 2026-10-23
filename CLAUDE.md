# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## これは何か

電子カルテが入った**オフラインの Windows PC** で、スキャンした書類 (JPG / PDF) を文字起こしして .txt / .csv / .pdf に保存するデスクトップアプリ (パッケージ名 `scantext`、exe 名 `ScanText`)。利用者はパソコンに詳しくない医師 (開発者の父)。コード中のコメント・画面の文言・文書はすべて日本語で書く。

## コマンド

```bash
pip install -e ".[dev]"                     # 依存 (pymupdf<2, pytesseract, pillow, tkinterdnd2) + pytest, ruff
python -m scantext                          # 画面 (tkinter)
python -m scantext --cli 書類.pdf -f csv -o 出力先   # コマンドで処理 (--cli が先頭に必要)
ruff check . && ruff format --check .       # lint / format (行長 120)
xvfb-run -a pytest                          # 全テスト (Linux で画面のテストを回すには xvfb が要る)
pytest tests/test_layout.py::test_table_rows_aligns_columns_even_when_a_cell_is_missing   # 1 件だけ
python tests/smoke_bundle.py dist/ScanText  # exe 化したものが実際に 3 形式を出力できるか
```

- OCR の結合テストは `tesseract` (jpn, jpn_vert) と日本語フォントがないと**自動で skip** される。Ubuntu: `apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert fonts-noto-cjk xvfb`
- テスト内で日本語のファイルを読み書きするときは必ず `encoding=` を指定する (Windows の CI は cp1252 で落ちる)
- exe は CI (`.github/workflows/build.yml` の `build-windows`) が PyInstaller で作り、Tesseract 本体と日本語データを `dist/ScanText/tesseract/` に同梱して artifact `ScanText-windows` にする。手元の Windows では `build_windows.bat`

## 構成

流れは `gui.py` / `cli.py` → `processor.process_file` → `loader.iter_pages` (1 ページずつ `PageImage`) → `ocr.OcrEngine.recognize` (`PageResult`: text / rows / searchable_pdf) → `exporters.write_output`。

- `layout.py` は Tesseract の `image_to_data` の単語位置だけから組み立てる純粋な処理で、OCR なしで単体テストできる
  - TXT: Tesseract の段落・行の順を使い、広い空白は全角スペースで区切る。縦書きの行 (縦長) は上から下へ並べる
  - CSV: 段組みを無視して縦位置で行をまとめ、セルの左端の位置で列をそろえる。縦書き (`jpn_vert`) のときは 1 行 1 セル
- 1 ページにつき Tesseract を最大 3 回呼ぶ: 向き判定 (OSD)、`image_to_data`、PDF 出力時のみ `image_to_pdf_or_hocr`
- 画面は処理を別スレッドで動かし、`queue` 経由でメインスレッドに渡す。Tk はメインスレッドからしか触らない
- 設定 (`settings.py`) は exe のときは exe の隣の `settings.json` (USB で持ち運べるように)、書けなければ APPDATA。壊れた値は既定値に戻す

## 崩してはいけない決まり

- **通信しない**。ネットワークを使う部品を足さない (`test_processing_never_touches_the_network` が守っている)
- **元のファイル・既存の出力を上書きしない**。`processor.output_path_for` が `(2)` を付け、PDF→PDF は `_文字起こし` を付ける
- 画面に出るエラーは `LoadError` / `OcrError` の日本語メッセージをそのまま表示する。新しい失敗もこの形にする
- Tesseract は「exe の隣の `tesseract/`」→ 設定 → PATH → Windows の既定の場所、の順で探す。**同梱版が最優先**
- 日本語データは **`tessdata_fast`** を使う (Ubuntu の apt 版と同じ)。`tessdata` 版は Windows で数字を丸数字 (6→⑥) にした
- 既定の言語は `jpn` (`jpn+eng` は「様」が「tk」になるなど日本語が崩れる)
- **PyMuPDF は 1.x に固定** (2.0 は起動時に大きなレイアウト解析モデルを読み込み、exe 化で壊れる)
- 画面は 1366x768 の画面に収まる高さ (1040x720) を保つ。色・フォントは `gui.py` 冒頭の定数 (カルテ用紙の色、BIZ UD ゴシック) を使う
- 見ればわかる UI に説明文を付けない

## 文書

- `docs/ARCHITECTURE.md` 構成の詳細 / `docs/TEST_PLAN.md` テスト方針とカバレッジ目標
- `docs/DEPLOY_CHECKLIST.md` オフライン PC への導入手順 / `docs/USER_GUIDE.md` 利用者向けの使い方 (画面を変えたらここも直す)
- `docs/DESIGN_handwriting.md` と `docs/adr/` 手書き問診票対応の設計 (未実装、提案段階)。テストに本物の患者データを使わない
