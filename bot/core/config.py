"""設定バリデーション（pydantic モデル）

起動時に config.yaml の全設定値を検証する。
検証失敗時は起動を中断しエラー内容をログに出力する。
"""

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ========== サブ設定モデル ==========


class TokenizerConfig(BaseModel):
    """形態素解析設定"""

    engine: Literal["sudachi"] = "sudachi"
    sudachi_dict: Literal["small", "core", "full"] = "core"


class BotConfig(BaseModel):
    """bot 基本設定"""

    character_prompt_file: str = "config/character_prompt.md"
    timezone: str = "Asia/Tokyo"
    tokenizer: TokenizerConfig = TokenizerConfig()


class GeminiConfig(BaseModel):
    """Gemini 設定"""

    model: str = "gemini-2.5-flash"
    max_output_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class OllamaConfig(BaseModel):
    """Ollama 設定"""

    model: str = "ministral-3:14b-cloud"
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    num_predict: int = Field(default=1024, ge=1)


class OpenRouterConfig(BaseModel):
    """OpenRouter 設定"""

    model: str = "stepfun/step-3.5-flash:free"
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class FunctionProvidersConfig(BaseModel):
    """機能別AIプロバイダ上書き設定

    null のフィールドは ai.provider の値を使用する。
    """

    reply: Literal["gemini", "ollama", "openrouter"] | None = None
    horoscope: Literal["gemini", "ollama", "openrouter"] | None = None
    timeline_post: Literal["gemini", "ollama", "openrouter"] | None = None
    poll: Literal["gemini", "ollama", "openrouter"] | None = None


class AIConfig(BaseModel):
    """生成 AI 設定"""

    provider: Literal["gemini", "ollama", "openrouter"] = "gemini"
    input_max_chars: int = Field(default=2500, ge=1)
    timeout_seconds: int = Field(default=30, ge=1)
    gemini: GeminiConfig = GeminiConfig()
    ollama: OllamaConfig = OllamaConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    function_providers: FunctionProvidersConfig = FunctionProvidersConfig()


class AdminConfig(BaseModel):
    """bot管理コマンド設定"""

    usernames: list[str] = []


class NightModeConfig(BaseModel):
    """夜間モード設定"""

    enabled: bool = True
    start_hour: int = Field(default=23, ge=0, le=23)
    end_hour: int = Field(default=5, ge=0, le=23)


class AutoDeleteItemConfig(BaseModel):
    """個別自動削除設定"""

    enabled: bool = False
    after_hours: int = Field(default=72, ge=1)


class AutoDeleteConfig(BaseModel):
    """自動削除設定"""

    random_post: AutoDeleteItemConfig = AutoDeleteItemConfig(
        enabled=True, after_hours=72
    )
    scheduled_posts: AutoDeleteItemConfig = AutoDeleteItemConfig(
        enabled=False, after_hours=168
    )
    timeline_post: AutoDeleteItemConfig = AutoDeleteItemConfig(
        enabled=False, after_hours=72
    )
    horoscope: AutoDeleteItemConfig = AutoDeleteItemConfig(
        enabled=False, after_hours=48
    )
    wordcloud: AutoDeleteItemConfig = AutoDeleteItemConfig(
        enabled=False, after_hours=48
    )
    poll: AutoDeleteItemConfig = AutoDeleteItemConfig(enabled=False, after_hours=24)


class RandomPostConfig(BaseModel):
    """ランダム投稿設定"""

    enabled: bool = True
    interval_minutes: int = Field(default=90, ge=1)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class ScheduledPostsConfig(BaseModel):
    """定時投稿設定"""

    enabled: bool = True
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class WeekdayPostsConfig(BaseModel):
    """曜日別投稿設定"""

    enabled: bool = True
    probability: float = Field(default=0.8, ge=0.0, le=1.0)


class TimelinePostConfig(BaseModel):
    """タイムライン連動投稿設定"""

    enabled: bool = True
    mode: Literal["template", "ai"] = "template"
    source: Literal["home", "local", "social", "global"] = "home"
    interval_minutes: int = Field(default=120, ge=1)
    max_notes_fetch: int = Field(default=20, ge=1)
    min_keyword_length: int = Field(default=2, ge=1)
    probability: float = Field(default=0.8, ge=0.0, le=1.0)
    template: str = "{keyword}… りいなも気になるじゃん"
    ai_max_chars: int = Field(default=100, ge=1)
    ai_keyword_count: int = Field(default=3, ge=1)

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        if "{keyword}" not in v:
            raise ValueError("template には '{keyword}' を含める必要があります")
        return v


class HoroscopeConfig(BaseModel):
    """星座占い設定"""

    enabled: bool = False
    mode: Literal["no_ai", "ai"] = "no_ai"
    post_hour: int = Field(default=7, ge=0, le=23)


class WordcloudConfig(BaseModel):
    """ワードクラウド設定"""

    enabled: bool = False
    interval_hours: int = Field(default=12, ge=4)
    timeline_source: Literal["home", "local", "social", "global"] = "home"
    max_stock_size: int = Field(default=2000, ge=1)
    min_stock_words: int = Field(default=30, ge=1)
    min_keyword_length: int = Field(default=2, ge=1)
    max_note_length: int = Field(default=500, ge=1)
    max_keywords_per_note: int = Field(default=10, ge=1)
    analysis_concurrency: int = Field(default=4, ge=1)
    width: int = Field(default=800, ge=100)
    height: int = Field(default=400, ge=100)
    background_color: str = "white"
    colormap: str = "coolwarm"
    font_path: str | None = None

    @field_validator("colormap")
    @classmethod
    def validate_colormap(cls, v: str) -> str:
        if not v:
            raise ValueError("colormap は空文字にできません")
        return v


class PollConfig(BaseModel):
    """アンケート設定"""

    enabled: bool = False
    mode: Literal["tl_word", "static", "ai"] = "tl_word"
    interval_hours: int = Field(default=12, ge=1)
    probability: float = Field(default=0.7, ge=0.0, le=1.0)
    expire_hours: int = Field(default=3, ge=1)
    multiple_choice: bool = False
    choice_count: int = Field(default=4, ge=2, le=10)
    timeline_source: Literal["home", "local", "social", "global"] = "home"
    max_notes_fetch: int = Field(default=50, ge=1)


class EventConfig(BaseModel):
    """記念日イベント設定"""

    enabled: bool = True


class PostingConfig(BaseModel):
    """投稿設定"""

    default_visibility: Literal["home", "public", "followers"] = "home"
    cooldown_minutes: int = Field(default=10, ge=0)
    night_mode: NightModeConfig = NightModeConfig()
    auto_delete: AutoDeleteConfig = AutoDeleteConfig()
    random_post: RandomPostConfig = RandomPostConfig()
    scheduled_posts: ScheduledPostsConfig = ScheduledPostsConfig()
    weekday_posts: WeekdayPostsConfig = WeekdayPostsConfig()
    timeline_post: TimelinePostConfig = TimelinePostConfig()
    horoscope: HoroscopeConfig = HoroscopeConfig()
    wordcloud: WordcloudConfig = WordcloudConfig()
    poll: PollConfig = PollConfig()
    event: EventConfig = EventConfig()


class ReactionRule(BaseModel):
    """リアクションルール"""

    keywords: list[str]
    reactions: list[str]


class ReactionConfig(BaseModel):
    """リアクション設定"""

    enabled: bool = True
    mutual_only: bool = True
    rules_file: str = "config/reaction_rules.yaml"
    rules: list[ReactionRule] = []


class KeywordFollowBackConfig(BaseModel):
    """キーワードフォローバック設定"""

    enabled: bool = True
    trigger: str = "mention_only"
    keywords: list[str] = []


class FollowConfig(BaseModel):
    """フォロー管理設定"""

    auto_follow_back: bool = False
    auto_unfollow_back: bool = True
    unfollow_grace_cycles: int = Field(default=2, ge=1)
    check_interval_minutes: int = Field(default=30, ge=1)
    keyword_follow_back: KeywordFollowBackConfig = KeywordFollowBackConfig()


class RateLimitConfig(BaseModel):
    """レート制限設定"""

    max_per_user_per_hour: int = Field(default=3, ge=1)


class ReplyConfig(BaseModel):
    """リプライ設定"""

    enabled: bool = True
    mutual_only: bool = True
    rate_limit: RateLimitConfig = RateLimitConfig()
    ai_concurrency: int = Field(default=2, ge=1)


class NGWordsConfig(BaseModel):
    """NGワード設定"""

    match_mode: str = "substring"
    local: list[str] = []
    external_urls: list[str] = []
    cache_file: str = "data/ng_words_cache.txt"


class AffinityConfig(BaseModel):
    """親密度設定（Phase 2）"""

    enabled: bool = False
    rank2_threshold: int = Field(default=5, ge=1)
    rank3_threshold: int = Field(default=20, ge=1)


class MaintenanceConfig(BaseModel):
    """メンテナンス設定"""

    enabled: bool = True
    cleanup_time: str = "03:00"
    cleanup_days: int = Field(default=30, ge=1)
    auto_delete_time: str = "03:30"
    backup_time: str = "04:00"
    backup_compress: bool = True
    keep_backups: int = Field(default=7, ge=1)
    log_cleanup_time: str = "05:00"
    log_cleanup_days: int = Field(default=30, ge=1)
    stats_time: str = "06:00"
    ng_word_refresh_time: str = "03:00"


class StorageConfig(BaseModel):
    """ストレージ設定"""

    database_path: str = "data/riina_bot.db"
    log_dir: str = "logs"
    wordcloud_dir: str = "data/wordcloud"


class LoggingConfig(BaseModel):
    """ログ設定"""

    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    file_rotation: str = "midnight"
    file_retention_days: int = Field(default=30, ge=1)
    file_name_pattern: str = "riina_bot_{date}.log"


# ========== ルート設定モデル ==========


class AppConfig(BaseModel):
    """アプリケーション全体の設定"""

    bot: BotConfig = BotConfig()
    ai: AIConfig = AIConfig()
    admin: AdminConfig = AdminConfig()
    posting: PostingConfig = PostingConfig()
    reaction: ReactionConfig = ReactionConfig()
    follow: FollowConfig = FollowConfig()
    reply: ReplyConfig = ReplyConfig()
    ng_words: NGWordsConfig = NGWordsConfig()
    affinity: AffinityConfig = AffinityConfig()
    maintenance: MaintenanceConfig = MaintenanceConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    """config.yaml を読み込み、pydantic バリデーションを行う。

    Args:
        config_path: 設定ファイルのパス

    Returns:
        バリデーション済みの AppConfig

    Raises:
        FileNotFoundError: 設定ファイルが見つからない場合
        pydantic.ValidationError: 設定値が不正な場合
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")

    with open(path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raw_config = {}

    config = AppConfig(**raw_config)
    logger.info("設定ファイルを読み込みました: %s", config_path)
    return config
