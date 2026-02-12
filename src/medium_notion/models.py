"""データモデル定義"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MediumArticle:
    """Medium から取得した記事"""

    url: str
    title: str
    content: str
    author: str = ""
    publish_date: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    is_preview_only: bool = False

    @property
    def word_count(self) -> int:
        return len(self.content.split())

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass
class TranslationResult:
    """Claude による翻訳結果"""

    original: MediumArticle
    japanese_title: str
    japanese_content: str
    categories: list[str] = field(default_factory=list)
    summary: Optional[str] = None

    @property
    def notion_title(self) -> str:
        return self.japanese_title


@dataclass
class NotionPage:
    """Notion に作成されたページ"""

    page_id: str
    title: str
    url: str
    created_at: datetime = field(default_factory=datetime.now)
