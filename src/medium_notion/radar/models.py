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
    content_full: str = ""  # RSS に全文があれば格納（深掘りの本文取得に使う）

    @property
    def key(self) -> str:
        """重複排除キー（guid 優先、無ければ URL）"""
        return self.guid or self.url


@dataclass
class DeepDive:
    """刺さる記事の深掘り結果（全文翻訳＋分析）"""

    translation: str = ""  # 📝 全文翻訳（マークダウン）
    overview: str = ""     # 📖 要約
    key_points: str = ""   # 🎯 立場として押さえるポイント
    critique: str = ""     # ⚠️ 批判的視点
    fulltext_ok: bool = False  # 本文を取得できたか（False なら翻訳は空・要約のみ）
    failed: bool = False   # 深掘りが失敗したか（True なら書き込み・既読化をスキップし次回再挑戦）


@dataclass
class ScoredItem:
    """Claude 採点後の記事"""

    item: FeedItem
    score: int = 0
    jp_title: str = ""
    summary: str = ""
    why: str = ""
    notion_url: str = ""  # Notion に蓄積したページの URL（pipeline が書き込み後にセット）
    deepdive: "DeepDive | None" = None  # 刺さる記事のみ pipeline がセット


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
