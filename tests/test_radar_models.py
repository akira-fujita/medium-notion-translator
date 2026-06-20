from medium_notion.radar.models import FeedItem, ScoredItem, Digest


def test_feeditem_key_prefers_guid():
    item = FeedItem(url="https://x/a", title="T", source="S", layer="L", guid="g-1")
    assert item.key == "g-1"


def test_feeditem_key_falls_back_to_url():
    item = FeedItem(url="https://x/a", title="T", source="S", layer="L")
    assert item.key == "https://x/a"


def test_digest_is_empty():
    assert Digest(highlights=[], others=[]).is_empty is True
    fi = FeedItem(url="u", title="t", source="s", layer="l")
    assert Digest(highlights=[ScoredItem(item=fi)], others=[]).is_empty is False


def test_scoreditem_holds_optional_deepdive():
    from medium_notion.radar.models import DeepDive
    fi = FeedItem(url="u", title="t", source="s", layer="l")
    s = ScoredItem(item=fi)
    assert s.deepdive is None  # デフォルトは未深掘り
    dd = DeepDive(translation="訳", overview="概要", key_points="点", critique="批判", fulltext_ok=True)
    s.deepdive = dd
    assert s.deepdive.translation == "訳"
    assert s.deepdive.fulltext_ok is True
