"""チャンネル関連のユーティリティ"""

from bot.core.config import AppConfig

SOURCE_TO_CHANNEL = {
    "home": "homeTimeline",
    "local": "localTimeline",
    "social": "hybridTimeline",
    "global": "globalTimeline",
}


def get_required_channels(config: AppConfig) -> list[str]:
    """設定に基づいて購読が必要な WebSocket チャンネルのリストを返す。"""
    channels = ["homeTimeline", "main"]
    required_sources = set()

    # ワードクラウド用
    if config.posting.wordcloud.enabled:
        required_sources.add(config.posting.wordcloud.timeline_source)

    # アンケート用
    if config.posting.poll.enabled:
        required_sources.add(config.posting.poll.timeline_source)

    # TL連動投稿用
    if config.posting.timeline_post.enabled:
        required_sources.add(config.posting.timeline_post.source)

    for src in required_sources:
        if channel := SOURCE_TO_CHANNEL.get(src):
            if channel not in channels:
                channels.append(channel)

    return channels
