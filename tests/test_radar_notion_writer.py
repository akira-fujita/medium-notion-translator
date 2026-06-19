from datetime import date

from medium_notion.config import Config
from medium_notion.radar.models import FeedItem, ScoredItem
from medium_notion.radar.notion_writer import RadarNotionWriter


def _cfg():
    return Config(
        notion_api_key="ntn_real_key",
        notion_database_id="a" * 32,
        radar_notion_database_id="b" * 32,
    )


def test_build_properties_maps_all_fields():
    fi = FeedItem(url="https://x/a", title="EN Title", source="a16z", layer="VC")
    scored = ScoredItem(item=fi, score=8, jp_title="日本語題", summary="要約", why="刺さる理由")
    writer = RadarNotionWriter(_cfg())
    props = writer._build_properties(scored, date(2026, 6, 19))

    assert props["名前"]["title"][0]["text"]["content"] == "日本語題"
    assert props["URL"]["url"] == "https://x/a"
    assert props["Date"]["date"]["start"] == "2026-06-19"
    assert props["Source"]["select"]["name"] == "a16z"
    assert props["Layer"]["select"]["name"] == "VC"
    assert props["Summary"]["rich_text"][0]["text"]["content"] == "要約"
    assert props["Why"]["rich_text"][0]["text"]["content"] == "刺さる理由"
    assert props["Score"]["number"] == 8


def test_build_properties_falls_back_to_original_title():
    fi = FeedItem(url="https://x/a", title="EN Only", source="s", layer="L")
    scored = ScoredItem(item=fi, score=0)
    writer = RadarNotionWriter(_cfg())
    props = writer._build_properties(scored, date(2026, 6, 19))
    assert props["名前"]["title"][0]["text"]["content"] == "EN Only"
