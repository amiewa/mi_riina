"""台詞ファイル読み込みユーティリティ

config/serif/ 以下の YAML ファイルを読み込み、
ホットリロード機能を提供する。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class SerifLoader:
    """台詞ファイルの読み込みとホットリロード

    起動時に全台詞ファイルを読み込みメモリに保持し、
    60秒間隔で mtime をチェックして変更があれば再読み込みする。
    """

    # 監視対象の台詞ファイル
    SERIF_FILES = [
        "scheduled.yaml",
        "weekday_posts.yaml",
        "random.yaml",
        "fallback.yaml",
        "poll.yaml",
        "event.yaml",
    ]

    def __init__(self, serif_dir: str = "config/serif") -> None:
        self._serif_dir = Path(serif_dir)
        self._data: dict[str, Any] = {}
        self._mtimes: dict[str, float] = {}
        self._watch_task: asyncio.Task | None = None

    def load_all(self) -> None:
        """起動時に全台詞ファイルを読み込みメモリに保持する。"""
        for filename in self.SERIF_FILES:
            filepath = self._serif_dir / filename
            if filepath.exists():
                self._load_file(filepath)
            else:
                logger.warning("台詞ファイルが見つかりません: %s", filepath)

        logger.info("台詞ファイルを読み込みました（%d 件）", len(self._data))

    def reload_all(self) -> None:
        """全台詞ファイルを再読み込みする（手動トリガー用）。"""
        for filename in self.SERIF_FILES:
            filepath = self._serif_dir / filename
            if filepath.exists():
                self._load_file(filepath)

        logger.info("全台詞ファイルを再読み込みしました")

    def start_watching(self) -> None:
        """ファイル変更監視を開始する。"""
        self._watch_task = asyncio.create_task(self._watch_loop())
        logger.info("台詞ファイル監視を開始しました（60秒間隔）")

    def stop_watching(self) -> None:
        """ファイル変更監視を停止する。"""
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            logger.info("台詞ファイル監視を停止しました")

    def get(self, name: str) -> Any:
        """台詞データを取得する。

        Args:
            name: ファイル名（拡張子なし）例: "scheduled", "random"

        Returns:
            台詞データ（dict / list 等）
        """
        return self._data.get(name)

    @property
    def scheduled(self) -> dict | None:
        """定時投稿台詞"""
        return self._data.get("scheduled")

    @property
    def weekday_posts(self) -> dict | None:
        """曜日別投稿台詞"""
        return self._data.get("weekday_posts")

    @property
    def random(self) -> dict | None:
        """ランダム投稿台詞"""
        return self._data.get("random")

    @property
    def fallback(self) -> dict | None:
        """フォールバック台詞"""
        return self._data.get("fallback")

    @property
    def poll(self) -> dict | None:
        """アンケート台詞"""
        return self._data.get("poll")

    @property
    def event(self) -> dict | None:
        """記念日イベント台詞"""
        return self._data.get("event")

    def _load_file(self, filepath: Path) -> None:
        """個別のYAMLファイルを読み込む。"""
        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            name = filepath.stem  # 拡張子を除いたファイル名
            self._data[name] = data
            self._mtimes[str(filepath)] = os.path.getmtime(filepath)

            logger.debug("台詞ファイルを読み込みました: %s", filepath.name)
        except yaml.YAMLError as e:
            logger.warning(
                "台詞ファイルのパースに失敗しました（旧データを維持）: %s (%s)",
                filepath.name,
                str(e),
            )
        except Exception as e:
            logger.error(
                "台詞ファイルの読み込みに失敗しました: %s (%s)",
                filepath.name,
                str(e),
            )

    async def _watch_loop(self) -> None:
        """60秒間隔で mtime をチェックし、変更があれば再読み込みする。"""
        while True:
            try:
                await asyncio.sleep(60)
                self._reload_if_changed()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("台詞ファイル監視でエラーが発生しました: %s", str(e))

    def _reload_if_changed(self) -> None:
        """mtime が変わったファイルのみ再読み込みする。"""
        for filename in self.SERIF_FILES:
            filepath = self._serif_dir / filename
            if not filepath.exists():
                continue

            current_mtime = os.path.getmtime(filepath)
            old_mtime = self._mtimes.get(str(filepath), 0)

            if current_mtime != old_mtime:
                logger.info("台詞ファイルの変更を検出しました: %s", filepath.name)
                self._load_file(filepath)
