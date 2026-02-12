"""翻訳モジュールのテスト"""

import json
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.translator import TranslationService


class TestTranslationService:
    def test_parse_translation_json(self, mock_config, sample_article):
        """JSON 形式の翻訳結果をパースできること"""
        service = TranslationService(mock_config)

        raw_output = json.dumps(
            {
                "title": "テスト記事",
                "content": "翻訳された本文です。",
                "categories": ["AI", "Development"],
                "summary": "テスト要約",
            }
        )

        result = service._parse_translation(raw_output, sample_article)

        assert result.japanese_title == "テスト記事"
        assert result.japanese_content == "翻訳された本文です。"
        assert result.categories == ["AI", "Development"]
        assert result.summary == "テスト要約"

    def test_parse_translation_json_block(self, mock_config, sample_article):
        """```json ブロックを含む出力からパースできること"""
        service = TranslationService(mock_config)

        raw_output = (
            "以下は翻訳結果です:\n\n"
            "```json\n"
            '{"title": "テスト", "content": "本文", "categories": [], "summary": ""}\n'
            "```"
        )

        result = service._parse_translation(raw_output, sample_article)

        assert result.japanese_title == "テスト"
        assert result.japanese_content == "本文"

    def test_parse_translation_fallback(self, mock_config, sample_article):
        """JSON パース失敗時にプレーンテキストとして扱うこと"""
        service = TranslationService(mock_config)

        raw_output = "これは翻訳されたテキストです。JSONではありません。"
        result = service._parse_translation(raw_output, sample_article)

        assert result.japanese_title == sample_article.title
        assert result.japanese_content == raw_output

    def test_extract_json_from_text(self, mock_config):
        """テキストから JSON を抽出できること"""
        service = TranslationService(mock_config)

        # ケース 1: ```json ブロック
        text1 = '前のテキスト\n```json\n{"key": "value"}\n```\n後のテキスト'
        assert json.loads(service._extract_json(text1)) == {"key": "value"}

        # ケース 2: 直接の JSON
        text2 = '{"title": "test"}'
        assert json.loads(service._extract_json(text2)) == {"title": "test"}

        # ケース 3: JSON なし
        text3 = "普通のテキスト"
        assert service._extract_json(text3) is None

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
