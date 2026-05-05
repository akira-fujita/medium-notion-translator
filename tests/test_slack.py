"""Slack 通知のテスト"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from medium_notion.slack import notify_fatal_error


def _run(coro):
    return asyncio.run(coro)


class TestNotifyFatalError:
    """致命的エラー時の Slack 通知"""

    def test_returns_false_when_webhook_url_empty(self):
        result = _run(
            notify_fatal_error(
                webhook_url="",
                error_type="SessionExpired",
                message="Medium セッションが切れています",
            )
        )
        assert result is False

    def test_posts_payload_to_webhook(self):
        captured: dict = {}

        async def fake_post(url, json, timeout):
            captured["url"] = url
            captured["payload"] = json
            response = MagicMock()
            response.raise_for_status = MagicMock()
            return response

        with patch("medium_notion.slack.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = fake_post
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = _run(
                notify_fatal_error(
                    webhook_url="https://hooks.slack.com/services/TEST",
                    error_type="SessionExpired",
                    message="Medium セッションが切れています",
                )
            )

            assert result is True
            assert captured["url"] == "https://hooks.slack.com/services/TEST"
            payload_str = str(captured["payload"])
            assert "SessionExpired" in payload_str
            assert "Medium セッションが切れています" in payload_str

    def test_returns_false_on_http_error(self):
        async def fake_post(url, json, timeout):
            raise Exception("network error")

        with patch("medium_notion.slack.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = fake_post
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = _run(
                notify_fatal_error(
                    webhook_url="https://hooks.slack.com/services/TEST",
                    error_type="NotionAuthError",
                    message="API キーが無効です",
                )
            )

            assert result is False

    def test_payload_includes_alert_marker(self):
        """致命的エラー通知は通常の成功通知と区別できるマーカーを含む"""
        captured: dict = {}

        async def fake_post(url, json, timeout):
            captured["payload"] = json
            response = MagicMock()
            response.raise_for_status = MagicMock()
            return response

        with patch("medium_notion.slack.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = fake_post
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            _run(
                notify_fatal_error(
                    webhook_url="https://hooks.slack.com/services/TEST",
                    error_type="SessionExpired",
                    message="Cookie 期限切れ",
                )
            )

        text = str(captured["payload"])
        assert any(
            marker in text for marker in [":rotating_light:", "致命的", "Fatal"]
        )
