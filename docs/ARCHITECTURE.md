# 構成 (開発者向け)

## 処理の流れ

```
 画面 (gui.py) / コマンド (cli.py)
        │  設定 (settings.py)
        ▼
 processor.process_file ─────────────────────────────────────────┐
        │                                                         │
        ▼                                                         ▼
 loader.iter_pages          ocr.OcrEngine.recognize           exporters.write_output
 ・画像/PDF → 1 ページずつ    ・向き補正 (OSD)                   ・.txt / .csv
 ・EXIF 回転、透過/16bit      ・image_to_data → 単語と位置       ・.pdf (検索可能 / 文字だけ)
   /CMYK を 8bit へ           ・layout で TXT と表 (行×列) を作る
 ・小さい画像は 2 倍           ・PDF 出力時は検索可能 PDF も作る
        │                          │
        └──── PageImage ──────────▶ PageResult(text, rows, searchable_pdf)
```

- 1 ファイル = 1 出力ファイル。PDF は 1 ページずつ読み、メモリを抑える
- 画面では `process_file` を別スレッドで動かし、状態は `queue` 経由でメインスレッドに渡す (Tk はメインスレッドからのみ触る)

## モジュール

| ファイル | 役割 | 外部依存 |
| --- | --- | --- |
| `loader.py` | 入力をページ画像 (`PageImage`: 画像＋dpi) にする。エラーは `LoadError` (日本語メッセージ) | Pillow, PyMuPDF |
| `ocr.py` | Tesseract の場所探し、言語データの確認、向き補正、認識。エラーは `OcrError` | pytesseract |
| `layout.py` | 単語の位置から、読む順のテキストと表を組み立てる (Tesseract に依存しない純粋な処理) | — |
| `textutil.py` | 日本語の文字間スペースを詰める | — |
| `exporters.py` | 3 形式の書き出し | PyMuPDF |
| `processor.py` | 1 ファイル分の処理、出力ファイル名 (上書きしない) | — |
| `settings.py` | 設定の読み書き。壊れていても既定値で起動 | — |
| `gui.py` / `cli.py` | 画面 / コマンド | tkinter, tkinterdnd2 (任意) |

## 大事な決まり

- **通信しない**。ネットワークを使う部品を足さない (テスト `test_processing_never_touches_the_network` が守る)
- **元のファイル・既存の出力を上書きしない** (`processor.output_path_for`)
- 画面に出るエラーは日本語の一文にする (`LoadError` / `OcrError` のメッセージをそのまま表示)
- Tesseract は `exe と同じフォルダ\tesseract` → 設定 → PATH → Windows の既定の場所、の順で探す。**同梱版が最優先**
- PyMuPDF は 1.x に固定 (2.0 は起動時に大きなレイアウト解析モデルを読み込み、exe 化で壊れる)

## レイアウト処理 (`layout.py`) の考え方

- **TXT**: Tesseract の段落・行の順をそのまま使う。行の中で文字の高さの 1.5 倍より広い空白があれば全角スペースで区切る。縦書きの行 (縦長) は上から下へ並べる
- **CSV**: 段組みを無視して、縦位置がそろった単語を 1 行にまとめ、各セルの左端の位置で列をそろえる。左端が文字の高さの 2 倍以内なら同じ列。縦書きは 1 行 1 セル
- 信頼度 30 未満の単語は罫線や汚れの誤認識として捨てる
- 苦手: 右寄せの数字、複数列にまたがる見出し、手書き

## 開発の手順

```
pip install -e ".[dev]"
python -m scantext                  # 画面
python -m scantext --cli a.pdf -f csv
ruff check . && ruff format --check .
pytest                              # Linux で画面のテストも回すなら xvfb-run -a pytest
```

- テスト用の Tesseract: Ubuntu なら `apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert fonts-noto-cjk`。入っていなければ OCR のテストは自動で飛ばされる
- exe: `build_windows.bat` (Windows) または CI の `build-windows`。作ったら `python tests/smoke_bundle.py dist/ScanText` で実際に文字起こしできるか確認

## 関連文書

- [テスト計画](TEST_PLAN.md) / [導入チェックリスト](DEPLOY_CHECKLIST.md)
- [手書き問診票の設計](DESIGN_handwriting.md) / [ADR](adr/)
