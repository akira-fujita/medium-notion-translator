"""Tech Radar DB への 1 記事 = 1 行 書き込み"""

from datetime import date

from notion_client import Client as NotionSDKClient

from ..config import Config
from .models import ScoredItem
from .. import logger as log

MAX_TEXT = 2000


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": (content or "")[:MAX_TEXT]}}]


class RadarNotionWriter:
    """Tech Radar データベースに採点済み記事を追加する"""

    def __init__(self, config: Config):
        self.client = NotionSDKClient(auth=config.notion_api_key)
        self.database_id = config.radar_notion_database_id_formatted

    def _build_properties(self, scored: ScoredItem, when: date) -> dict:
        title = scored.jp_title or scored.item.title
        return {
            "名前": {"title": [{"type": "text", "text": {"content": title[:MAX_TEXT]}}]},
            "URL": {"url": scored.item.url},
            "Date": {"date": {"start": when.isoformat()}},
            "Source": {"select": {"name": scored.item.source}},
            "Layer": {"select": {"name": scored.item.layer}},
            "Summary": {"rich_text": _rich_text(scored.summary)},
            "Why": {"rich_text": _rich_text(scored.why)},
            "Score": {"number": scored.score},
        }

    def append_item(self, scored: ScoredItem, when: date) -> None:
        """1 記事を Tech Radar DB に追加する。失敗時はログのみ（継続）"""
        try:
            self.client.pages.create(
                parent={"data_source_id": self.database_id},
                properties=self._build_properties(scored, when),
            )
        except Exception as e:
            log.warn(f"Notion 追加に失敗（スキップ）: {scored.item.url}: {e}")
