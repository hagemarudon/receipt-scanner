"""OCR 結果の日本語テキストを整える処理。"""

import re

# ひらがな・カタカナ・漢字・全角記号・全角英数
_JP = r"　-〿぀-ゟ゠-ヿ㐀-䶿一-鿿豈-﫿＀-￯"

# Tesseract は日本語の文字間に半角スペースを入れることがあるので取り除く。
# 「令和 6 年」のような数字との間も詰める。英単語同士の間は残す。
_SPACE_IN_JP = re.compile(rf"(?<=[{_JP}])[ \t]+(?=[{_JP}0-9])|(?<=[{_JP}0-9])[ \t]+(?=[{_JP}])")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def tidy_japanese(text: str) -> str:
    text = _SPACE_IN_JP.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return _MANY_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip("\n")
