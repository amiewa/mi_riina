
from bot.utils.text_utils import weighted_keyword_choice


def test_weighted_keyword_choice_empty():
    assert weighted_keyword_choice([]) == []
    assert weighted_keyword_choice([], k=5) == []


def test_weighted_keyword_choice_less_than_k():
    keywords = ["a", "ab"]
    result = weighted_keyword_choice(keywords, k=5)
    assert len(result) == 2
    assert set(result) == set(keywords)


def test_weighted_keyword_choice_basic():
    keywords = ["a", "ab", "abc", "abcd"]
    # 複数回実行して、重みに応じた選択が行われているか（ランダム関数のため厳密ではないがエラーなく動作するか）
    for _ in range(10):
        result = weighted_keyword_choice(keywords, k=2)
        assert len(result) == 2
        assert len(set(result)) == 2  # 重複がないこと
