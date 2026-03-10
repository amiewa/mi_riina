"""星座占いマネージャー

2モード対応の星座占い機能:
- no_ai: MD5シードによる乱数ベース（同日は同結果）
- ai: AIクライアントで生成 + バリデーション（失敗時 no_ai フォールバック）
"""

import hashlib
import logging
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.core.ai_client import AIClientBase
from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.utils.ng_word_manager import NGWordManager

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# 12星座データ（シンボル、名前、パディング後の幅に合わせる）
ZODIAC_SIGNS = [
    ("♈", "おひつじ座"),
    ("♉", "おうし座"),
    ("♊", "ふたご座"),
    ("♋", "かに座"),
    ("♌", "しし座"),
    ("♍", "おとめ座"),
    ("♎", "てんびん座"),
    ("♏", "さそり座"),
    ("♐", "いて座"),
    ("♑", "やぎ座"),
    ("♒", "みずがめ座"),
    ("♓", "うお座"),
]

# 最長星座名の文字数（「みずがめ座」= 5文字）に合わせてパディング
MAX_NAME_LEN = 5

# スコア用絵文字
SCORE_EMOJIS = {
    "money": "💰",
    "love": "❤",
    "health": "🍀",
}

# メダル絵文字
MEDAL_EMOJIS = ["🥇", "🥈", "🥉"]

# AIモードのプロンプトテンプレート
HOROSCOPE_PROMPT_TEMPLATE = """
【条件】
- 本日の日付: {today} (この日付に基づいた運勢を生成してください)
- 以下の12星座すべてを必ず含めてください（抜け・重複不可）。
  ♈おひつじ座, ♉おうし座, ♊ふたご座, ♋かに座, ♌しし座, ♍おとめ座,
  ♎てんびん座, ♏さそり座, ♐いて座, ♑やぎ座, ♒みずがめ座, ♓うお座
- 順位は1位〜12位まで毎日ランダムに入れ替えてください。特定の星座が常に上位にならないようにしてください。
- 各星座に「⭐」で1〜5のレート（0.5刻み可: ⭐3.5 のように数値で表記）を付けてください。
- 各星座にキャラクターの口調で今日の運勢コメント（15〜20文字程度）を付けてください。
- 1位は🥇、2位は🥈、3位は🥉を付けてください。4位以降は数字のみ。

【出力フォーマット（このまま投稿します。厳密に守ってください）】
🌟 今日の12星座占いランキング 🌟

🥇 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
🥈 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
🥉 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
4位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
5位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
6位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
7位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
8位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
9位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
10位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
11位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]
12位 [星座名(絵文字付き)] ⭐[評価] [運勢コメント]

【出力ルール】
- 1位から12位まで、すべての星座について漏れなく出力してください（途中で省略せず確実に12行出力すること）。
- 上記フォーマットの投稿文のみを出力してください。
- 「承知しました」「生成します」等の前置きや、末尾の解説文は一切不要です。
"""

# 12星座シンボルのセット（バリデーション用）
ZODIAC_SYMBOLS = {
    "♈",
    "♉",
    "♊",
    "♋",
    "♌",
    "♍",
    "♎",
    "♏",
    "♐",
    "♑",
    "♒",
    "♓",
}


class HoroscopeManager:
    """星座占いマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        ai_client: AIClientBase | None = None,
        ng_word_manager: NGWordManager | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._ai_client = ai_client
        self._ng_word_manager = ng_word_manager
        self._character_prompt = ""

        # キャラクタープロンプトの読み込み
        prompt_path = Path(config.bot.character_prompt_file)
        if prompt_path.exists():
            self._character_prompt = prompt_path.read_text(encoding="utf-8")

    async def execute_horoscope(self) -> None:
        """星座占いを実行する。"""
        horoscope_config = self._config.posting.horoscope

        if not horoscope_config.enabled:
            return

        await self._do_horoscope_post()

    async def _do_horoscope_post(self, force: bool = False) -> None:
        """実際の星座占い投稿処理。AdminManagerからも呼ばれる。"""
        horoscope_config = self._config.posting.horoscope

        now = datetime.now(JST)
        today_str = now.strftime("%Y-%m-%d")
        execution_key = f"horoscope:{today_str}"

        if force:
            execution_key = None

        # execution_key 二重投稿チェック
        try:
            post_id = await self._db.insert_post(
                post_type="horoscope",
                execution_key=execution_key,
                content=None,
            )
        except Exception:
            if not force:
                logger.info(
                    "星座占いは既に投稿済みです（execution_key=%s）",
                    execution_key,
                )
                return
            # force=True の場合は IntegrityError にならないはず（key=None なので）
            raise

        try:
            # モード判定
            if horoscope_config.mode == "ai" and self._ai_client:
                text = await self._generate_ai_horoscope(today_str)
            else:
                text = self._generate_no_ai_horoscope(today_str)

            # 自動削除スケジュール計算
            auto_delete = self._config.posting.auto_delete.horoscope
            scheduled_delete_at = None
            if auto_delete.enabled:
                from datetime import timedelta

                delete_time = now + timedelta(hours=auto_delete.after_hours)
                scheduled_delete_at = delete_time.isoformat()

            # content を更新（先頭200文字まで保存）
            await self._db.execute(
                "UPDATE posts SET content = ?, scheduled_delete_at = ? WHERE id = ?",
                (text[:200], scheduled_delete_at, post_id),
            )

            # ノート投稿
            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )

            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "星座占いを投稿しました（note_id=%s, mode=%s, execution_key=%s）",
                note_id,
                horoscope_config.mode,
                execution_key,
            )

        except Exception as e:
            logger.error("星座占いの投稿に失敗しました: %s", str(e))
            try:
                await self._db.delete_post_by_id(post_id)
            except Exception:
                pass

    def _generate_no_ai_horoscope(self, date_str: str) -> str:
        """no_ai モード: MD5シードによる乱数ベースで星座占いを生成する。

        同じ日は必ず同じ結果になる。
        """
        # MD5シードの生成
        seed_str = date_str.replace("-", "")
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
        rng = random.Random(seed)

        # 各星座にスコアを割り当て
        results = []
        for symbol, name in ZODIAC_SIGNS:
            money = rng.randint(1, 3)
            love = rng.randint(1, 3)
            health = rng.randint(1, 3)
            total = money + love + health
            results.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "money": money,
                    "love": love,
                    "health": health,
                    "total": total,
                }
            )

        # 合計スコアで降順ソート（安定ソートで同点は入力順を維持）
        results.sort(key=lambda x: x["total"], reverse=True)

        # フォーマット
        lines = ["🌟 今日の12星座占いランキング 🌟", ""]

        for i, r in enumerate(results):
            # 順位表示
            if i < 3:
                rank_str = MEDAL_EMOJIS[i]
            else:
                rank_str = f"{i + 1}位"
                # 2桁の場合はそのまま、1桁の場合は全角スペースを追加
                if i + 1 < 10:
                    rank_str = f"{i + 1}位"
                else:
                    rank_str = f"{i + 1}位"

            # 星座名をパディング
            name_padded = r["name"] + "　" * (MAX_NAME_LEN - len(r["name"]))

            # スコア表示（絵文字 + 全角スペースパディング）
            money_score = SCORE_EMOJIS["money"] * r["money"] + "　" * (3 - r["money"])
            love_score = SCORE_EMOJIS["love"] * r["love"] + "　" * (3 - r["love"])
            health_score = SCORE_EMOJIS["health"] * r["health"] + "　" * (
                3 - r["health"]
            )

            line = f"{rank_str} {r['symbol']}{name_padded}金運{money_score}恋愛{love_score}健康{health_score}"
            lines.append(line)

        return "\n".join(lines)

    async def _generate_ai_horoscope(self, date_str: str) -> str:
        """ai モード: AIクライアントで星座占いを生成する。

        バリデーション失敗時は no_ai にフォールバックする。
        """
        today_display = date_str  # YYYY-MM-DD
        prompt = HOROSCOPE_PROMPT_TEMPLATE.format(today=today_display)

        # 最大1回リトライ
        for attempt in range(2):
            try:
                text = await self._ai_client.generate(
                    user_prompt=prompt,
                    system_prompt=self._character_prompt,
                )

                # バリデーション: 12星座が全て含まれているか
                if self._validate_ai_horoscope(text):
                    # NGワードチェック
                    if (
                        self._ng_word_manager
                        and self._ng_word_manager.contains_ng_word(text)
                    ):
                        logger.warning(
                            "AI占いにNGワードが含まれています。no_ai にフォールバックします"
                        )
                        return self._generate_no_ai_horoscope(date_str)
                    return text

                logger.warning(
                    "AI占いのバリデーション失敗（試行 %d/2）: 12星座が揃っていません",
                    attempt + 1,
                )

            except Exception as e:
                logger.error(
                    "AI占い生成に失敗しました（試行 %d/2）: %s",
                    attempt + 1,
                    str(e),
                )

        # リトライ後もダメなら no_ai フォールバック
        logger.warning("AI占いが2回失敗しました。no_ai モードにフォールバックします")
        return self._generate_no_ai_horoscope(date_str)

    @staticmethod
    def _validate_ai_horoscope(text: str) -> bool:
        """AI出力に12星座のシンボルが全て含まれているか検証する。"""
        found_symbols = {char for char in text if char in ZODIAC_SYMBOLS}
        if found_symbols != ZODIAC_SYMBOLS:
            missing = ZODIAC_SYMBOLS - found_symbols
            logger.debug("不足している星座シンボル: %s", missing)
            return False
        return True
