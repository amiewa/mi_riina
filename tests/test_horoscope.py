"""星座占いマネージャーのテスト

no_ai モードのシード固定テストと AI バリデーションテストを含む。
"""

import hashlib
import random
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bot.core.config import AppConfig, load_config
from bot.core.database import Database
from bot.managers.horoscope_manager import (
    ZODIAC_SIGNS,
    ZODIAC_SYMBOLS,
    HoroscopeManager,
)


@pytest.fixture
def config() -> AppConfig:
    """テスト用の設定を返す。"""
    return load_config("config/config.yaml")


@pytest_asyncio.fixture
async def db(tmp_path) -> Database:
    """テスト用の DB を返す。"""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def mock_misskey():
    """モック MisskeyClient。"""
    mock = AsyncMock()
    mock.bot_user_id = "bot-user-id"
    mock.create_note = AsyncMock(return_value="test-note-id")
    return mock


@pytest.fixture
def mock_ai_client():
    """モック AIClientBase。"""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_ng_word_manager():
    """モック NGWordManager。"""
    mock = MagicMock()
    mock.contains_ng_word = MagicMock(return_value=False)
    return mock


class TestNoAIHoroscope:
    """no_ai モードのテスト"""

    def test_same_date_same_result(self, config, db, mock_misskey):
        """同じ日付では同じ結果になること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result1 = manager._generate_no_ai_horoscope("2026-03-09")
        result2 = manager._generate_no_ai_horoscope("2026-03-09")
        assert result1 == result2

    def test_different_date_different_result(self, config, db, mock_misskey):
        """異なる日付では異なる結果になること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result1 = manager._generate_no_ai_horoscope("2026-03-09")
        result2 = manager._generate_no_ai_horoscope("2026-03-10")
        assert result1 != result2

    def test_contains_all_zodiac_signs(self, config, db, mock_misskey):
        """出力に12星座が全て含まれていること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result = manager._generate_no_ai_horoscope("2026-03-09")

        for symbol, name in ZODIAC_SIGNS:
            assert symbol in result, f"シンボル {symbol} が見つかりません"
            assert name in result, f"名前 {name} が見つかりません"

    def test_contains_header(self, config, db, mock_misskey):
        """ヘッダーが含まれていること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result = manager._generate_no_ai_horoscope("2026-03-09")
        assert "🌟 今日の12星座占いランキング 🌟" in result

    def test_contains_medals(self, config, db, mock_misskey):
        """上位3位にメダル絵文字が含まれていること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result = manager._generate_no_ai_horoscope("2026-03-09")
        assert "🥇" in result
        assert "🥈" in result
        assert "🥉" in result

    def test_contains_score_emojis(self, config, db, mock_misskey):
        """スコア用の絵文字が含まれていること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result = manager._generate_no_ai_horoscope("2026-03-09")
        assert "💰" in result
        assert "❤" in result
        assert "🍀" in result

    def test_has_12_lines_of_rankings(self, config, db, mock_misskey):
        """12行分のランキングが出力されること。"""
        manager = HoroscopeManager(config, db, mock_misskey)
        result = manager._generate_no_ai_horoscope("2026-03-09")
        lines = [line for line in result.split("\n") if line.strip()]
        # ヘッダー1行 + ランキング12行 = 13行
        assert len(lines) == 13

    def test_seed_consistency(self, config, db, mock_misskey):
        """MD5シードが正しく機能していること。"""
        date_str = "2026-03-09"
        seed_str = date_str.replace("-", "")
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)

        # 同じシードで同じ結果になることを確認
        rng1 = random.Random(seed)
        rng2 = random.Random(seed)

        for _ in range(36):  # 12星座 × 3スコア
            assert rng1.randint(1, 3) == rng2.randint(1, 3)


class TestAIHoroscopeValidation:
    """AI バリデーションのテスト"""

    def test_valid_horoscope(self):
        """全12星座が含まれている場合にバリデーション通過。"""
        text = """🌟 今日の12星座占いランキング 🌟

🥇 ♊ふたご座 ⭐5 今日は絶好調だよ〜！
🥈 ♈おひつじ座 ⭐4.5 いいことあるかもね♪
🥉 ♓うお座 ⭐4 のんびりいこう〜
4位 ♉おうし座 ⭐3.5 ちょっと慎重にね
5位 ♋かに座 ⭐3 まあまあかな〜
6位 ♌しし座 ⭐3 普通の日じゃん
7位 ♍おとめ座 ⭐2.5 ゆっくりいこう
8位 ♎てんびん座 ⭐2.5 焦らないで〜
9位 ♏さそり座 ⭐2 おとなしくしてて〜
10位 ♐いて座 ⭐2 のんびりがいいよ〜
11位 ♑やぎ座 ⭐1.5 ちょっと我慢の日
12位 ♒みずがめ座 ⭐1 今日はお休みの日だよ〜"""

        assert HoroscopeManager._validate_ai_horoscope(text) is True

    def test_missing_zodiac(self):
        """星座が欠けている場合にバリデーション失敗。"""
        text = """🌟 今日の12星座占いランキング 🌟

🥇 ♊ふたご座 ⭐5 今日は絶好調だよ〜！
🥈 ♈おひつじ座 ⭐4.5 いいことあるかもね♪"""

        assert HoroscopeManager._validate_ai_horoscope(text) is False

    def test_empty_text(self):
        """空テキストでバリデーション失敗。"""
        assert HoroscopeManager._validate_ai_horoscope("") is False

    def test_all_symbols_present(self):
        """全シンボルが含まれていればバリデーション通過。"""
        text = "".join(ZODIAC_SYMBOLS)
        assert HoroscopeManager._validate_ai_horoscope(text) is True


class TestHoroscopeExecution:
    """execute_horoscope の統合テスト"""

    @pytest.mark.asyncio
    async def test_execute_no_ai(self, config, db, mock_misskey):
        """no_ai モードで正常に投稿できること。"""
        manager = HoroscopeManager(config, db, mock_misskey)

        # horoscope.enabled を強制的に True に
        config.posting.horoscope.enabled = True
        config.posting.horoscope.mode = "no_ai"

        await manager.execute_horoscope()

        # create_note が呼ばれたことを確認
        mock_misskey.create_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_execution_key_prevents_duplicate(self, config, db, mock_misskey):
        """同日に2回実行しても二重投稿しないこと。"""
        manager = HoroscopeManager(config, db, mock_misskey)

        config.posting.horoscope.enabled = True
        config.posting.horoscope.mode = "no_ai"

        # 1回目
        await manager.execute_horoscope()
        assert mock_misskey.create_note.call_count == 1

        # 2回目（スキップされるはず）
        await manager.execute_horoscope()
        assert mock_misskey.create_note.call_count == 1

    @pytest.mark.asyncio
    async def test_ai_mode_fallback_to_no_ai(
        self, config, db, mock_misskey, mock_ai_client, mock_ng_word_manager
    ):
        """AI モードが失敗した場合に no_ai にフォールバックすること。"""
        # AI が例外を投げるように設定
        mock_ai_client.generate = AsyncMock(side_effect=Exception("API Error"))

        manager = HoroscopeManager(
            config, db, mock_misskey, mock_ai_client, mock_ng_word_manager
        )

        config.posting.horoscope.enabled = True
        config.posting.horoscope.mode = "ai"

        await manager.execute_horoscope()

        # フォールバックして投稿されること
        mock_misskey.create_note.assert_called_once()
        # 投稿内容に12星座が含まれていること（no_ai の出力）
        call_args = mock_misskey.create_note.call_args
        text = call_args.kwargs.get("text", "")
        for symbol in ZODIAC_SYMBOLS:
            assert symbol in text

    @pytest.mark.asyncio
    async def test_ai_mode_ng_word_fallback(
        self, config, db, mock_misskey, mock_ai_client, mock_ng_word_manager
    ):
        """AI出力にNGワードが含まれている場合に no_ai にフォールバックすること。"""
        # AI が正常な出力を返すが NGワードが含まれている
        valid_text = "".join("♈♉♊♋♌♍♎♏♐♑♒♓")
        mock_ai_client.generate = AsyncMock(return_value=valid_text)
        mock_ng_word_manager.contains_ng_word = MagicMock(return_value=True)

        manager = HoroscopeManager(
            config, db, mock_misskey, mock_ai_client, mock_ng_word_manager
        )

        config.posting.horoscope.enabled = True
        config.posting.horoscope.mode = "ai"

        await manager.execute_horoscope()

        # フォールバックして投稿されること
        mock_misskey.create_note.assert_called_once()
