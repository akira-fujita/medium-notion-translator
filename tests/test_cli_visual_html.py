"""翻訳して Notion に登録したら、そのページに視覚版 HTML も付ける（Dock / launchd の bookmark --run）"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from medium_notion.cli import _bookmark_run
from medium_notion.config import Config
from medium_notion.visual_html import HtmlOutcome


URL = "https://medium.com/@author/new-article-abc123"


@pytest.fixture
def config(tmp_path):
    return Config(
        notion_api_key="ntn_test_key_12345",
        notion_database_id="2a354f2bd9f080c6ad76f4c0caa22b65",
        headless=True,
        index_path=tmp_path / "article-index.json",
    )


def _run(config, attach, tmp_path):
    notion = MagicMock()
    notion.check_access.return_value = True
    notion.list_existing_urls.return_value = set()
    notion.list_existing_topics.return_value = []
    page = MagicMock(url="https://notion.so/p1")
    notion.create_page.return_value = page

    browser = MagicMock()
    browser.initialize = AsyncMock()
    browser.fetch_reading_list = AsyncMock(return_value=[URL])
    browser.fetch_article = AsyncMock(return_value=MagicMock(is_preview_only=False))
    browser.remove_articles_from_list = AsyncMock(return_value=([URL], []))
    browser.close = AsyncMock()

    translator = MagicMock()
    result = MagicMock(japanese_title="新しい記事", categories=[], topics=[])
    translator.translate_article.return_value = result

    with patch("medium_notion.cli.load_config", return_value=config), \
         patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
         patch("medium_notion.cli.NotionClient", return_value=notion), \
         patch("medium_notion.cli.BrowserClient", return_value=browser), \
         patch("medium_notion.cli.TranslationService", return_value=translator), \
         patch("medium_notion.cli._load_article_index", return_value=[]), \
         patch("medium_notion.cli.attach_visual_html", attach):
        try:
            asyncio.run(_bookmark_run(
                list_name="toNotion", output=str(tmp_path / "bookmarks.txt"),
                headless=True, score=None, interval=0,
            ))
        except SystemExit:
            pass
    return notion, translator, result, page, browser


class TestBookmarkRunAttachesHtml:
    def test_attaches_html_to_each_created_page(self, config, tmp_path):
        attach = MagicMock(return_value=HtmlOutcome(ok=True))

        notion, translator, result, page, _ = _run(config, attach, tmp_path)

        attach.assert_called_once()
        args, kwargs = attach.call_args
        assert args[:4] == (notion, translator._call_claude, result, page)
        assert kwargs["primer_dir"] == config.visual_primer_dir

    def test_html_failure_does_not_fail_the_article(self, config, tmp_path):
        """HTML は従。失敗しても記事は成功扱いで、Medium のリストからも削除される"""
        attach = MagicMock(return_value=HtmlOutcome(ok=False, reason="図が作れない"))

        _, _, _, _, browser = _run(config, attach, tmp_path)

        assert browser.remove_articles_from_list.call_args.kwargs["urls_to_remove"] == [URL]

    def test_disabled_by_config(self, config, tmp_path):
        """VISUAL_HTML=false なら作らない"""
        config.visual_html = False
        attach = MagicMock()

        _run(config, attach, tmp_path)

        attach.assert_not_called()


class TestMigrateHtml:
    def test_adds_property_once(self, config):
        """medium-notion migrate-html で DB に「HTML」プロパティを足す（冪等）"""
        from click.testing import CliRunner
        from medium_notion.cli import cli

        notion = MagicMock()
        notion.check_access.return_value = True
        notion.ensure_html_property.side_effect = [True, False]

        with patch("medium_notion.cli.load_config", return_value=config), \
             patch("medium_notion.cli.NotionClient", return_value=notion):
            first = CliRunner().invoke(cli, ["migrate-html"])
            second = CliRunner().invoke(cli, ["migrate-html"])

        assert first.exit_code == 0 and "追加しました" in first.output
        assert second.exit_code == 0 and "既にあります" in second.output


class TestHtmlReasonIsPrintedSafely:
    def test_markup_like_reason_does_not_break_the_run(self, config, tmp_path):
        """理由は Claude の出力や例外文。Rich のマークアップとして解釈させない（codex P2）"""
        attach = MagicMock(return_value=HtmlOutcome(ok=False, reason="閉じタグだけ [/bold] が混ざった理由"))

        _, _, _, _, browser = _run(config, attach, tmp_path)

        assert browser.remove_articles_from_list.call_args.kwargs["urls_to_remove"] == [URL]
