"""設定読み込みのテスト"""

import os
from unittest.mock import patch

from medium_notion.config import load_config


class TestLoadConfig:
    def test_env_file_overrides_shell_env(self, tmp_path):
        """`.env` の値がシェル環境変数より優先されること"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NOTION_API_KEY=ntn_from_dotenv_file\n"
            "NOTION_DATABASE_ID=dbid_from_dotenv_file\n"
        )

        with patch.dict(os.environ, {"NOTION_API_KEY": "ntn_from_shell"}):
            config = load_config(str(env_file))

        assert config.notion_api_key == "ntn_from_dotenv_file"

    def test_visual_html_is_on_by_default_and_can_be_disabled(self, tmp_path):
        """視覚版 HTML は既定で作る。VISUAL_HTML=false で止められる"""
        env_file = tmp_path / ".env"
        env_file.write_text("NOTION_API_KEY=ntn_x\nNOTION_DATABASE_ID=dbid\n")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VISUAL_HTML", None)
            assert load_config(str(env_file)).visual_html is True

        env_file.write_text("NOTION_API_KEY=ntn_x\nNOTION_DATABASE_ID=dbid\nVISUAL_HTML=false\n")
        with patch.dict(os.environ, {}, clear=False):
            assert load_config(str(env_file)).visual_html is False
