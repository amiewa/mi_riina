"""チャンネルユーティリティのテスト"""

import pytest
from bot.core.config import AppConfig
from bot.utils.channel_utils import get_required_channels


def test_get_required_channels_default():
    """デフォルト設定でのチャンネル。"""
    config = AppConfig()
    # デフォルトではどれも enabled=False か source="home"
    channels = get_required_channels(config)
    assert set(channels) == {"homeTimeline", "main"}


def test_get_required_channels_global():
    """Wordcloud が global 設定の場合。"""
    config = AppConfig()
    config.posting.wordcloud.enabled = True
    config.posting.wordcloud.timeline_source = "global"
    channels = get_required_channels(config)
    assert set(channels) == {"homeTimeline", "main", "globalTimeline"}


def test_get_required_channels_multiple():
    """複数のソースが指定されている場合。"""
    config = AppConfig()
    config.posting.wordcloud.enabled = True
    config.posting.wordcloud.timeline_source = "local"
    config.posting.poll.enabled = True
    config.posting.poll.timeline_source = "social"
    channels = get_required_channels(config)
    assert set(channels) == {"homeTimeline", "main", "localTimeline", "hybridTimeline"}
