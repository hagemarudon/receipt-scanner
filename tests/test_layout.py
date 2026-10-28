from scantext.layout import (
    Word,
    group_rows,
    layout_text,
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


def test_cells_competing_for_one_column_shift_right():
    words = [w("A", 0, 0), w("B", 500, 0), w("C", 0, 100), w("D", 130, 100), w("E", 500, 100)]
    assert table_rows(words) == [["A", "", "B"], ["C", "D", "E"]]


def test_cell_beyond_last_column_is_appended():
    words = [w("A", 0, 0), w("B", 500, 0), w("C", 0, 100), w("D", 470, 100, width=20), w("E", 560, 100)]
    assert table_rows(words)[1] == ["C", "D", "E"]


def test_vertical_line_reads_top_to_bottom():
    """縦書きの行は左右の位置ではなく上から順に並べる (以前は文字順が崩れていた)。"""
    column = [
        w("情報", 10, 100, width=40, height=80),
        w("診療", 0, 0, width=44, height=80),
        w("書", 5, 190, width=40, height=40),
    ]
    assert [c.text for c in split_cells(column)] == ["診療情報書"]


def test_vertical_line_splits_on_large_vertical_gap():
    column = [w("氏名", 0, 0, width=40, height=80), w("山田", 0, 400, width=40, height=80)]
    assert [c.text for c in split_cells(column)] == ["氏名", "山田"]


def _data(*words):
    """(文字, left, top, width, height, line) の並びを image_to_data の形にする。"""
    n = len(words)
    return {
        "level": [5] * n,
        "text": [x[0] for x in words],
        "conf": [90] * n,
        "left": [x[1] for x in words],
        "top": [x[2] for x in words],
        "width": [x[3] for x in words],
        "height": [x[4] for x in words],
        "block_num": [1] * n,
        "par_num": [1] * n,
        "line_num": [x[5] if len(x) > 5 else 1 for x in words],
    }


def test_table_border_read_as_bar_is_not_output_but_splits_cells():
    """表の縦の罫線が「|」「｜」と読まれても文字としては出さず、列の区切りにする。"""
    data = _data(("氏名", 0, 0, 80, 40), ("|", 90, -10, 6, 60), ("山田", 110, 0, 80, 40), ("｜", 200, -10, 6, 60))
    words = words_from_tesseract(data)
    assert [c.text for c in split_cells(words)] == ["氏名", "山田"]
    assert reading_order_text(words) == "氏名　山田"


def test_bar_stuck_to_letters_is_cut_off():
    words = words_from_tesseract(_data(("|氏名|山田|", 0, 0, 300, 40)))
    assert [w.text for w in words if not w.rule] == ["氏名", "山田"]
    assert [c.text for c in split_cells(words)] == ["氏名", "山田"]


def test_scraps_of_ruled_lines_are_dropped():
    words = words_from_tesseract(_data(("_]", 0, 0, 30, 40), ("[", 50, 0, 10, 40), ("70-109", 100, 0, 240, 40)))
    assert [c.text for c in split_cells(words)] == ["70-109"]


def test_tall_bar_does_not_make_a_line_look_vertical():
    words = [w("血糖", 0, 0), w("98", 200, 0), Word("|", 150, -200, 4, 600, rule=True)]
    assert [c.text for c in split_cells(words)] == ["血糖", "98"]


def test_border_spanning_rows_separates_cells_in_every_row():
    """何行にもまたがる縦線 1 本でも、どの行でも列の区切りになる。"""
    words = [
        w("項目", 0, 0),
        w("結果", 100, 0),
        w("血糖", 0, 100),
        w("98", 100, 100),
        Word("|", 90, -10, 4, 160, rule=True),
    ]
    assert table_rows(words) == [["項目", "結果"], ["血糖", "98"]]


def test_layout_text_keeps_table_rows_together_and_aligns_columns():
    """Tesseract が表の列を別ブロックとして読んでも、行ごとにまとめ、列を全角スペースでそろえる。"""
    words = [
        w("検査結果", 0, 0),
        w("項目", 0, 120, block=2),
        w("血糖", 0, 180, block=2, line=2),
        w("結果", 400, 120, block=3),
        w("98", 400, 180, width=40, block=3, line=2),
        w("備考", 0, 240, block=4),
        w("なし", 400, 242, block=5),
    ]
    assert layout_text(words).splitlines() == [
        "検査結果",
        "",
        "項目　　　　　　　　結果",
        "血糖　　　　　　　　98",
        "備考　　　　　　　　なし",
    ]


def test_layout_text_pads_half_width_text_back_onto_the_grid():
    words = [
        w("HbA1c", 0, 0, width=100),
        w("5.6", 400, 0, width=60),
        w("項目", 0, 60, line=2),
        w("結果", 400, 60, line=2),
    ]
    first, second = layout_text(words).splitlines()
    assert first == "HbA1c " + "　" * 7 + "5.6"
    assert second == "項目　　　　　　　　結果"


def test_layout_text_indents_by_position_and_ignores_rules():
    words = [w("令和6年", 400, 0), w("以上", 0, 60, line=2), Word("|", 0, 0, 4, 100, rule=True)]
    assert layout_text(words) == "　　　　　　　　　　令和6年\n以上"
    assert layout_text([]) == ""
