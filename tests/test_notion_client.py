"""Notion クライアントのテスト"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.notion_client import NotionClient


@pytest.fixture
def notion_client(mock_config):
    """Notion SDK をモックした NotionClient"""
    with patch("medium_notion.notion_client.NotionSDKClient") as mock_sdk:
        mock_sdk.return_value = MagicMock()
        client = NotionClient(mock_config)
        yield client


class TestNotionClient:
    def test_build_properties(self, notion_client, sample_translation):
        """Notion プロパティが正しく構築されること"""
        props = notion_client._build_properties(sample_translation, score=8)

        # タイトル
        assert props["名前"]["title"][0]["text"]["content"] == sample_translation.japanese_title

        # URL
        assert props["URL"]["url"] == sample_translation.original.url

        # read date
        assert props["read date"]["date"]["start"] == date.today().isoformat()

        # Categories
        assert len(props["Categories"]["multi_select"]) == 2
        assert props["Categories"]["multi_select"][0]["name"] == "AI"

        # Score
        assert props["Score"]["number"] == 8

    def test_build_properties_no_score(self, notion_client, sample_translation):
        """Score なしでプロパティ構築"""
        props = notion_client._build_properties(sample_translation, score=None)

        assert "Score" not in props

    def test_build_content_blocks(self, notion_client, sample_translation):
        """本文ブロックが正しく生成されること"""
        blocks = notion_client._build_content_blocks(sample_translation)

        # 最低限のブロックが生成されていること
        assert len(blocks) > 0

        # 最後に元記事リンクがあること
        last_para = blocks[-1]
        assert last_para["type"] == "paragraph"
        assert "元記事" in last_para["paragraph"]["rich_text"][0]["text"]["content"]

    def test_split_text_short(self, notion_client):
        """短いテキストは分割されないこと"""
        result = notion_client._split_text("短いテキスト", 2000)
        assert len(result) == 1
        assert result[0] == "短いテキスト"

    def test_split_text_long(self, notion_client):
        """長いテキストが分割されること"""
        long_text = "あ" * 5000
        result = notion_client._split_text(long_text, 2000)
        assert len(result) > 1
        assert all(len(chunk) <= 2000 for chunk in result)

    def test_heading_block(self, notion_client):
        """見出しブロックの生成"""
        block = notion_client._heading_block("テスト見出し", level=2)
        assert block["type"] == "heading_2"
        assert block["heading_2"]["rich_text"][0]["text"]["content"] == "テスト見出し"
