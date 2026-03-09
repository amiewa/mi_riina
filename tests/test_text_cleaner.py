"""テキストクリーニングのテスト"""

from bot.utils.text_cleaner import clean_note_text


class TestCleanNoteText:
    """clean_note_text のテスト"""

    def test_none_input(self) -> None:
        """None 入力で空文字を返す"""
        assert clean_note_text(None) == ""

    def test_empty_input(self) -> None:
        """空文字入力で空文字を返す"""
        assert clean_note_text("") == ""

    def test_remove_url(self) -> None:
        """URL を除去する"""
        assert (
            clean_note_text("こんにちは https://example.com テスト")
            == "こんにちは  テスト"
        )

    def test_remove_multiple_urls(self) -> None:
        """複数の URL を除去する"""
        result = clean_note_text("URL1 https://a.com URL2 http://b.com 終わり")
        assert "https" not in result
        assert "http" not in result
        assert "終わり" in result

    def test_remove_mention(self) -> None:
        """メンションを除去する"""
        assert clean_note_text("@user テスト").strip() == "テスト"

    def test_remove_remote_mention(self) -> None:
        """リモートメンションを除去する"""
        assert clean_note_text("@user@example.com テスト").strip() == "テスト"

    def test_remove_custom_emoji(self) -> None:
        """カスタム絵文字を除去する"""
        assert clean_note_text("テスト :emoji_name: テスト2") == "テスト  テスト2"

    def test_remove_hashtag(self) -> None:
        """ハッシュタグを除去する"""
        assert clean_note_text("テスト #タグ テスト2") == "テスト  テスト2"

    def test_remove_mfm(self) -> None:
        """MFM 構文を除去する"""
        assert (
            clean_note_text("テスト $[spin テキスト] 終わり")
            == "テスト テキスト 終わり"
        )

    def test_remove_nested_mfm(self) -> None:
        """入れ子の MFM を除去する"""
        # 注: 入れ子MFMは最大5回ループで処理
        result = clean_note_text("$[x2 $[spin テスト]]")
        assert "テスト" in result
        assert "$[" not in result

    def test_plain_text_unchanged(self) -> None:
        """通常テキストはそのまま"""
        assert clean_note_text("普通のテキスト") == "普通のテキスト"

    def test_colon_in_normal_text(self) -> None:
        """通常のコロンはカスタム絵文字と誤認しない"""
        # :英数字: のパターンのみがカスタム絵文字扱い
        result = clean_note_text("時刻は12:30だよ")
        assert "12" in result
        assert "30" in result

    def test_combined_cleanup(self) -> None:
        """複数のクリーニング対象を同時に処理する"""
        text = "@user テスト https://example.com :emoji: #tag"
        result = clean_note_text(text)
        assert "テスト" in result
        assert "@user" not in result
        assert "https" not in result
        assert ":emoji:" not in result
        assert "#tag" not in result
