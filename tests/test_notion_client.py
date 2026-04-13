"""Notion クライアントのテスト"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.notion_client import NotionClient, _text_obj


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

        # 最後に元記事リンク（bookmark）があること
        last_block = blocks[-1]
        assert last_block["type"] == "bookmark"
        assert last_block["bookmark"]["url"] == sample_translation.original.url

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


class TestTextObjUrlValidation:
    """_text_obj の URL バリデーションテスト"""

    def test_valid_https_url(self):
        """https URL はリンクとして設定されること"""
        obj = _text_obj("text", link="https://example.com")
        assert obj["text"]["link"] == {"url": "https://example.com"}

    def test_valid_http_url(self):
        """http URL はリンクとして設定されること"""
        obj = _text_obj("text", link="http://example.com")
        assert obj["text"]["link"] == {"url": "http://example.com"}

    def test_fragment_only_url(self):
        """#fragment のみの URL はリンクにならないこと"""
        obj = _text_obj("text", link="#section")
        assert "link" not in obj["text"]

    def test_relative_path_url(self):
        """相対パス URL はリンクにならないこと"""
        obj = _text_obj("text", link="/path/to/page")
        assert "link" not in obj["text"]

    def test_empty_url(self):
        """空文字 URL はリンクにならないこと"""
        obj = _text_obj("text", link="")
        assert "link" not in obj["text"]

    def test_whitespace_url(self):
        """空白のみの URL はリンクにならないこと"""
        obj = _text_obj("text", link="  ")
        assert "link" not in obj["text"]

    def test_none_url(self):
        """None はリンクにならないこと"""
        obj = _text_obj("text", link=None)
        assert "link" not in obj["text"]

    def test_javascript_url(self):
        """javascript: URL はリンクにならないこと"""
        obj = _text_obj("text", link="javascript:alert(1)")
        assert "link" not in obj["text"]


class TestNotionAPIDataSource:
    """Notion API data_sources 移行のテスト"""

    def test_check_access_uses_data_sources(self, notion_client):
        """check_access が data_sources.retrieve を使うこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.retrieve.return_value = {
            "title": [{"plain_text": "Medium DB"}],
        }
        result = notion_client.check_access()

        assert result is True
        mock_sdk.data_sources.retrieve.assert_called_once_with(
            data_source_id=notion_client.database_id,
        )

    def test_list_articles_uses_data_sources(self, notion_client):
        """list_articles が data_sources.query を使うこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [{
                "properties": {
                    "名前": {"title": [{"plain_text": "テスト記事"}]},
                    "Categories": {"multi_select": [{"name": "AI"}]},
                },
            }],
            "has_more": False,
            "next_cursor": None,
        }
        articles = notion_client.list_articles()

        assert len(articles) == 1
        assert articles[0]["title"] == "テスト記事"
        mock_sdk.data_sources.query.assert_called_once()
        call_kwargs = mock_sdk.data_sources.query.call_args[1]
        assert "data_source_id" in call_kwargs

    def test_list_existing_urls_uses_data_sources_sdk(self, notion_client):
        """list_existing_urls が SDK の data_sources.query を使うこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {"properties": {"URL": {"url": "https://medium.com/article-1"}}},
                {"properties": {"URL": {"url": "https://medium.com/article-2"}}},
                {"properties": {"URL": {"url": None}}},
            ],
            "has_more": False,
            "next_cursor": None,
        }
        urls = notion_client.list_existing_urls()

        assert urls == {
            "https://medium.com/article-1",
            "https://medium.com/article-2",
        }
        mock_sdk.data_sources.query.assert_called_once()

    def test_create_page_uses_data_source_parent(
        self, notion_client, sample_translation
    ):
        """create_page が data_source_id を parent に使うこと"""
        mock_sdk = notion_client.client
        mock_sdk.pages.create.return_value = {
            "id": "test-page-id",
            "url": "https://notion.so/test",
        }
        notion_client.create_page(sample_translation, score=7)

        call_kwargs = mock_sdk.pages.create.call_args[1]
        assert "data_source_id" in call_kwargs["parent"]
        assert call_kwargs["parent"]["data_source_id"] == notion_client.database_id
