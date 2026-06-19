from datetime import date
from unittest.mock import MagicMock

from medium_notion.config import Config
from medium_notion.radar.config import RadarConfig, FeedSpec
from medium_notion.radar.models import FeedItem, ScoredItem
from medium_notion.radar.state import SeenStore
from medium_notion.radar.pipeline import run_radar


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def test_run_radar_empty_when_no_new_items(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))

    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )
    seen.mark_seen([item])

    scorer = MagicMock()
    digest = run_radar(_cfg(), radar_cfg, seen, dry_run=True, limit=None,
                       when=date(2026, 6, 19), scorer=scorer)
    assert digest.is_empty
    scorer.score.assert_not_called()


def test_run_radar_dry_run_does_not_write(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )

    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=item, score=9, jp_title="題")]
    notion_writer = MagicMock()
    slack_post = MagicMock()

    digest = run_radar(_cfg(), radar_cfg, seen, dry_run=True, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=notion_writer, slack_post=slack_post)

    assert len(digest.highlights) == 1
    notion_writer.append_item.assert_not_called()
    slack_post.assert_not_called()
    assert seen.filter_new([item]) == [item]


def test_run_radar_writes_and_marks_seen(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )

    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=item, score=9, jp_title="題")]
    notion_writer = MagicMock()
    slack_post = MagicMock()

    cfg = _cfg()
    cfg.slack_webhook_url = "https://hooks.slack.test/x"
    run_radar(cfg, radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer,
              notion_writer=notion_writer, slack_post=slack_post)

    notion_writer.append_item.assert_called_once()
    slack_post.assert_called_once()
    assert seen.filter_new([item]) == []


def test_run_radar_slack_status_reflects_post_result(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=item, score=9, jp_title="題")]

    cfg = _cfg()
    cfg.slack_webhook_url = "https://hooks.slack.test/x"

    # 送信成功 → "sent"
    seen1 = SeenStore(str(tmp_path / "s1.json"))
    d_sent = run_radar(cfg, radar_cfg, seen1, dry_run=False, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=MagicMock(), slack_post=lambda u, d: True)
    assert d_sent.slack_status == "sent"

    # 送信失敗 → "failed"
    seen2 = SeenStore(str(tmp_path / "s2.json"))
    d_failed = run_radar(cfg, radar_cfg, seen2, dry_run=False, limit=None,
                         when=date(2026, 6, 19), scorer=scorer,
                         notion_writer=MagicMock(), slack_post=lambda u, d: False)
    assert d_failed.slack_status == "failed"

    # webhook 未設定 → "skipped"
    cfg_no_hook = _cfg()
    cfg_no_hook.slack_webhook_url = None
    seen3 = SeenStore(str(tmp_path / "s3.json"))
    d_skip = run_radar(cfg_no_hook, radar_cfg, seen3, dry_run=False, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=MagicMock(), slack_post=lambda u, d: True)
    assert d_skip.slack_status == "skipped"
