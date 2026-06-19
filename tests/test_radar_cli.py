from unittest.mock import patch

from click.testing import CliRunner

from medium_notion.cli import cli
from medium_notion.config import Config
from medium_notion.radar.config import RadarConfig
from medium_notion.radar.models import FeedItem, ScoredItem, Digest


def test_radar_dry_run_prints_digest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)
    radar_cfg = RadarConfig(threshold=7)
    fi = FeedItem(url="https://x/a", title="EN", source="a16z", layer="VC")
    digest = Digest(highlights=[ScoredItem(item=fi, score=9, jp_title="刺さる記事")], others=[])

    with patch("medium_notion.cli.load_config", return_value=cfg), \
         patch("medium_notion.cli.load_radar_config", return_value=radar_cfg), \
         patch("medium_notion.cli.run_radar", return_value=digest) as mock_run:
        result = CliRunner().invoke(cli, ["radar", "--dry-run"])

    assert result.exit_code == 0
    assert "刺さる記事" in result.output
    # dry_run フラグが pipeline に伝わる
    assert mock_run.call_args.kwargs["dry_run"] is True


def test_radar_missing_feeds_yml_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)

    with patch("medium_notion.cli.load_config", return_value=cfg), \
         patch("medium_notion.cli.load_radar_config",
               side_effect=FileNotFoundError("feeds.yml")):
        result = CliRunner().invoke(cli, ["radar", "--dry-run"])

    assert result.exit_code == 1
    assert "feeds.yml" in result.output


def test_radar_reports_slack_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)
    radar_cfg = RadarConfig(threshold=7)
    fi = FeedItem(url="https://x/a", title="EN", source="a16z", layer="VC")
    digest = Digest(highlights=[ScoredItem(item=fi, score=9, jp_title="題")], others=[])
    digest.slack_status = "failed"

    with patch("medium_notion.cli.load_config", return_value=cfg), \
         patch("medium_notion.cli.load_radar_config", return_value=radar_cfg), \
         patch("medium_notion.cli.run_radar", return_value=digest):
        result = CliRunner().invoke(cli, ["radar"])

    assert result.exit_code == 0
    # 「投稿完了」と嘘をつかず、失敗が分かる表示になっている
    assert "投稿完了" not in result.output
    assert "失敗" in result.output
