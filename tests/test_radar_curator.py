from unittest.mock import patch

from medium_notion.config import Config
from medium_notion.radar.config import RadarConfig
from medium_notion.radar.models import FeedItem
from medium_notion.radar.curator import Curator


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def _items():
    return [
        FeedItem(url="https://x/a", title="AI org change", source="a16z", layer="VC"),
        FeedItem(url="https://x/b", title="Some rust internals", source="Stripe", layer="一次情報"),
    ]


def test_score_merges_claude_output():
    radar_cfg = RadarConfig(profile=["AI 時代の EM"], threshold=7)
    fake = (
        '```json\n[{"url":"https://x/a","score":9,"jp_title":"AIで組織が変わる",'
        '"summary":"要約A","why":"EM に直撃"},'
        '{"url":"https://x/b","score":3,"jp_title":"Rust 内部","summary":"要約B","why":""}]\n```'
    )
    curator = Curator(_cfg())
    with patch.object(curator, "_call_claude", return_value=fake):
        scored = curator.score(_items(), radar_cfg)

    by_url = {s.item.url: s for s in scored}
    assert by_url["https://x/a"].score == 9
    assert by_url["https://x/a"].jp_title == "AIで組織が変わる"
    assert by_url["https://x/a"].why == "EM に直撃"
    assert by_url["https://x/b"].score == 3


def test_score_falls_back_when_claude_fails():
    radar_cfg = RadarConfig(profile=["x"], threshold=7)
    curator = Curator(_cfg())
    with patch.object(curator, "_call_claude", side_effect=RuntimeError("boom")):
        scored = curator.score(_items(), radar_cfg)

    assert len(scored) == 2
    assert all(s.score == 0 for s in scored)
    assert {s.item.url for s in scored} == {"https://x/a", "https://x/b"}


def test_score_empty_input_returns_empty():
    curator = Curator(_cfg())
    assert curator.score([], RadarConfig()) == []


def test_score_tolerates_malformed_score_values():
    """Claude が score に '9/10' や 'high' を返しても落ちず、その項目は 0 にフォールバック"""
    radar_cfg = RadarConfig(profile=["x"], threshold=7)
    fake = (
        '[{"url":"https://x/a","score":"9/10","jp_title":"A","summary":"s","why":""},'
        '{"url":"https://x/b","score":"high","jp_title":"B","summary":"s","why":""}]'
    )
    curator = Curator(_cfg())
    with patch.object(curator, "_call_claude", return_value=fake):
        scored = curator.score(_items(), radar_cfg)

    by_url = {s.item.url: s for s in scored}
    assert by_url["https://x/a"].score == 0
    assert by_url["https://x/b"].score == 0
    # 落ちずに全件返る
    assert len(scored) == 2
