"""翻訳モジュールのテスト"""

import json
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.translator import TranslationService


class TestParseJson:
    """_parse_json のテスト"""

    def test_parse_json_from_raw(self, mock_config):
        """直接の JSON 文字列をパースできること"""
        service = TranslationService(mock_config)

        text = json.dumps({"key": "value"})
        result = service._parse_json(text)

        assert result == {"key": "value"}

    def test_parse_json_from_code_block(self, mock_config):
        """```json ブロックを含むテキストからパースできること"""
        service = TranslationService(mock_config)

        text = '前のテキスト\n```json\n{"key": "value"}\n```\n後のテキスト'
        result = service._parse_json(text)

        assert result == {"key": "value"}

    def test_parse_json_returns_none_for_plain_text(self, mock_config):
        """JSON を含まないテキストで None を返すこと"""
        service = TranslationService(mock_config)

        result = service._parse_json("普通のテキスト")

        assert result is None

    def test_parse_json_nested_braces(self, mock_config):
        """ネストされた JSON をパースできること"""
        service = TranslationService(mock_config)

        data = {"summary": {"overview": "テスト", "learnings": "学び"}}
        text = f"結果: {json.dumps(data, ensure_ascii=False)}"
        result = service._parse_json(text)

        assert result == data


class TestExtractMetadata:
    def test_extract_metadata_with_topics(self, mock_config, sample_article):
        """_extract_metadata が topics を含む JSON を正しくパースすること"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト記事",
            "categories": ["AI"],
            "topics": ["Kubernetes", "モジューラーモノリス", "運用負荷"],
            "summary": {
                "overview": "概要テスト",
                "learnings": "学びテスト",
                "use_cases": "活用テスト",
                "connections": "",
            },
        }, ensure_ascii=False)

        with patch.object(service, "_call_claude", return_value=raw_json):
            title, categories, summary, topics = service._extract_metadata(
                sample_article, [], []
            )

        assert title == "テスト記事"
        assert categories == ["AI"]
        assert topics == ["Kubernetes", "モジューラーモノリス", "運用負荷"]
        assert "概要テスト" in summary

    def test_extract_metadata_without_topics_field(self, mock_config, sample_article):
        """topics フィールドがない JSON でもエラーにならないこと"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト記事",
            "categories": ["AI"],
            "summary": {
                "overview": "概要テスト",
                "learnings": "",
                "use_cases": "",
                "connections": "",
            },
        }, ensure_ascii=False)

        with patch.object(service, "_call_claude", return_value=raw_json):
            title, categories, summary, topics = service._extract_metadata(
                sample_article, [], []
            )

        assert topics == []

    def test_extract_metadata_passes_existing_topics_to_prompt(self, mock_config, sample_article):
        """既存 Topics がプロンプトに含まれること"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト",
            "categories": [],
            "topics": ["Kubernetes"],
            "summary": {"overview": "", "learnings": "", "use_cases": "", "connections": ""},
        }, ensure_ascii=False)

        existing_topics = ["Kubernetes", "モジューラーモノリス"]

        with patch.object(service, "_call_claude", return_value=raw_json) as mock_claude:
            service._extract_metadata(sample_article, [], existing_topics)
            prompt_text = mock_claude.call_args[0][0]
            assert "Kubernetes" in prompt_text
            assert "モジューラーモノリス" in prompt_text

    def test_extract_metadata_limits_existing_topics(self, mock_config, sample_article):
        """既存 Topics が上限 200 件に切り詰められること"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト",
            "categories": [],
            "topics": [],
            "summary": {"overview": "", "learnings": "", "use_cases": "", "connections": ""},
        }, ensure_ascii=False)

        # 300 個の Topics を生成
        existing_topics = [f"topic_{i}" for i in range(300)]

        with patch.object(service, "_call_claude", return_value=raw_json) as mock_claude:
            service._extract_metadata(sample_article, [], existing_topics)
            prompt_text = mock_claude.call_args[0][0]
            # 先頭の topic_0 は含まれる
            assert "topic_0" in prompt_text
            # 末尾の topic_299 は含まれない（200 件で切り詰め）
            assert "topic_299" not in prompt_text

    def test_extract_metadata_failure_returns_empty_topics(self, mock_config, sample_article):
        """メタデータ抽出失敗時に空の topics を返すこと"""
        service = TranslationService(mock_config)

        with patch.object(service, "_call_claude", side_effect=RuntimeError("fail")):
            title, categories, summary, topics = service._extract_metadata(
                sample_article, [], []
            )

        assert title is None
        assert categories == []
        assert summary is None
        assert topics == []


class TestCallClaude:
    """_call_claude のテスト"""

    @patch("medium_notion.translator.subprocess.run")
    def test_call_claude_success(self, mock_run, mock_config):
        """Claude Code CLI の正常呼び出し"""
        service = TranslationService(mock_config)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "翻訳"}',
            stderr="",
        )

        result = service._call_claude("test prompt")
        assert result == '{"title": "翻訳"}'

    @patch("medium_notion.translator.subprocess.run")
    def test_call_claude_not_found(self, mock_run, mock_config):
        """Claude Code CLI が見つからない場合"""
        service = TranslationService(mock_config)
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(RuntimeError, match="Claude Code CLI が見つかりません"):
            service._call_claude("test prompt")
