# ADR-0001: オフライン PC 向けの作り方 (Python + Tesseract を同梱したフォルダ配布)

**Status:** Accepted (実機確認待ち)
**Date:** 2026-10-22
**Deciders:** 開発者 (息子)、利用者 (父)

## Context
- 動かす PC は電子カルテが入った**オフラインの Windows (11 の見込み)**。通信は不可、ソフトの導入には院内ルールの確認が要る
- 入力はスキャンした JPG / PDF、出力は .txt / .csv / .pdf を設定で選ぶ
- 利用者はパソコンに詳しくない。開発者は 1 人で、保守に多くの時間はかけられない
- 診療情報を扱うので、外部サービスに画像を送る方式は使えない

## Decision
Python (tkinter の画面) と Tesseract OCR を使い、PyInstaller で **exe・Tesseract・日本語データを 1 つのフォルダに同梱**して配る。フォルダを USB でコピーするだけで動かし、インストーラや管理者権限は使わない。

## Options Considered

### Option A: Python + Tesseract を同梱したフォルダ (採用)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low — 部品が少なく、全部 Python で書ける |
| Cost | 無料 (Tesseract: Apache-2.0、PyMuPDF: AGPL-3.0 は院内利用なら問題なし) |
| Scalability | 1 台・1 日数十枚が前提なので十分 |
| Team familiarity | High — Python のみ |

**Pros:** 完全オフライン / コピーだけで導入 / CI で exe を作り、exe で実際に文字起こしできるかまで自動で確認できる
**Cons:** 手書きはほぼ読めない / 配布サイズが大きめ (〜200MB) / 見た目は Windows 標準アプリほど洗練されない

### Option B: Windows 標準の OCR (Windows.Media.Ocr) を使う C# アプリ
| Dimension | Assessment |
|-----------|------------|
| Complexity | Med — C#/.NET と WinRT の知識が要る |
| Cost | 無料 |
| Scalability | 十分 |
| Team familiarity | Low |

**Pros:** OCR エンジンの同梱が不要で配布が小さい / 見た目が自然
**Cons:** 日本語の言語パックが PC に入っているか次第 (オフライン PC では追加できないことがある) / Linux の CI で検証できない / 開発者に慣れがない

### Option C: 市販の OCR ソフト・スキャナ付属ソフト
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (作らない) |
| Cost | 数千〜数万円 |
| Scalability | 十分 |
| Team familiarity | — |

**Pros:** すぐ使える / 精度が高い製品もある
**Cons:** ライセンス認証にネット接続が要る製品がある / 出力形式を思いどおりにできない / 問診票向けの拡張ができない

## Trade-off Analysis
決め手は「オフライン PC の状態に左右されないこと」と「1 人で保守できること」。B は配布が軽いが、日本語 OCR が PC の言語パック次第になり、オフライン PC では最も確かめにくい点に依存してしまう。A は配布が大きくなる代わりに、必要なものを全部自分で同梱でき、動作を CI で確かめられる。C は今すぐ使えるが、問診票対応 (ADR-0002) のような拡張ができない。

## Consequences
- **楽になる**: 導入 (コピーのみ)、更新 (フォルダの差し替え)、CI での自動確認
- **難しくなる**: 手書きへの対応 (Tesseract では無理なので別の部品が要る → ADR-0002)
- **見直すこと**: 実機で起動・速度・表示を確認した結果 / 院内ルールで USB 持ち込みや exe 実行が禁止されていた場合

## Action Items
1. [ ] GitHub の権限を直して push し、CI で Windows 版を作る
2. [ ] 実機 (Windows 10 IoT Enterprise LTSC) で起動・速度・日本語表示・コピー＆貼り付けを確認 (docs/TEST_PLAN.md の手動確認項目)
3. [ ] 院内のシステム担当に、フォルダ持ち込みと exe 実行の可否を確認
