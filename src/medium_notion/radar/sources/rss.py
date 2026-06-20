"""RSS/Atom ソースアダプタ"""

import feedparser
import httpx

from ..config import FeedSpec
from ..models import FeedItem
from ... import logger as log

# フィード取得のタイムアウト（秒）。feedparser.parse(url) はタイムアウトを持たず
# 1 本の遅いフィードで無人実行が無限ハングするため、必ず httpx 経由で取得する。
FETCH_TIMEOUT = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (medium-notion radar)"}


class RssSource:
    """1 つの RSS/Atom フィードから FeedItem を取得する"""

    def __init__(self, spec: FeedSpec):
        self.spec = spec
        self.name = spec.name
        self.layer = spec.layer

    def fetch(self, limit: int | None = None) -> list[FeedItem]:
        """フィード URL をタイムアウト付きで取得して FeedItem のリストを返す"""
        resp = httpx.get(
            self.spec.url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
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
            # content:encoded（RSS）/ content（Atom）に全文があれば取り込む
            content_full = ""
            content = e.get("content")
            if content and isinstance(content, list) and content:
                content_full = content[0].get("value", "") or ""
            items.append(
                FeedItem(
                    url=url,
                    title=e.get("title", "(no title)"),
                    source=self.spec.name,
                    layer=self.spec.layer,
                    summary_raw=e.get("summary", ""),
                    published=e.get("published", None),
                    guid=e.get("id", "") or e.get("guid", ""),
                    content_full=content_full,
                )
            )
        return items
