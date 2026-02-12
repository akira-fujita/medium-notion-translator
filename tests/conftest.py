"""テスト用のフィクスチャ"""

import pytest
from medium_notion.config import Config
from medium_notion.models import MediumArticle, TranslationResult


@pytest.fixture
def mock_config():
    return Config(
        notion_api_key="ntn_test_key_12345",
        notion_database_id="2a354f2bd9f080c6ad76f4c0caa22b65",
        headless=True,
        log_level="DEBUG",
        claude_model="sonnet",
    )


@pytest.fixture
def sample_article():
    return MediumArticle(
        url="https://medium.com/@test/sample-article-123",
        title="I Cut My Claude Code API Costs by 40%",
        content=(
            "In this article, I'll share how I reduced my API costs "
            "significantly using a simple tool.\n\n"
            "The key insight was to use prompt caching effectively. "
            "By implementing a local cache layer, I was able to avoid "
            "redundant API calls.\n\n"
            "Here's the approach I took:\n\n"
            "First, I analyzed my usage patterns. Most of my API calls "
            "were repetitive, sending similar prompts for code review tasks."
        ),
        author="Test Author",
        tags=["AI", "Development"],
    )


@pytest.fixture
def sample_translation(sample_article):
    return TranslationResult(
        original=sample_article,
        japanese_title="Claude Code の API コストを 40% 削減した方法",
        japanese_content=(
            "この記事では、シンプルなツールを使って API コストを大幅に削減した方法を紹介します。\n\n"
            "重要な発見は、プロンプトキャッシュを効果的に使用することでした。"
        ),
        categories=["AI", "Development"],
        summary="Claude Code のコスト削減手法。プロンプトキャッシュの活用で40%のコスト削減を実現。",
    )
