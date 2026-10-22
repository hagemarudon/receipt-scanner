"""Tesseract の単語位置から「読む順のテキスト」と「表 (行×列)」を組み立てる。"""

from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def right(self) -> int:
        return self.left + self.width

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
        words.append(
            Word(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                block=int(data["block_num"][i]),
                par=int(data["par_num"][i]),
                line=int(data["line_num"][i]),
            )
        )
    return words


def _char_height(words: list[Word]) -> float:
    return max(median(w.height for w in words), 1)


def split_cells(line_words: list[Word]) -> list[Cell]:
    """1 行分の単語を、広い空白で区切られたセルに分ける。"""
    if not line_words:
        return []
    ordered = sorted(line_words, key=lambda w: w.left)
    gap_limit = _char_height(ordered) * CELL_GAP_RATIO
    groups: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        if word.left - groups[-1][-1].right > gap_limit:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [Cell(tidy_japanese(" ".join(w.text for w in group)), group[0].left) for group in groups]


def reading_order_text(words: list[Word]) -> str:
    """Tesseract が判定した段落・行の順に並べたテキスト。"""
    lines: dict[tuple[int, int, int], list[Word]] = {}
    for word in words:
        lines.setdefault((word.block, word.par, word.line), []).append(word)

    out: list[str] = []
    previous_par = None
    for (block, par, _line), line_words in lines.items():
        if previous_par is not None and previous_par != (block, par):
            out.append("")
        previous_par = (block, par)
        out.append(TXT_CELL_SEPARATOR.join(c.text for c in split_cells(line_words)))
    return tidy_japanese("\n".join(out))


def group_rows(words: list[Word]) -> list[list[Word]]:
    """縦位置が揃っている単語を同じ行にまとめる (段組みを無視して横一列で見る)。"""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.center_y, w.left)):
        if rows:
            row = rows[-1]
            row_center = sum(w.center_y for w in row) / len(row)
            if abs(word.center_y - row_center) <= _char_height(row) * 0.5:
                row.append(word)
                continue
        rows.append([word])
    return rows


def table_rows(words: list[Word]) -> list[list[str]]:
    """単語を行×列の表にする。列は各セルの左端の位置で揃える。"""
    if not words:
        return []
    rows = [split_cells(row) for row in group_rows(words)]
    tolerance = _char_height(words) * COLUMN_ALIGN_RATIO

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
