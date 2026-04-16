"""Notion クライアントのテスト"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.notion_client import NotionClient, _text_obj
from medium_notion.models import TranslationResult


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

        # create date
        assert props["create date"]["date"]["start"] == date.today().isoformat()

        # Categories
        assert len(props["Categories"]["multi_select"]) == 2
        assert props["Categories"]["multi_select"][0]["name"] == "AI"

        # Score
        assert props["Score"]["number"] == 8

    def test_build_properties_with_topics(self, notion_client, sample_translation):
        """Topics が multi_select として構築されること"""
        notion_client._has_topics_property = True
        props = notion_client._build_properties(sample_translation, score=8)

        assert "Topics" in props
        topics_ms = props["Topics"]["multi_select"]
        assert len(topics_ms) == 4
        assert topics_ms[0]["name"] == "Claude Code"
        assert topics_ms[1]["name"] == "プロンプトキャッシュ"

    def test_build_properties_empty_topics(self, notion_client, sample_article):
        """topics が空の場合は Topics プロパティが含まれないこと"""
        result = TranslationResult(
            original=sample_article,
            japanese_title="テスト",
            japanese_content="テスト",
            topics=[],
        )
        props = notion_client._build_properties(result, score=None)

        assert "Topics" not in props

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


class TestTopicsPropertyDetection:
    """Topics プロパティの有無検出テスト"""

    def test_check_access_detects_topics_property(self, notion_client):
        """check_access が Topics プロパティの存在を検出すること"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.retrieve.return_value = {
            "title": [{"plain_text": "Medium DB"}],
            "properties": {
                "名前": {"type": "title"},
                "Topics": {"type": "multi_select"},
            },
        }
        notion_client.check_access()

        assert notion_client._has_topics_property is True

    def test_check_access_detects_missing_topics_property(self, notion_client):
        """check_access が Topics プロパティ未設定を検出すること"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.retrieve.return_value = {
            "title": [{"plain_text": "Medium DB"}],
            "properties": {
                "名前": {"type": "title"},
            },
        }
        notion_client.check_access()

        assert notion_client._has_topics_property is False

    def test_build_properties_skips_topics_when_not_in_schema(self, notion_client, sample_translation):
        """DB に Topics がない場合は properties に含めないこと"""
        notion_client._has_topics_property = False
        props = notion_client._build_properties(sample_translation, score=8)

        assert "Topics" not in props

    def test_build_properties_includes_topics_when_in_schema(self, notion_client, sample_translation):
        """DB に Topics がある場合は properties に含めること"""
        notion_client._has_topics_property = True
        props = notion_client._build_properties(sample_translation, score=8)

        assert "Topics" in props
        assert len(props["Topics"]["multi_select"]) == 4


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


class TestListExistingTopics:
    def test_list_existing_topics_returns_unique_sorted(self, notion_client):
        """DB 内の Topics を重複排除してソート済みで返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {
                    "properties": {
                        "Topics": {
                            "multi_select": [
                                {"name": "Kubernetes"},
                                {"name": "モジューラーモノリス"},
                            ]
                        }
                    }
                },
                {
                    "properties": {
                        "Topics": {
                            "multi_select": [
                                {"name": "Kubernetes"},
                                {"name": "運用負荷"},
                            ]
                        }
                    }
                },
            ],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == sorted(["Kubernetes", "モジューラーモノリス", "運用負荷"])
        mock_sdk.data_sources.query.assert_called_once()

    def test_list_existing_topics_empty_db(self, notion_client):
        """DB が空の場合に空リストを返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == []

    def test_list_existing_topics_no_topics_property(self, notion_client):
        """Topics プロパティがないページでもエラーにならないこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {"properties": {"名前": {"title": [{"plain_text": "記事"}]}}},
            ],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == []


class TestBackfillMethods:
    """バックフィル用メソッドのテスト"""

    def test_list_pages_without_topics(self, notion_client):
        """Topics 未設定のページ一覧を返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "properties": {
                        "名前": {"title": [{"plain_text": "記事A"}]},
                        "URL": {"url": "https://medium.com/a"},
                        "Topics": {"multi_select": []},
                    },
                },
                {
                    "id": "page-2",
                    "properties": {
                        "名前": {"title": [{"plain_text": "記事B"}]},
                        "URL": {"url": "https://medium.com/b"},
                        "Topics": {"multi_select": [{"name": "AI"}]},
                    },
                },
                {
                    "id": "page-3",
                    "properties": {
                        "名前": {"title": [{"plain_text": "記事C"}]},
                        "URL": {"url": "https://medium.com/c"},
                    },
                },
            ],
            "has_more": False,
            "next_cursor": None,
        }
        pages = notion_client.list_pages_without_topics()

        assert len(pages) == 2
        assert pages[0]["page_id"] == "page-1"
        assert pages[0]["title"] == "記事A"
        assert pages[1]["page_id"] == "page-3"

    def test_get_page_text(self, notion_client):
        """ページの blocks からテキストを抽出すること"""
        mock_sdk = notion_client.client
        mock_sdk.blocks.children.list.return_value = {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"plain_text": "最初の段落です。"}]
                    },
                },
                {
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"plain_text": "見出し"}]
                    },
                },
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"plain_text": "2番目の段落。"}]
                    },
                },
                {
                    "type": "divider",
                    "divider": {},
                },
            ],
            "has_more": False,
        }
        text = notion_client.get_page_text("page-1")

        assert "最初の段落です。" in text
        assert "見出し" in text
        assert "2番目の段落。" in text

    def test_get_page_text_empty(self, notion_client):
        """空のページで空文字列を返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.blocks.children.list.return_value = {
            "results": [],
            "has_more": False,
        }
        text = notion_client.get_page_text("page-1")

        assert text == ""

    def test_update_page_topics(self, notion_client):
        """ページの Topics を更新すること"""
        mock_sdk = notion_client.client
        mock_sdk.pages.update.return_value = {"id": "page-1"}

        notion_client.update_page_topics(
            "page-1", ["Kubernetes", "モジューラーモノリス"]
        )

        mock_sdk.pages.update.assert_called_once_with(
            page_id="page-1",
            properties={
                "Topics": {
                    "multi_select": [
                        {"name": "Kubernetes"},
                        {"name": "モジューラーモノリス"},
                    ]
                }
            },
        )
