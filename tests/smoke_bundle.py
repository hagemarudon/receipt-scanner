"""exe にしたアプリ (同梱の Tesseract を含む) で実際に文字起こしできるか確かめる。

使い方: python tests/smoke_bundle.py dist/ScanText
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SAMPLE = Path(__file__).parent / "data" / "sample_letter.png"
EXPECTED = ["診療情報提供書", "山田太郎", "検査項目"]


def main(dist_dir: str) -> int:
    exe = Path(dist_dir) / ("ScanText.exe" if sys.platform == "win32" else "ScanText")
    with tempfile.TemporaryDirectory() as out:
        for fmt in ("txt", "csv", "pdf"):
            subprocess.run([str(exe), "--cli", str(SAMPLE), "-f", fmt, "-o", out], check=True, timeout=300)
        text = (Path(out) / "sample_letter.txt").read_text(encoding="utf-8-sig")
        missing = [word for word in EXPECTED if word not in text]
        produced = sorted(p.name for p in Path(out).iterdir())
    print("出力:", produced)
    print(text)
    if missing or len(produced) != 3:
        print("足りないもの:", missing, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
