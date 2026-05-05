"""致命的エラー時に Slack 通知が送られることのテスト

CI / launchd で無人実行する際、セッション切れや認証失敗などの
致命的エラーをユーザーに気づかせる経路を担保する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from medium_notion.cli import _bookmark_run
from medium_notion.config import Config


@pytest.fixture
def config_with_webhook():
    return Config(
        notion_api_key="ntn_test_key_12345",
        notion_database_id="2a354f2bd9f080c6ad76f4c0caa22b65",
        headless=True,
        log_level="DEBUG",
        claude_model="sonnet",
        slack_webhook_url="https://hooks.slack.com/services/TEST",
    )


@pytest.fixture
def config_without_webhook():
    return Config(
        notion_api_key="ntn_test_key_12345",
        notion_database_id="2a354f2bd9f080c6ad76f4c0caa22b65",
        headless=True,
        log_level="DEBUG",
        claude_model="sonnet",
    )


def _run_bookmark(list_name="toNotion"):
    """_bookmark_run を実行して SystemExit を捕捉する"""
    try:
        asyncio.run(
            _bookmark_run(
                list_name=list_name,
                output="/tmp/test-bookmarks.txt",
                headless=True,
                score=None,
                interval=0,
            )
        )
        return None
    except SystemExit as e:
        return e.code


class TestFatalNotifyOnClaudeCliMissing:
    def test_sends_slack_when_claude_cli_missing(self, config_with_webhook):
        notify_mock = AsyncMock(return_value=True)
        with patch("medium_notion.cli.load_config", return_value=config_with_webhook), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=False), \
             patch("medium_notion.slack.notify_fatal_error", notify_mock):
            exit_code = _run_bookmark()

        assert exit_code == 1
        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        assert kwargs["error_type"] == "ClaudeCodeCLIMissing"
        assert kwargs["webhook_url"] == "https://hooks.slack.com/services/TEST"

    def test_no_slack_when_webhook_unset(self, config_without_webhook):
        notify_mock = AsyncMock(return_value=False)
        with patch("medium_notion.cli.load_config", return_value=config_without_webhook), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=False), \
             patch("medium_notion.slack.notify_fatal_error", notify_mock):
            exit_code = _run_bookmark()

        assert exit_code == 1
        notify_mock.assert_not_called()


class TestFatalNotifyOnNotionFailure:
    def test_sends_slack_when_notion_check_fails(self, config_with_webhook):
        notify_mock = AsyncMock(return_value=True)
        notion_instance = MagicMock()
        notion_instance.check_access = MagicMock(return_value=False)

        with patch("medium_notion.cli.load_config", return_value=config_with_webhook), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
             patch("medium_notion.cli.NotionClient", return_value=notion_instance), \
             patch("medium_notion.slack.notify_fatal_error", notify_mock):
            exit_code = _run_bookmark()

        assert exit_code == 1
        notify_mock.assert_called_once()
        assert notify_mock.call_args.kwargs["error_type"] == "NotionAuthError"


class TestFatalNotifyOnRuntimeError:
    def test_sends_slack_when_browser_raises_runtime_error(self, config_with_webhook):
        notify_mock = AsyncMock(return_value=True)
        notion_instance = MagicMock()
        notion_instance.check_access = MagicMock(return_value=True)
        notion_instance.list_existing_urls = MagicMock(return_value=set())
        notion_instance.list_existing_topics = MagicMock(return_value=[])

        browser_instance = MagicMock()
        browser_instance.initialize = AsyncMock(
            side_effect=RuntimeError("Medium セッションが見つかりません")
        )
        browser_instance.close = AsyncMock()

        with patch("medium_notion.cli.load_config", return_value=config_with_webhook), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
             patch("medium_notion.cli.NotionClient", return_value=notion_instance), \
             patch("medium_notion.cli.BrowserClient", return_value=browser_instance), \
             patch("medium_notion.cli._load_article_index", return_value=[]), \
             patch("medium_notion.slack.notify_fatal_error", notify_mock):
            exit_code = _run_bookmark()

        assert exit_code == 1
        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        assert "セッション" in kwargs["message"] or "Session" in kwargs["message"]


class TestNoFatalNotifyOnEmptyList:
    """空振り（リストが空）では通知を送らない"""

    def test_no_slack_on_empty_reading_list(self, config_with_webhook):
        notify_mock = AsyncMock(return_value=True)
        notion_instance = MagicMock()
        notion_instance.check_access = MagicMock(return_value=True)
        notion_instance.list_existing_urls = MagicMock(return_value=set())
        notion_instance.list_existing_topics = MagicMock(return_value=[])

        browser_instance = MagicMock()
        browser_instance.initialize = AsyncMock()
        browser_instance.fetch_reading_list = AsyncMock(return_value=[])
        browser_instance.close = AsyncMock()

        success_notify = AsyncMock(return_value=True)

        with patch("medium_notion.cli.load_config", return_value=config_with_webhook), \
             patch("medium_notion.cli.Config.check_claude_code", return_value=True), \
             patch("medium_notion.cli.NotionClient", return_value=notion_instance), \
             patch("medium_notion.cli.BrowserClient", return_value=browser_instance), \
             patch("medium_notion.cli._load_article_index", return_value=[]), \
             patch("medium_notion.slack.notify_fatal_error", notify_mock), \
             patch("medium_notion.slack.notify_slack", success_notify):
            exit_code = _run_bookmark()

        # 空振りは正常終了（exit code 0 / None）
        assert exit_code in (None, 0)
        # 致命的エラー通知も成功通知も送らない
        notify_mock.assert_not_called()
        success_notify.assert_not_called()
