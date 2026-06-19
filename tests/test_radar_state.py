from medium_notion.radar.models import FeedItem
from medium_notion.radar.state import SeenStore


def _item(url, guid=""):
    return FeedItem(url=url, title="t", source="s", layer="l", guid=guid)


def test_first_run_all_new(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    items = [_item("https://x/a"), _item("https://x/b")]
    assert store.filter_new(items) == items


def test_marked_items_are_filtered_out(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path)
    a, b = _item("https://x/a"), _item("https://x/b")
    store.mark_seen([a])

    store2 = SeenStore(path)  # 再ロード（永続化を検証）
    assert store2.filter_new([a, b]) == [b]


def test_dedup_within_batch(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    dup = [_item("https://x/a"), _item("https://x/a")]
    assert len(store.filter_new(dup)) == 1
