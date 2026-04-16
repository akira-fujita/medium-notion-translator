"""データモデルのテスト"""

from medium_notion.models import MediumArticle, TranslationResult


class TestTranslationResult:
    def test_topics_default_empty(self):
        """topics のデフォルトが空リストであること"""
        article = MediumArticle(
            url="https://medium.com/@test/article",
            title="Test Article",
            content="Test content",
        )
        result = TranslationResult(
            original=article,
            japanese_title="テスト記事",
            japanese_content="テスト本文",
        )
        assert result.topics == []

    def test_topics_with_values(self):
        """topics に値を設定できること"""
        article = MediumArticle(
            url="https://medium.com/@test/article",
            title="Test Article",
            content="Test content",
        )
        result = TranslationResult(
            original=article,
            japanese_title="テスト記事",
            japanese_content="テスト本文",
            topics=["Kubernetes", "モジューラーモノリス", "運用負荷"],
        )
        assert result.topics == ["Kubernetes", "モジューラーモノリス", "運用負荷"]
        assert len(result.topics) == 3
