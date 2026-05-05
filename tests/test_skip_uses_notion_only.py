"""スキップ判定は Notion DB のみを source of truth とする

問題: ローカル `article-index.json` と Notion DB の URL の和集合で
スキップ判定していたため、Notion から記事が消えていても
ローカルインデックスに残っていれば「処理済み」扱いになり、
リストから削除だけされて再翻訳されない問題が発生していた。

修正: スキップ判定は Notion DB の URL のみで行う。
ローカルインデックスは引き続き読み込まれ、translator への
コンテキスト（既存記事一覧・topics サジェスト）として渡される。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from medium_notion.cli import _bookmark_run
from medium_notion.config import Config


@pytest.fixture
def config():
    return Config(
        notion_api_key="ntn_test_key_12345",
        notion_database_id="2a354f2bd9f080c6ad76f4c0caa22b65",
        headless=True,
        log_level="DEBUG",
        claude_model="sonnet",
    )


def _run_bookmark():
    try:
        asyncio.run(
            _bookmark_run(
                list_name="toNotion",
                output="/tmp/test-bookmarks-skip.txt",
                headless=True,
                score=None,
                interval=0,
            )
        )
        return None
    except SystemExit as e:
        return e.code


class TestSkipUsesNotionOnly:
    def test_url_only_in_local_index_is_not_skipped(self, config):
        """ローカル index には居るが Notion から消えた URL は再処理される"""
        stale_url = "https://medium.com/@author/stale-only-in-index-abc123"

        notion_instance = MagicMock()
        notion_instance.check_access = MagicMock(return_value=True)
        notion_instance.list_existing_urls = MagicMock(return_value=set())
        notion_instance.list_existing_topics = MagicMock(return_value=[])
        notion_instance.create_page = MagicMock(return_value=MagicMock(url="https://notion.so/p1"))

        article = MagicMock()
        article.is_preview_only = False
        browser_instance = MagicMock()
        browser_instance.initialize = AsyncMock()
        browser_instance.fetch_reading_list = AsyncMock(return_value=[stale_url])
        browser_instance.fetch_article = AsyncMock(return_value=article)
        browser_instance.remove_articles_from_list = AsyncMock(return_value=([stale_url], []))
        browser_instance.close = AsyncMock()

        translator_instance = MagicMock()
        translator_instance.translate_article = MagicMock(
            return_value=MagicMock(
                japanese_title="再翻訳されたタイトル",
                categories=[],
                topics=[],
                original=MagicMock(url=stale_url),
            )
        )

        stale_index = [{
            "title": "古い翻訳",
            "categories": [],
            "topics": [],
            "url": stale_url,
        }]

        with patch("medium_notion.cli.load_config", return_value=config), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
             patch("medium_notion.cli.NotionClient", return_value=notion_instance), \
             patch("medium_notion.cli.BrowserClient", return_value=browser_instance), \
             patch("medium_notion.cli.TranslationService", return_value=translator_instance), \
             patch("medium_notion.cli._load_article_index", return_value=stale_index):
            _run_bookmark()

        # Notion に存在しないので、ローカル index に居ても再翻訳される
        translator_instance.translate_article.assert_called_once()
        notion_instance.create_page.assert_called_once()

    def test_url_in_notion_is_skipped(self, config):
        """Notion DB にある URL は (ローカル index の有無に関わらず) スキップされる"""
        existing_url = "https://medium.com/@author/already-in-notion-xyz789"

        notion_instance = MagicMock()
        notion_instance.check_access = MagicMock(return_value=True)
        notion_instance.list_existing_urls = MagicMock(return_value={existing_url})
        notion_instance.list_existing_topics = MagicMock(return_value=[])
        notion_instance.create_page = MagicMock()

        browser_instance = MagicMock()
        browser_instance.initialize = AsyncMock()
        browser_instance.fetch_reading_list = AsyncMock(return_value=[existing_url])
        browser_instance.fetch_article = AsyncMock()
        browser_instance.remove_articles_from_list = AsyncMock(return_value=([existing_url], []))
        browser_instance.close = AsyncMock()

        translator_instance = MagicMock()
        translator_instance.translate_article = MagicMock()

        with patch("medium_notion.cli.load_config", return_value=config), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
             patch("medium_notion.cli.NotionClient", return_value=notion_instance), \
             patch("medium_notion.cli.BrowserClient", return_value=browser_instance), \
             patch("medium_notion.cli.TranslationService", return_value=translator_instance), \
             patch("medium_notion.cli._load_article_index", return_value=[]):
            _run_bookmark()

        # Notion に居るので translate も create_page も呼ばれない
        translator_instance.translate_article.assert_not_called()
        notion_instance.create_page.assert_not_called()
        browser_instance.fetch_article.assert_not_called()
