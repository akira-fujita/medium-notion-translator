from medium_notion.radar.models import FeedItem, ScoredItem
from medium_notion.radar.digest import build_digest, render_slack_text, render_slack_payload


def _scored(url, score, layer="VC", jp="JP", summary="S", why="W"):
    fi = FeedItem(url=url, title="EN", source="src", layer=layer)
    return ScoredItem(item=fi, score=score, jp_title=jp, summary=summary, why=why)


def test_build_digest_splits_by_threshold_sorted():
    scored = [_scored("u1", 5), _scored("u2", 9), _scored("u3", 7)]
    d = build_digest(scored, threshold=7, max_highlights=8)
    assert [s.item.url for s in d.highlights] == ["u2", "u3"]
    assert [s.item.url for s in d.others] == ["u1"]


def test_build_digest_respects_max_highlights():
    scored = [_scored(f"u{i}", 8) for i in range(5)]
    d = build_digest(scored, threshold=7, max_highlights=3)
    assert len(d.highlights) == 3
    assert len(d.others) == 2


def test_render_slack_text_contains_highlight_and_others():
    d = build_digest([_scored("u1", 9, jp="刺さる記事"), _scored("u2", 2, jp="その他記事")],
                     threshold=7, max_highlights=8)
    text = render_slack_text(d)
    assert "刺さる記事" in text
    assert "u1" in text
    assert "その他" in text


def test_render_slack_payload_shape():
    d = build_digest([_scored("u1", 9)], threshold=7, max_highlights=8)
    payload = render_slack_payload(d)
    assert "text" in payload and "blocks" in payload
    assert isinstance(payload["blocks"], list)
