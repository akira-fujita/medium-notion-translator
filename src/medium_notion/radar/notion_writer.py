"""Tech Radar DB への 1 記事 = 1 行 書き込み"""

from datetime import date

from notion_client import Client as NotionSDKClient

from ..config import Config
from .models import ScoredItem, DeepDive
from .notion_blocks import markdown_to_blocks, _heading, _paragraph, _bullet
from .. import logger as log

MAX_TEXT = 2000
# Notion blocks.children.append は 1 回 100 ブロックまで
NOTION_APPEND_BATCH = 100


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

    def append_item(self, scored: ScoredItem, when: date) -> str | None:
        """1 記事を Tech Radar DB に追加し、作成ページの URL を返す。

        scored.deepdive があればページ本文に深掘り（要約/全文翻訳/ポイント/批判）を書き込む。
        失敗時はログのみ出して None を返す（継続。Slack の Notion リンクが
        その項目だけ省かれる）。
        """
        try:
            resp = self.client.pages.create(
                parent={"data_source_id": self.database_id},
                properties=self._build_properties(scored, when),
            )
        except Exception as e:
            log.warn(f"Notion 追加に失敗（スキップ）: {scored.item.url}: {e}")
            return None

        if scored.deepdive is not None:
            self._write_deepdive_body(resp.get("id"), scored.deepdive, scored.item.url)
        return resp.get("url")

    def _build_deepdive_blocks(self, dd: DeepDive, source_url: str) -> list[dict]:
        """深掘り結果をページ本文ブロック列に変換する。"""
        # 並び: 📖要約 → 🎯ポイント → ⚠️批判 → 📝全文翻訳（末尾）→ 元記事リンク
        # 分析を先に読み、全文翻訳は参照用として末尾に置く。
        blocks: list[dict] = []
        if dd.overview:
            blocks.append(_heading("📖 要約", 2))
            blocks.append(_paragraph(dd.overview))
        if dd.key_points:
            blocks.append(_heading("🎯 立場として押さえるべきポイント", 2))
            blocks.append(_paragraph(dd.key_points))
        if dd.critique:
            blocks.append(_heading("⚠️ 批判的視点", 2))
            blocks.append(_paragraph(dd.critique))
        if dd.fulltext_ok and dd.translation:
            blocks.append(_heading("📝 全文翻訳", 2))
            blocks.extend(markdown_to_blocks(dd.translation))
        elif not dd.fulltext_ok:
            blocks.append(_paragraph("⚠️ 全文を取得できなかったため、要約のみ掲載しています。"))
        if source_url:
            blocks.append({"type": "bookmark", "bookmark": {"url": source_url}})
        return blocks

    def _write_deepdive_body(self, page_id, dd: DeepDive, source_url: str) -> None:
        """深掘りブロックを 100 件ずつページ本文に append する。失敗はログのみ。"""
        if not page_id:
            return
        blocks = self._build_deepdive_blocks(dd, source_url)
        for i in range(0, len(blocks), NOTION_APPEND_BATCH):
            batch = blocks[i : i + NOTION_APPEND_BATCH]
            try:
                self.client.blocks.children.append(block_id=page_id, children=batch)
            except Exception as e:
                log.warn(f"深掘り本文の追記に失敗（スキップ）: {e}")
                return
