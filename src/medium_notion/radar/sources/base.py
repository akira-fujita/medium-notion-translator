"""Source プロトコル — 取得元の共通インターフェース"""

from typing import Protocol

from ..models import FeedItem


class Source(Protocol):
    """記事取得元。将来 GitHub Trending / Reddit もこの形で実装する"""

    name: str
    layer: str

    def fetch(self, limit: int | None = None) -> list[FeedItem]: ...
