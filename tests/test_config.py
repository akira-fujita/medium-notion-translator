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
