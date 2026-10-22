import pytest

from scantext.textutil import tidy_japanese


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("山 田 太 郎", "山田太郎"),
        ("令和 6 年 4 月 1 日", "令和6年4月1日"),
        ("血圧 は 128/80 でした 。", "血圧は128/80でした。"),
        ("Hello World", "Hello World"),  # 英単語の間のスペースは残す
        ("CT 検査", "CT 検査"),  # 英字と日本語の間は残す (略語が読みやすい)
        ("氏名　山田", "氏名　山田"),  # 全角スペースは列の区切りなので残す
        ("行末の空白   \n次の行", "行末の空白\n次の行"),
        ("段落1\n\n\n\n段落2", "段落1\n\n段落2"),
        ("", ""),
    ],
)
def test_tidy_japanese(raw, expected):
    assert tidy_japanese(raw) == expected
