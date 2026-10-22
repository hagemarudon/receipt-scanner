from scantext.layout import (
    Word,
    group_rows,
    reading_order_text,
    split_cells,
    table_rows,
    words_from_tesseract,
)


def w(text, left, top, width=None, height=40, block=1, par=1, line=1):
    return Word(text, left, top, width if width is not None else 40 * len(text), height, block, par, line)


def test_words_from_tesseract_skips_empty_and_non_word_levels():
    data = {
        "level": [1, 5, 5, 5],
        "text": ["", "山田", "  ", "太郎"],
        "conf": ["-1", "95.1", "90", 88],  # 文字列でも数値でも来る
        "left": [0, 10, 0, 100],
        "top": [0, 10, 0, 10],
        "width": [500, 80, 0, 80],
        "height": [500, 40, 0, 40],
        "block_num": [0, 1, 1, 1],
        "par_num": [0, 1, 1, 1],
        "line_num": [0, 1, 1, 1],
    }
    assert [x.text for x in words_from_tesseract(data)] == ["山田", "太郎"]


def test_split_cells_joins_close_words_and_splits_wide_gaps():
    cells = split_cells([w("山田", 300, 0), w("氏名", 0, 0), w("太郎", 390, 0)])
    assert [c.text for c in cells] == ["氏名", "山田太郎"]
    assert cells[1].left == 300


def test_reading_order_keeps_paragraphs_and_wide_gaps():
    words = [
        w("診療", 0, 0),
        w("情報", 85, 0),
        w("氏名", 0, 100, par=2),
        w("山田", 400, 100, par=2),
        w("以上", 0, 200, par=2, line=2),
    ]
    assert reading_order_text(words) == "診療情報\n\n氏名　山田\n以上"


def test_group_rows_tolerates_slightly_tilted_scans():
    words = [w("A", 0, 0), w("B", 500, 12), w("C", 0, 100), w("D", 500, 108)]
    assert [[x.text for x in row] for row in group_rows(words)] == [["A", "B"], ["C", "D"]]


def test_table_rows_aligns_columns_even_when_a_cell_is_missing():
    words = [
        w("項目", 0, 0),
        w("結果", 500, 0),
        w("単位", 1000, 0),
        w("血糖", 0, 100),
        w("98", 510, 100),
        w("mg/dL", 1000, 100),
        w("備考", 0, 200),
        w("なし", 1000, 200),
    ]
    assert table_rows(words) == [
        ["項目", "結果", "単位"],
        ["血糖", "98", "mg/dL"],
        ["備考", "", "なし"],
    ]


def test_table_rows_empty():
    assert table_rows([]) == []
    assert reading_order_text([]) == ""


def test_low_confidence_noise_is_dropped():
    data = {
        "level": [5, 5],
        "text": ["|", "様"],
        "conf": [2, 80],
        "left": [0, 50],
        "top": [0, 0],
        "width": [10, 40],
        "height": [20, 40],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }
    assert [x.text for x in words_from_tesseract(data)] == ["様"]
