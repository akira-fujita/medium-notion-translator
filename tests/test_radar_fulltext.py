from medium_notion.radar.models import FeedItem
from medium_notion.radar.fulltext import fetch_fulltext


def _item(url="https://x/a", content_full=""):
    return FeedItem(url=url, title="t", source="s", layer="l",
                    summary_raw="短い概要", content_full=content_full)


def test_uses_rss_full_content_when_long_enough():
    """RSS に十分長い全文があれば trafilatura を呼ばずそれを使う"""
    long_body = "これは記事の全文です。" * 50  # 十分長い
    item = _item(content_full=long_body)
    assert fetch_fulltext(item) == long_body


def test_extracts_via_trafilatura_when_rss_short(monkeypatch):
    """RSS 全文が無い/短い → URL から trafilatura 抽出"""
    extracted = "抽出された本文。" * 80  # MIN_FULLTEXT_LEN(500) 超
    import trafilatura
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: "<html>...</html>")
    monkeypatch.setattr(trafilatura, "extract", lambda html: extracted)
    assert fetch_fulltext(_item(content_full="")) == extracted


def test_returns_none_when_extraction_fails(monkeypatch):
    """trafilatura が取れなければ None（フォールバック）"""
    import trafilatura
    monkeypatch.setattr(trafilatura, "fetch_url", lambda url: None)
    assert fetch_fulltext(_item(content_full="")) is None
