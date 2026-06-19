"""radar 既読ストア — 処理済み記事キーを JSON で永続化"""

import json
import os

from .models import FeedItem


class SeenStore:
    """処理済み記事のキー（guid/URL）を保持し、新着を判定する"""

    def __init__(self, path: str):
        self.path = path
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if not os.path.exists(self.path):
            return set()
        try:
            with open(self.path, encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()

    def filter_new(self, items: list[FeedItem]) -> list[FeedItem]:
        """既読キーと、同一バッチ内の重複を除外した新着リストを返す"""
        result: list[FeedItem] = []
        batch_keys: set[str] = set()
        for item in items:
            if item.key in self._seen or item.key in batch_keys:
                continue
            batch_keys.add(item.key)
            result.append(item)
        return result

    def mark_seen(self, items: list[FeedItem]) -> None:
        """キーを記録してファイルへ保存する"""
        for item in items:
            self._seen.add(item.key)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self._seen), f, ensure_ascii=False, indent=2)
