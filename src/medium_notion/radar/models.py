"""radar データモデル"""

from dataclasses import dataclass, field


@dataclass
class FeedItem:
    """フィードから取得した 1 記事（採点前）"""

    url: str
    title: str
    source: str
    layer: str
    summary_raw: str = ""
    published: str | None = None
    guid: str = ""

    @property
    def key(self) -> str:
        """重複排除キー（guid 優先、無ければ URL）"""
        return self.guid or self.url


@dataclass
class ScoredItem:
    """Claude 採点後の記事"""

    item: FeedItem
    score: int = 0
    jp_title: str = ""
    summary: str = ""
    why: str = ""
    notion_url: str = ""  # Notion に蓄積したページの URL（pipeline が書き込み後にセット）


@dataclass
class Digest:
    """振り分け済みのダイジェスト"""

    highlights: list[ScoredItem] = field(default_factory=list)
    others: list[ScoredItem] = field(default_factory=list)
    # Slack 送信結果: "sent" / "failed" / "skipped"(webhook未設定) / "dry_run" / "empty"
    slack_status: str = "skipped"

    @property
    def is_empty(self) -> bool:
        return not self.highlights and not self.others
