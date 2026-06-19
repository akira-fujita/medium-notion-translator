from medium_notion.radar.models import FeedItem, ScoredItem, Digest
from medium_notion.slack import post_digest


def _digest():
    fi = FeedItem(url="https://x/a", title="t", source="s", layer="VC")
    return Digest(highlights=[ScoredItem(item=fi, score=9, jp_title="題")], others=[])


async def test_post_digest_no_webhook_returns_false():
    assert await post_digest("", _digest()) is False


async def test_post_digest_empty_digest_returns_false():
    assert await post_digest("https://hooks.slack.test/x", Digest()) is False


async def test_post_digest_posts_payload(monkeypatch):
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, timeout):
            sent["url"] = url
            sent["json"] = json
            return FakeResp()

    monkeypatch.setattr("medium_notion.slack.httpx.AsyncClient", lambda: FakeClient())
    ok = await post_digest("https://hooks.slack.test/x", _digest())
    assert ok is True
    assert sent["url"] == "https://hooks.slack.test/x"
    assert "blocks" in sent["json"]
