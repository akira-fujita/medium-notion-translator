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
              notion_writer=notion_writer, slack_post=slack_post, no_deepdive=True)

    notion_writer.append_item.assert_called_once()
    slack_post.assert_called_once()
    assert seen.filter_new([item]) == []


def test_run_radar_sets_notion_url_on_items(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )
    scorer = MagicMock()
    scored = ScoredItem(item=item, score=9, jp_title="題")
    scorer.score.return_value = [scored]

    notion_writer = MagicMock()
    notion_writer.append_item.return_value = "https://notion.so/page-1"

    digest = run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=notion_writer, slack_post=lambda u, d: True,
                       no_deepdive=True)

    # 書き込んだページ URL が ScoredItem に反映される（Slack の Notion リンク用）
    assert digest.highlights[0].notion_url == "https://notion.so/page-1"


def test_run_radar_applies_default_feed_limit_when_none(tmp_path, monkeypatch):
    """--limit 未指定でも、フィード当たりにデフォルト上限を適用する（バックログ全件処理を防ぐ）"""
    from medium_notion.radar.pipeline import DEFAULT_FEED_LIMIT
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    captured = {}

    def fake_fetch(self, limit=None):
        captured["limit"] = limit
        return []

    monkeypatch.setattr("medium_notion.radar.pipeline.RssSource.fetch", fake_fetch)
    run_radar(_cfg(), radar_cfg, seen, dry_run=True, limit=None,
              when=date(2026, 6, 19), scorer=MagicMock())
    assert captured["limit"] == DEFAULT_FEED_LIMIT


def test_run_radar_deepdives_highlights_only_capped(tmp_path, monkeypatch):
    from medium_notion.radar.models import DeepDive
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")],
                            threshold=7, deepdive_max=2)
    seen = SeenStore(str(tmp_path / "seen.json"))
    items = [FeedItem(url=f"https://x/{i}", title="t", source="S", layer="VC")
             for i in range(5)]
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: items
    )
    scorer = MagicMock()
    scored = [ScoredItem(item=it, score=9 if i < 3 else 2) for i, it in enumerate(items)]
    scorer.score.return_value = scored

    diver = MagicMock()
    diver.analyze.return_value = DeepDive(overview="o", fulltext_ok=False)

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer,
              notion_writer=MagicMock(), slack_post=lambda u, d: True,
              diver=diver, fulltext_fn=lambda it: None)

    # 刺さる3件のうち deepdive_max=2 までしか深掘りしない
    assert diver.analyze.call_count == 2


def test_run_radar_marks_seen_only_successfully_written(tmp_path, monkeypatch):
    """Notion 書き込みに失敗した記事は既読にしない（次回リトライできるよう取りこぼし防止）"""
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    a = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    b = FeedItem(url="https://x/b", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [a, b]
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=a, score=2), ScoredItem(item=b, score=2)]

    # a は成功（URL 返す）、b は失敗（None）
    notion_writer = MagicMock()
    notion_writer.append_item.side_effect = (
        lambda s, when: "https://notion.so/a" if s.item.url == "https://x/a" else None
    )

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer, notion_writer=notion_writer,
              slack_post=lambda u, d: True, no_deepdive=True)

    # a は既読、b は未読（リトライ対象として残る）
    remaining = seen.filter_new([a, b])
    assert remaining == [b]


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
                       notion_writer=MagicMock(), slack_post=lambda u, d: True,
                       no_deepdive=True)
    assert d_sent.slack_status == "sent"

    # 送信失敗 → "failed"
    seen2 = SeenStore(str(tmp_path / "s2.json"))
    d_failed = run_radar(cfg, radar_cfg, seen2, dry_run=False, limit=None,
                         when=date(2026, 6, 19), scorer=scorer,
                         notion_writer=MagicMock(), slack_post=lambda u, d: False,
                         no_deepdive=True)
    assert d_failed.slack_status == "failed"

    # webhook 未設定 → "skipped"
    cfg_no_hook = _cfg()
    cfg_no_hook.slack_webhook_url = None
    seen3 = SeenStore(str(tmp_path / "s3.json"))
    d_skip = run_radar(cfg_no_hook, radar_cfg, seen3, dry_run=False, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=MagicMock(), slack_post=lambda u, d: True,
                       no_deepdive=True)
    assert d_skip.slack_status == "skipped"


def test_run_radar_skips_write_and_seen_when_deepdive_failed(tmp_path, monkeypatch):
    """深掘りが失敗した記事は Notion 書き込みも既読化もスキップ（次回再挑戦）"""
    from medium_notion.radar.models import DeepDive
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")],
                            threshold=7, deepdive_max=2)
    seen = SeenStore(str(tmp_path / "seen.json"))
    a = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [a]
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=a, score=9)]
    diver = MagicMock()
    diver.analyze.return_value = DeepDive(failed=True)
    notion_writer = MagicMock()

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer, notion_writer=notion_writer,
              slack_post=lambda u, d: True, diver=diver, fulltext_fn=lambda it: "body")

    notion_writer.append_item.assert_not_called()   # 書き込みスキップ
    assert seen.filter_new([a]) == [a]              # 未読のまま残る


def test_run_radar_circuit_breaker_stops_deepdive_after_failure(tmp_path, monkeypatch):
    """深掘りが1件失敗したら以降の深掘りを打ち切り、残りも未書き込み・未読で持ち越す"""
    from medium_notion.radar.models import DeepDive
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")],
                            threshold=7, deepdive_max=3)
    seen = SeenStore(str(tmp_path / "seen.json"))
    items = [FeedItem(url=f"https://x/{i}", title="t", source="S", layer="VC")
             for i in range(3)]
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: items
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=it, score=9) for it in items]
    diver = MagicMock()
    diver.analyze.return_value = DeepDive(failed=True)
    notion_writer = MagicMock()

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer, notion_writer=notion_writer,
              slack_post=lambda u, d: True, diver=diver, fulltext_fn=lambda it: "body")

    assert diver.analyze.call_count == 1            # 1件目失敗で打ち切り
    notion_writer.append_item.assert_not_called()   # 3件とも未書き込み
    assert seen.filter_new(items) == items          # 3件とも未読


def test_run_radar_fatal_cli_error_aborts_without_marking_seen(tmp_path, monkeypatch):
    """深掘りが致命エラー（CLI不在）を送出したら run を失敗させ、何も既読化しない"""
    import pytest
    from medium_notion.radar.deepdive import ClaudeCliNotFound
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")],
                            threshold=7, deepdive_max=2)
    seen = SeenStore(str(tmp_path / "seen.json"))
    a = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [a]
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=a, score=9)]
    diver = MagicMock()
    diver.analyze.side_effect = ClaudeCliNotFound("no cli")

    with pytest.raises(ClaudeCliNotFound):
        run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
                  when=date(2026, 6, 19), scorer=scorer, notion_writer=MagicMock(),
                  slack_post=lambda u, d: True, diver=diver, fulltext_fn=lambda it: "body")

    assert seen.filter_new([a]) == [a]   # 何も既読化されていない


def test_run_radar_writes_normally_when_no_fulltext(tmp_path, monkeypatch):
    """本文が取れないだけ（failed=False, fulltext_ok=False）は通常通り書き込む（過剰スキップ防止）"""
    from medium_notion.radar.models import DeepDive
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")],
                            threshold=7, deepdive_max=2)
    seen = SeenStore(str(tmp_path / "seen.json"))
    a = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [a]
    )
    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=a, score=9)]
    diver = MagicMock()
    diver.analyze.return_value = DeepDive(overview="o", fulltext_ok=False, failed=False)
    notion_writer = MagicMock()
    notion_writer.append_item.return_value = "https://notion.so/a"

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer, notion_writer=notion_writer,
              slack_post=lambda u, d: True, diver=diver, fulltext_fn=lambda it: None)

    notion_writer.append_item.assert_called_once()   # 通常通り書き込み
    assert seen.filter_new([a]) == []                # 既読化される
