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


def test_parse_captures_full_content_when_present():
    """RSS の content:encoded があれば content_full に取り込む"""
    raw = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><title>B</title>
      <item>
        <title>Post</title>
        <link>https://example.com/p/1</link>
        <description>短い概要</description>
        <content:encoded>これは記事の完全な本文テキストです。</content:encoded>
      </item>
      </channel>
    </rss>"""
    spec = FeedSpec(name="B", url="https://example.com/rss", layer="VC")
    items = RssSource(spec)._parse(raw)
    assert items[0].content_full == "これは記事の完全な本文テキストです。"


def test_fetch_uses_timed_http_get(monkeypatch):
    """fetch はタイムアウト付き HTTP 取得を使う（feedparser.parse(url) の無限ハング回避）"""
    import medium_notion.radar.sources.rss as rss_mod

    captured = {}

    class FakeResp:
        content = FIXTURE.read_bytes()

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return FakeResp()

    monkeypatch.setattr(rss_mod.httpx, "get", fake_get)

    spec = FeedSpec(name="Sample Blog", url="https://example.com/rss", layer="一次情報")
    items = RssSource(spec).fetch()

    assert captured["url"] == "https://example.com/rss"
    assert captured["timeout"] is not None  # タイムアウトが必ず指定される
    assert len(items) == 2
