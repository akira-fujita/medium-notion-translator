from medium_notion.config import load_config


def test_radar_env_loaded(tmp_path, monkeypatch):
    # 実 .env を読み込まないよう空の env ファイルを渡して分離する
    # （load_config は override=True で dotenv を読むため、実 .env があると
    #  monkeypatch の値が上書きされてしまう）
    empty_env = tmp_path / ".env"
    empty_env.write_text("")
    monkeypatch.setenv("NOTION_API_KEY", "ntn_real_key")
    monkeypatch.setenv("NOTION_DATABASE_ID", "a" * 32)
    monkeypatch.setenv("RADAR_NOTION_DATABASE_ID", "b" * 32)
    monkeypatch.setenv("RADAR_SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    cfg = load_config(str(empty_env))
    assert cfg.radar_notion_database_id == "b" * 32
    assert cfg.radar_slack_webhook_url == "https://hooks.slack.test/x"
    assert cfg.radar_notion_database_id_formatted == (
        f"{'b'*8}-{'b'*4}-{'b'*4}-{'b'*4}-{'b'*12}"
    )
