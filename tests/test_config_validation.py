"""config バリデーションのテスト"""

import pytest
from pydantic import ValidationError

from bot.core.config import (
    AIConfig,
    AppConfig,
    NightModeConfig,
    PollConfig,
    RandomPostConfig,
    WordcloudConfig,
    load_config,
)


class TestConfigValidation:
    """設定バリデーションのテスト"""

    def test_load_valid_config(self) -> None:
        """正常な設定ファイルを読み込める"""
        config = load_config("config/config.yaml")
        assert config.bot.timezone == "Asia/Tokyo"
        assert config.ai.provider == "gemini"

    def test_invalid_provider(self) -> None:
        """不正な AI プロバイダでエラー"""
        with pytest.raises(ValidationError):
            AIConfig(provider="invalid")  # type: ignore

    def test_probability_out_of_range(self) -> None:
        """probability が 1.0 を超えるとエラー"""
        with pytest.raises(ValidationError):
            RandomPostConfig(probability=1.5)

    def test_probability_negative(self) -> None:
        """probability が負数だとエラー"""
        with pytest.raises(ValidationError):
            RandomPostConfig(probability=-0.1)

    def test_night_mode_valid(self) -> None:
        """正常な夜間モード設定"""
        config = NightModeConfig(start_hour=23, end_hour=5)
        assert config.start_hour == 23
        assert config.end_hour == 5

    def test_night_mode_invalid_hour(self) -> None:
        """不正な時刻（24以上）でエラー"""
        with pytest.raises(ValidationError):
            NightModeConfig(start_hour=24)

    def test_wordcloud_interval_too_small(self) -> None:
        """ワードクラウドの interval_hours が 4 未満だとエラー"""
        with pytest.raises(ValidationError):
            WordcloudConfig(interval_hours=3)

    def test_wordcloud_interval_min(self) -> None:
        """ワードクラウドの interval_hours が 4 であれば OK"""
        config = WordcloudConfig(interval_hours=4)
        assert config.interval_hours == 4

    def test_poll_choice_count_range(self) -> None:
        """アンケート choice_count は 2〜10"""
        config = PollConfig(choice_count=4)
        assert config.choice_count == 4

        with pytest.raises(ValidationError):
            PollConfig(choice_count=1)

        with pytest.raises(ValidationError):
            PollConfig(choice_count=11)

    def test_default_config(self) -> None:
        """デフォルト値で AppConfig が作成できる"""
        config = AppConfig()
        assert config.posting.default_visibility == "home"
        assert config.posting.cooldown_minutes == 10

    def test_wordcloud_empty_colormap(self) -> None:
        """ワードクラウドの colormap が空文字だとエラー"""
        with pytest.raises(ValidationError):
            WordcloudConfig(colormap="")

    def test_config_file_not_found(self) -> None:
        """設定ファイルが見つからない場合はエラー"""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")
