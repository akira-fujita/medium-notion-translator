from unittest.mock import patch

from medium_notion.config import Config
from medium_notion.radar.models import FeedItem
from medium_notion.radar.deepdive import DeepDiver


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def _item():
    return FeedItem(url="https://x/a", title="AI org change", source="a16z",
                    layer="VC", summary_raw="短い概要")


def test_analyze_with_fulltext_translates_and_analyzes():
    diver = DeepDiver(_cfg())
    analysis = ('```json\n{"overview":"概要文","key_points":"押さえる点",'
                '"critique":"批判的視点"}\n```')
    with patch.object(diver, "_call_claude", side_effect=["日本語の全文訳", analysis]):
        dd = diver.analyze(_item(), fulltext="This is the full article body. " * 50)

    assert dd.fulltext_ok is True
    assert dd.translation == "日本語の全文訳"
    assert dd.overview == "概要文"
    assert dd.key_points == "押さえる点"
    assert dd.critique == "批判的視点"


def test_analyze_without_fulltext_skips_translation():
    diver = DeepDiver(_cfg())
    analysis = '{"overview":"概要","key_points":"点","critique":"批判"}'
    with patch.object(diver, "_call_claude", return_value=analysis) as m:
        dd = diver.analyze(_item(), fulltext=None)

    assert dd.fulltext_ok is False
    assert dd.translation == ""        # 翻訳は省略
    assert dd.overview == "概要"
    assert m.call_count == 1           # 分析のみ（翻訳しない）


def test_analyze_returns_empty_on_claude_failure():
    diver = DeepDiver(_cfg())
    with patch.object(diver, "_call_claude", side_effect=RuntimeError("boom")):
        dd = diver.analyze(_item(), fulltext="body " * 200)
    # 落ちずに空の DeepDive（行・Slack は維持される）
    assert dd.translation == ""
    assert dd.overview == ""
