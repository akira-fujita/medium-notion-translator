from medium_notion.config import load_config


def test_radar_env_loaded(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "ntn_real_key")
    monkeypatch.setenv("NOTION_DATABASE_ID", "a" * 32)
    monkeypatch.setenv("RADAR_NOTION_DATABASE_ID", "b" * 32)
    monkeypatch.setenv("RADAR_SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    cfg = load_config()
    assert cfg.radar_notion_database_id == "b" * 32
    assert cfg.radar_slack_webhook_url == "https://hooks.slack.test/x"
    assert cfg.radar_notion_database_id_formatted == (
        f"{'b'*8}-{'b'*4}-{'b'*4}-{'b'*4}-{'b'*12}"
    )
