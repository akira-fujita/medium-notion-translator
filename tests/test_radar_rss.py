from pathlib import Path

from medium_notion.radar.config import FeedSpec
from medium_notion.radar.sources.rss import RssSource

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_extracts_feed_items():
    spec = FeedSpec(name="Sample Blog", url="https://example.com/rss", layer="一次情報")
    source = RssSource(spec)
    items = source._parse(FIXTURE.read_text(encoding="utf-8"))

    assert len(items) == 2
    first = items[0]
    assert first.title == "First Post"
    assert first.url == "https://example.com/posts/first"
    assert first.source == "Sample Blog"
    assert first.layer == "一次情報"
    assert "first post summary" in first.summary_raw.lower()
    assert items[1].guid == "guid-second-123"


def test_parse_respects_limit():
    spec = FeedSpec(name="Sample Blog", url="https://example.com/rss", layer="一次情報")
    source = RssSource(spec)
    items = source._parse(FIXTURE.read_text(encoding="utf-8"), limit=1)
    assert len(items) == 1
