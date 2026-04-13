"""致命的エラーによるバッチ早期中断のテスト"""

import pytest
from medium_notion.cli import _is_fatal_error


class TestIsFatalError:
    """環境起因の致命的エラーを判定するテスト"""

    def test_ssl_certificate_error(self):
        error = (
            "Claude Code CLI エラー (exit code: 1):\n"
            "  stdout: API Error: Unable to connect to API: "
            "Self-signed certificate detected.\n"
            "Check your proxy or corporate SSL certificates"
        )
        assert _is_fatal_error(error) is True

    def test_unable_to_connect_api(self):
        error = (
            "Claude Code CLI エラー (exit code: 1):\n"
            "  stdout: API Error: Unable to connect to API"
        )
        assert _is_fatal_error(error) is True

    def test_api_key_invalid(self):
        error = (
            "Claude Code CLI エラー (exit code: 1):\n"
            "  stderr: invalid x-api-key"
        )
        assert _is_fatal_error(error) is True

    def test_authentication_error(self):
        error = (
            "Claude Code CLI エラー (exit code: 1):\n"
            "  stderr: 401 Unauthorized"
        )
        assert _is_fatal_error(error) is True

    def test_cli_not_found(self):
        error = (
            "Claude Code CLI が見つかりません。\n"
            "  → npm install -g @anthropic-ai/claude-code でインストールしてください"
        )
        assert _is_fatal_error(error) is True

    def test_cli_timeout_is_not_fatal(self):
        """タイムアウトは記事固有の問題なので致命的ではない"""
        error = "Claude Code CLI がタイムアウトしました（10分）"
        assert _is_fatal_error(error) is False

    def test_http_error_is_not_fatal(self):
        """HTTP エラーは記事固有の問題なので致命的ではない"""
        error = "ページの取得に失敗しました (HTTP 502)。URLが正しいか確認してください。"
        assert _is_fatal_error(error) is False

    def test_notion_api_error_is_not_fatal(self):
        """Notion API エラーは記事固有の可能性があるので致命的ではない"""
        error = "Notion ページの作成に失敗しました: validation_error"
        assert _is_fatal_error(error) is False

    def test_empty_response_is_not_fatal(self):
        """空レスポンスは一時的な問題の可能性"""
        error = "Claude Code CLI から空の応答が返されました。"
        assert _is_fatal_error(error) is False
