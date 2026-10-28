"""Tesseract の単語位置から「読む順のテキスト」と「表 (行×列)」を組み立てる。"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, replace
from statistics import median

from .textutil import tidy_japanese

# 単語の間がこの倍率 (文字の高さ基準) より広ければ、別のセル (列) とみなす
CELL_GAP_RATIO = 1.5
# 列の左端がこの倍率 (文字の高さ基準) 以内なら同じ列とみなす
COLUMN_ALIGN_RATIO = 2.0
# 信頼度がこれより低い単語は、紙の汚れや罫線の誤認識とみなして捨てる
MIN_CONFIDENCE = 30
# TXT 出力でセルの間に入れる区切り
TXT_CELL_SEPARATOR = "　"
# 行の間がこの倍率 (文字の高さ基準) より広ければ、TXT で空行を入れる
PARAGRAPH_GAP_RATIO = 1.5
# 表の縦の罫線は Tesseract が「|」「｜」などと読んでしまう
BAR_CHARS = "|｜│┃¦丨〡"
# 単語がこれらの文字だけなら罫線 (横線・角の切れ端) とみなす
RULE_CHARS = BAR_CHARS + "[]［］_＿"
_BARS = re.compile(f"([{re.escape(BAR_CHARS)}]+)")


@dataclass(frozen=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    block: int = 0
    par: int = 0
    line: int = 0
    # 表の罫線を読み違えたもの。文字としては出さず、セルの区切りにだけ使う
    rule: bool = False

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


@dataclass(frozen=True)
class Cell:
    text: str
    left: int


def words_from_tesseract(data: dict) -> list[Word]:
    """pytesseract.image_to_data(output_type=DICT) の結果から単語を取り出す。"""
    words = []
    for i, text in enumerate(data.get("text", [])):
        text = (text or "").strip()
        if not text or int(data["level"][i]) != 5:
            continue
        if float(data["conf"][i]) < MIN_CONFIDENCE:
            continue
        word = Word(
            text=text,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
            block=int(data["block_num"][i]),
            par=int(data["par_num"][i]),
            line=int(data["line_num"][i]),
        )
        words.extend(_split_rules(word))
    return words


def _split_rules(word: Word) -> list[Word]:
    """罫線を読み違えた文字を、文字から切り離して罫線の印 (rule) にする。

    「氏名|山田」のように罫線が文字にくっついて 1 単語になることもあるので、
    「|」の位置で分け、それぞれの位置は文字数の割合で見積もる。
    """
    if all(char in RULE_CHARS for char in word.text):
        return [replace(word, rule=True)]
    if not _BARS.search(word.text):
        return [word]
    vertical = word.height > word.width * 2
    length = word.height if vertical else word.width
    pieces = []
    position = 0
    for text in _BARS.split(word.text):
        if text:
            offset = length * position // len(word.text)
            size = max(length * len(text) // len(word.text), 1)
            if vertical:
                geometry = {"top": word.top + offset, "height": size}
            else:
                geometry = {"left": word.left + offset, "width": size}
            pieces.append(replace(word, text=text, rule=text[0] in BAR_CHARS, **geometry))
        position += len(text)
    return pieces


def _char_height(words: list[Word]) -> float:
    return max(median(w.height for w in words), 1)


def _letters(words: list[Word]) -> list[Word]:
    return [w for w in words if not w.rule]


def split_cells(line_words: list[Word]) -> list[Cell]:
    """1 行分の単語を、広い空白か罫線で区切られたセルに分ける。罫線そのものは出さない。"""
    letters = _letters(line_words)
    if not letters:
        return []
    if _is_vertical(letters):
        # 縦書きの行は上から下へ。文字の大きさは横幅で測る
        ordered = sorted(line_words, key=lambda w: w.top)
        char_size = max(median(w.width for w in letters), 1)

        def gap(a: Word, b: Word) -> int:
            return b.top - a.bottom
    else:
        ordered = sorted(line_words, key=lambda w: w.left)
        char_size = _char_height(letters)

        def gap(a: Word, b: Word) -> int:
            return b.left - a.right

    groups: list[list[Word]] = [[]]
    for word in ordered:
        if word.rule:
            if groups[-1]:
                groups.append([])
        elif groups[-1] and gap(groups[-1][-1], word) > char_size * CELL_GAP_RATIO:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [Cell(tidy_japanese(" ".join(w.text for w in group)), group[0].left) for group in groups if group]


def _is_vertical(line_words: list[Word]) -> bool:
    """行全体が縦に長ければ縦書きの行とみなす。"""
    if len(line_words) < 2:
        return False
    width = max(w.right for w in line_words) - min(w.left for w in line_words)
    height = max(w.bottom for w in line_words) - min(w.top for w in line_words)
    return height > width * 2


def _tesseract_lines(words: list[Word]) -> list[list[Word]]:
    lines: dict[tuple[int, int, int], list[Word]] = {}
    for word in words:
        lines.setdefault((word.block, word.par, word.line), []).append(word)
    return list(lines.values())


def reading_order_text(words: list[Word]) -> str:
    """Tesseract が判定した段落・行の順に並べたテキスト (縦書き用)。"""
    out: list[str] = []
    previous_par = None
    for line_words in _tesseract_lines(words):
        cells = split_cells(line_words)
        if not cells:
            continue
        par = (line_words[0].block, line_words[0].par)
        if previous_par is not None and previous_par != par:
            out.append("")
        previous_par = par
        out.append(TXT_CELL_SEPARATOR.join(c.text for c in cells))
    return tidy_japanese("\n".join(out))


def _text_width(text: str) -> float:
    """等幅フォントでの幅。全角 1 文字を 1 とする。"""
    return sum(0.5 if unicodedata.east_asian_width(char) in "NaH" else 1 for char in text)


def layout_text(words: list[Word]) -> str:
    """紙の上の位置どおりに並べたテキスト (横書き用)。

    Tesseract は表の列や離れた項目を別のブロックとして読むので、その順に並べると
    表の行がばらばらになる。ここでは Tesseract の行を縦位置で横一列にまとめ、
    セルの左端の位置に合わせて全角スペースで字下げする。等幅フォント (メモ帳・電子カルテ) に
    貼り付けたときに、列が紙と同じようにそろう。
    """
    letters = _letters(words)
    if not letters:
        return ""
    char_size = _char_height(letters)
    origin = min(w.left for w in letters)

    # Tesseract の 1 行は (傾いていても) まとめて扱い、縦位置が重なる行どうしをつなぐ
    rows: list[tuple[float, float, list[Cell]]] = []  # (上端, 下端, セル)
    lines = [line for line in _tesseract_lines(words) if _letters(line)]
    for line in sorted(lines, key=lambda line: median(w.center_y for w in _letters(line))):
        line_letters = _letters(line)
        top = min(w.top for w in line_letters)
        bottom = max(w.bottom for w in line_letters)
        center = median(w.center_y for w in line_letters)
        cells = split_cells(line)
        if rows and abs(center - (rows[-1][0] + rows[-1][1]) / 2) <= char_size * 0.5:
            row_top, row_bottom, row_cells = rows[-1]
            rows[-1] = (min(row_top, top), max(row_bottom, bottom), row_cells + cells)
        else:
            rows.append((top, bottom, cells))

    out: list[str] = []
    previous_bottom = None
    for top, bottom, cells in rows:
        if previous_bottom is not None and top - previous_bottom > char_size * PARAGRAPH_GAP_RATIO:
            out.append("")
        previous_bottom = bottom
        line = ""
        width = 0.0
        for cell in sorted(cells, key=lambda c: c.left):
            if width % 1:
                # 半角で終わって半文字ずれたぶんを半角スペースで戻す
                line += " "
                width = math.ceil(width)
            column = round((cell.left - origin) / char_size)
            pad = max(column - int(width), 1 if line else 0)
            line += TXT_CELL_SEPARATOR * pad + cell.text
            width += pad + _text_width(cell.text)
        out.append(line)
    return "\n".join(out)


def group_rows(words: list[Word]) -> list[list[Word]]:
    """縦位置が揃っている単語を同じ行にまとめる (段組みを無視して横一列で見る)。

    罫線は、縦に重なっているすべての行に入れる (何行にもまたがる縦線は、どの行でも列の区切り)。
    """
    rows: list[list[Word]] = []
    for word in sorted(_letters(words), key=lambda w: (w.center_y, w.left)):
        if rows:
            row = rows[-1]
            row_center = sum(w.center_y for w in row) / len(row)
            if abs(word.center_y - row_center) <= _char_height(row) * 0.5:
                row.append(word)
                continue
        rows.append([word])
    for rule in (w for w in words if w.rule):
        for row in rows:
            row_center = sum(w.center_y for w in row) / len(row)
            if rule.top <= row_center <= rule.bottom:
                row.append(rule)
    return rows


def table_rows(words: list[Word]) -> list[list[str]]:
    """単語を行×列の表にする。列は各セルの左端の位置で揃える。"""
    letters = _letters(words)
    if not letters:
        return []
    rows = [split_cells(row) for row in group_rows(words)]
    tolerance = _char_height(letters) * COLUMN_ALIGN_RATIO

    # 左端の位置が近いものをまとめて列の基準位置にする
    anchors: list[float] = []
    for left in sorted(cell.left for row in rows for cell in row):
        if anchors and left - anchors[-1] <= tolerance:
            continue
        anchors.append(left)

    table = []
    for row in rows:
        values = [""] * len(anchors)
        for cell in row:
            column = min(range(len(anchors)), key=lambda i: abs(anchors[i] - cell.left))
            while column < len(anchors) and values[column]:
                column += 1
            if column == len(anchors):
                values.append(cell.text)
            else:
                values[column] = cell.text
        while values and not values[-1]:
            values.pop()
        table.append(values)
    return table
