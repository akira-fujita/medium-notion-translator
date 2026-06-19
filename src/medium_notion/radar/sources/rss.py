"""RSS/Atom ソースアダプタ"""

import feedparser

from ..config import FeedSpec
from ..models import FeedItem
from ... import logger as log


class RssSource:
    """1 つの RSS/Atom フィードから FeedItem を取得する"""

    def __init__(self, spec: FeedSpec):
        self.spec = spec
        self.name = spec.name
        self.layer = spec.layer

    def fetch(self, limit: int | None = None) -> list[FeedItem]:
        """フィード URL を取得して FeedItem のリストを返す"""
        parsed = feedparser.parse(self.spec.url)
        return self._to_items(parsed, limit)

    def _parse(self, raw: str, limit: int | None = None) -> list[FeedItem]:
        """生 XML 文字列をパースする（テスト用・ネットワーク非依存）"""
        parsed = feedparser.parse(raw)
        return self._to_items(parsed, limit)

    def _to_items(self, parsed, limit: int | None) -> list[FeedItem]:
        entries = parsed.entries
        if limit is not None:
            entries = entries[:limit]
        items: list[FeedItem] = []
        for e in entries:
            url = e.get("link", "")
            if not url:
                continue
            items.append(
                FeedItem(
                    url=url,
                    title=e.get("title", "(no title)"),
                    source=self.spec.name,
                    layer=self.spec.layer,
                    summary_raw=e.get("summary", ""),
                    published=e.get("published", None),
                    guid=e.get("id", "") or e.get("guid", ""),
                )
            )
        return items
