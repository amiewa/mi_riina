"""SQLite データベース管理

aiosqlite を使用した非同期 DB アクセス。
テーブル別のヘルパーメソッドを集約し、各 Manager が SQL を直接書かない設計。
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class Database:
    """SQLite データベースクラス

    各 Manager はこのクラスのヘルパーメソッドを使用して DB にアクセスする。
    SQL の直接記述は避け、ここに集約する。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """DB に接続し、初期設定（プラグマ・テーブル作成）を実行する。"""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row

        # プラグマ設定
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA foreign_keys=ON")

        await self._create_tables()
        await self._create_indexes()
        await self._db.commit()

        logger.info("データベースを初期化しました: %s", self._db_path)

    async def close(self) -> None:
        """DB 接続を閉じる。"""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("データベース接続を閉じました")

    # ========== テーブル・インデックス作成 ==========

    async def _create_tables(self) -> None:
        """全テーブルを作成する（IF NOT EXISTS）。"""
        assert self._db is not None

        # フォロワー管理
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS followers (
                user_id             TEXT PRIMARY KEY,
                username            TEXT NOT NULL,
                followed_at         TEXT NOT NULL,
                i_am_following      BOOLEAN DEFAULT 0,
                missing_count       INTEGER DEFAULT 0
            )
        """)

        # 投稿履歴（自己削除スケジュール + 二重投稿防止）
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id             TEXT,
                post_type           TEXT,
                execution_key       TEXT,
                content             TEXT,
                provider            TEXT,
                posted_at           TEXT NOT NULL,
                scheduled_delete_at TEXT,
                drive_file_id       TEXT,
                deleted             BOOLEAN DEFAULT 0
            )
        """)

        # リプライレート制限
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS reply_rate_limits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                replied_at TEXT NOT NULL
            )
        """)

        # リアクション済みノート（重複防止）
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS reactions (
                note_id    TEXT PRIMARY KEY,
                reacted_at TEXT NOT NULL
            )
        """)

        # ワードクラウド用単語ストック
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS wordcloud_word_stock (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                word       TEXT NOT NULL,
                stocked_at TEXT NOT NULL
            )
        """)

        # 親密度 (Phase 2)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS affinities (
                user_id           TEXT PRIMARY KEY,
                interaction_count INTEGER DEFAULT 0,
                last_interaction  TEXT,
                rank              INTEGER DEFAULT 1
            )
        """)

        # ニックネーム登録
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS nicknames (
                user_id       TEXT PRIMARY KEY,
                nickname      TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
        """)

        # 会話履歴（マルチターン会話）
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                user_message TEXT NOT NULL,
                bot_response TEXT NOT NULL,
                note_id      TEXT,
                created_at   TEXT NOT NULL
            )
        """)

        # 既存DB向けマイグレーション: provider カラム追加
        await self._migrate_add_provider_column()

    async def _migrate_add_provider_column(self) -> None:
        """posts テーブルに provider カラムが存在しない場合に追加する。"""
        assert self._db is not None
        cursor = await self._db.execute("PRAGMA table_info(posts)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if "provider" not in column_names:
            await self._db.execute(
                "ALTER TABLE posts ADD COLUMN provider TEXT"
            )
            logger.info(
                "posts テーブルに provider カラムを追加しました"
            )

    async def _create_indexes(self) -> None:
        """インデックスを作成する。"""
        assert self._db is not None

        # 二重投稿防止（execution_key のユニーク制約）
        await self._db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_execution_key
                ON posts (execution_key)
                WHERE execution_key IS NOT NULL
        """)

        # note_id の一意性
        await self._db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_note_id
                ON posts (note_id)
                WHERE note_id IS NOT NULL
        """)

        # 自己削除対象の検索
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_delete_schedule
                ON posts (deleted, scheduled_delete_at)
                WHERE scheduled_delete_at IS NOT NULL
        """)

        # post_type での絞り込み
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_post_type
                ON posts (post_type)
        """)

        # ワードクラウドストックの古い順削除
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_wordcloud_stock_time
                ON wordcloud_word_stock (stocked_at)
        """)

        # リプライレート制限の検索
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_reply_rate_user_time
                ON reply_rate_limits (user_id, replied_at)
        """)

        # リアクション履歴のクリーンアップ
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_reactions_time
                ON reactions (reacted_at)
        """)

        # 会話履歴の検索（ユーザー × 時刻）
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_history_user_time
                ON conversation_history (user_id, created_at)
        """)

    # ========== 汎用メソッド ==========

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """SQL を実行する。"""
        assert self._db is not None
        await self._db.execute(sql, params)
        await self._db.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        """1行取得する。"""
        assert self._db is not None
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """全行取得する。"""
        assert self._db is not None
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ========== posts 関連 ==========

    async def insert_post(
        self,
        post_type: str,
        execution_key: str | None,
        content: str | None,
        scheduled_delete_at: str | None = None,
        drive_file_id: str | None = None,
        provider: str | None = None,
    ) -> int:
        """投稿レコードを挿入し、IDを返す。
        execution_key の UNIQUE 制約違反時は sqlite3.IntegrityError が発生する。
        """
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO posts
               (post_type, execution_key, content, provider, posted_at,
                scheduled_delete_at, drive_file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                post_type,
                execution_key,
                content,
                provider,
                now,
                scheduled_delete_at,
                drive_file_id,
            ),
        )
        await self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def update_post_note_id(self, post_id: int, note_id: str) -> None:
        """投稿レコードに note_id を設定する。"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE posts SET note_id = ? WHERE id = ?",
            (note_id, post_id),
        )
        await self._db.commit()

    async def delete_post_by_id(self, post_id: int) -> None:
        """投稿レコードを削除する（投稿失敗時のリトライ許可用）。"""
        assert self._db is not None
        await self._db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await self._db.commit()

    async def get_posts_to_delete(self) -> list[dict]:
        """削除スケジュールに達した投稿を取得する。"""
        now = datetime.now(JST).isoformat()
        return await self.fetchall(
            """SELECT id, note_id, post_type, drive_file_id
               FROM posts
               WHERE scheduled_delete_at IS NOT NULL
                 AND scheduled_delete_at < ?
                 AND deleted = 0""",
            (now,),
        )

    async def mark_post_deleted(self, post_id: int) -> None:
        """投稿を削除済みにマークする。"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE posts SET deleted = 1 WHERE id = ?",
            (post_id,),
        )
        await self._db.commit()

    async def get_last_auto_post_time(self) -> str | None:
        """直近の自動投稿（reply以外）の投稿時刻を取得する。"""
        row = await self.fetchone(
            """SELECT posted_at FROM posts
               WHERE post_type != 'reply'
                 AND note_id IS NOT NULL
               ORDER BY posted_at DESC LIMIT 1""",
        )
        return row["posted_at"] if row else None

    # ========== followers 関連 ==========

    async def upsert_follower(
        self,
        user_id: str,
        username: str,
        i_am_following: bool = False,
    ) -> None:
        """フォロワーを追加または更新する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        await self._db.execute(
            """INSERT INTO followers (user_id, username, followed_at, i_am_following, missing_count)
               VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   i_am_following = excluded.i_am_following,
                   missing_count = 0""",
            (user_id, username, now, int(i_am_following)),
        )
        await self._db.commit()

    async def is_mutual(self, user_id: str) -> bool:
        """相互フォローかどうかを判定する。"""
        row = await self.fetchone(
            "SELECT i_am_following FROM followers WHERE user_id = ?",
            (user_id,),
        )
        return row is not None and row["i_am_following"] == 1

    async def increment_missing_count(self, user_id: str) -> int:
        """同期で未検出のカウントをインクリメントし、新しい値を返す。"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE followers SET missing_count = missing_count + 1 WHERE user_id = ?",
            (user_id,),
        )
        await self._db.commit()
        row = await self.fetchone(
            "SELECT missing_count FROM followers WHERE user_id = ?",
            (user_id,),
        )
        return row["missing_count"] if row else 0

    async def reset_missing_count(self, user_id: str) -> None:
        """missing_count をリセットする。"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE followers SET missing_count = 0 WHERE user_id = ?",
            (user_id,),
        )
        await self._db.commit()

    async def delete_follower(self, user_id: str) -> None:
        """フォロワーレコードを削除する。"""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM followers WHERE user_id = ?",
            (user_id,),
        )
        await self._db.commit()

    async def get_all_followers(self) -> list[dict]:
        """全フォロワーを取得する。"""
        return await self.fetchall("SELECT * FROM followers")

    async def update_following_status(self, user_id: str, i_am_following: bool) -> None:
        """フォロー状態を更新する。"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE followers SET i_am_following = ? WHERE user_id = ?",
            (int(i_am_following), user_id),
        )
        await self._db.commit()

    # ========== reactions 関連 ==========

    async def has_reacted(self, note_id: str) -> bool:
        """既にリアクション済みかどうかを確認する。"""
        row = await self.fetchone(
            "SELECT note_id FROM reactions WHERE note_id = ?",
            (note_id,),
        )
        return row is not None

    async def record_reaction(self, note_id: str) -> None:
        """リアクション記録を保存する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO reactions (note_id, reacted_at) VALUES (?, ?)",
            (note_id, now),
        )
        await self._db.commit()

    # ========== wordcloud 関連 ==========

    async def stock_words(self, words: list[str]) -> None:
        """ワードクラウド用の単語をバッチ保存する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        await self._db.executemany(
            "INSERT INTO wordcloud_word_stock (word, stocked_at) VALUES (?, ?)",
            [(word, now) for word in words],
        )
        await self._db.commit()

    async def get_word_stock(self) -> list[str]:
        """ストック済みの全ワードを取得する。"""
        rows = await self.fetchall("SELECT word FROM wordcloud_word_stock")
        return [row["word"] for row in rows]

    async def clear_word_stock(self) -> None:
        """ワードクラウドストックを全件クリアする。"""
        await self.execute("DELETE FROM wordcloud_word_stock")

    async def get_stock_count(self) -> int:
        """ストックされた単語数を取得する。"""
        row = await self.fetchone("SELECT COUNT(*) as cnt FROM wordcloud_word_stock")
        return row["cnt"] if row else 0

    async def trim_word_stock(self, max_size: int) -> None:
        """ストックが max_size を超えた場合、古いものから削除する。"""
        assert self._db is not None
        count = await self.get_stock_count()
        if count > max_size:
            delete_count = count - max_size
            await self._db.execute(
                """DELETE FROM wordcloud_word_stock
                   WHERE id IN (
                       SELECT id FROM wordcloud_word_stock
                       ORDER BY stocked_at ASC
                       LIMIT ?
                   )""",
                (delete_count,),
            )
            await self._db.commit()
            logger.debug(
                "ワードクラウドストックを %d 件削除しました（残り: %d 件）",
                delete_count,
                max_size,
            )

    # ========== rate_limits 関連 ==========

    async def count_recent_replies(self, user_id: str, hours: int = 1) -> int:
        """指定ユーザーの直近 N 時間のリプライ数を取得する。"""
        since = (datetime.now(JST) - timedelta(hours=hours)).isoformat()
        row = await self.fetchone(
            """SELECT COUNT(*) as cnt FROM reply_rate_limits
               WHERE user_id = ? AND replied_at > ?""",
            (user_id, since),
        )
        return row["cnt"] if row else 0

    async def record_reply(self, user_id: str) -> None:
        """リプライ記録を保存する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        await self._db.execute(
            "INSERT INTO reply_rate_limits (user_id, replied_at) VALUES (?, ?)",
            (user_id, now),
        )
        await self._db.commit()

    # ========== nicknames 関連 ==========

    async def upsert_nickname(self, user_id: str, nickname: str) -> None:
        """ニックネームを登録（または更新）する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        await self._db.execute(
            """INSERT INTO nicknames (user_id, nickname, registered_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   nickname = excluded.nickname,
                   registered_at = excluded.registered_at""",
            (user_id, nickname, now),
        )
        await self._db.commit()

    async def get_nickname(self, user_id: str) -> str | None:
        """ニックネームを取得する。未登録の場合は None を返す。"""
        row = await self.fetchone(
            "SELECT nickname FROM nicknames WHERE user_id = ?",
            (user_id,),
        )
        return row["nickname"] if row else None

    async def delete_nickname(self, user_id: str) -> None:
        """ニックネームを削除する。"""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM nicknames WHERE user_id = ?",
            (user_id,),
        )
        await self._db.commit()

    # ========== conversation_history 関連 ==========

    async def save_conversation_turn(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        note_id: str | None = None,
    ) -> None:
        """会話ターンを保存する。"""
        assert self._db is not None
        now = datetime.now(JST).isoformat()
        # 保存時に文字数上限を適用（先頭 500 文字）
        await self._db.execute(
            """INSERT INTO conversation_history
               (user_id, user_message, bot_response, note_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                user_id,
                user_message[:500],
                bot_response[:500],
                note_id,
                now,
            ),
        )
        await self._db.commit()

    async def get_conversation_history(
        self,
        user_id: str,
        max_turns: int,
    ) -> list[dict]:
        """直近N件の会話履歴を取得する（古い順）。

        Returns:
            [{"user_message": str, "bot_response": str, "created_at": str}, ...]
        """
        rows = await self.fetchall(
            """SELECT user_message, bot_response, created_at
               FROM conversation_history
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, max_turns),
        )
        # DESC で取得したものを古い順に並べ直す
        rows.reverse()
        return rows

    async def cleanup_conversation_history(self, days: int) -> int:
        """指定日数より古い会話履歴を削除する。削除件数を返す。"""
        assert self._db is not None
        cutoff = (datetime.now(JST) - timedelta(days=days)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM conversation_history WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.commit()
        deleted = cursor.rowcount if cursor.rowcount is not None else 0
        logger.debug("会話履歴を %d 件削除しました", deleted)
        return deleted

    # ========== クリーンアップ ==========

    async def cleanup(self, cleanup_days: int) -> None:
        """古いデータを削除する。"""
        assert self._db is not None
        cutoff = (datetime.now(JST) - timedelta(days=cleanup_days)).isoformat()

        # リプライレート制限の古い履歴
        await self._db.execute(
            "DELETE FROM reply_rate_limits WHERE replied_at < ?", (cutoff,)
        )

        # リアクション済み記録
        await self._db.execute("DELETE FROM reactions WHERE reacted_at < ?", (cutoff,))

        # 削除済み投稿の履歴
        await self._db.execute(
            "DELETE FROM posts WHERE deleted = 1 AND posted_at < ?", (cutoff,)
        )

        # ワードクラウドストックの残骸
        await self._db.execute(
            "DELETE FROM wordcloud_word_stock WHERE stocked_at < ?", (cutoff,)
        )

        # 会話履歴の古いデータ
        await self._db.execute(
            "DELETE FROM conversation_history WHERE created_at < ?", (cutoff,)
        )

        await self._db.commit()
        logger.info(
            "DBクリーンアップを実行しました（%d日以前のデータを削除）", cleanup_days
        )
