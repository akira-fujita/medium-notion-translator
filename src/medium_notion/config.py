"""設定管理 — .env ファイルの読み込みとバリデーション"""

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


class Config(BaseModel):
    """アプリケーション設定"""

    notion_api_key: str
    notion_database_id: str
    headless: bool = False
    log_level: str = "INFO"
    claude_model: str = "sonnet"
    session_path: Path = Path("medium-session.json")
    index_path: Path = Path("article-index.json")

    @field_validator("notion_api_key")
    @classmethod
    def validate_notion_key(cls, v: str) -> str:
        if not v or v.startswith("ntn_your"):
            raise ValueError(
                "Notion API キーが設定されていません。\n"
                "  → .env ファイルに NOTION_API_KEY を設定してください\n"
                "  → 取得: https://www.notion.so/profile/integrations"
            )
        return v

    @field_validator("notion_database_id")
    @classmethod
    def validate_database_id(cls, v: str) -> str:
        if not v or v.startswith("your_"):
            raise ValueError(
                "Notion Database ID が設定されていません。\n"
                "  → .env ファイルに NOTION_DATABASE_ID を設定してください"
            )
        # ハイフンを除去（UUID形式の正規化）
        return v.replace("-", "")

    @property
    def notion_database_id_formatted(self) -> str:
        """Notion API 用にハイフン付き UUID 形式に変換"""
        d = self.notion_database_id
        if len(d) == 32:
            return f"{d[:8]}-{d[8:12]}-{d[12:16]}-{d[16:20]}-{d[20:]}"
        return d

    @classmethod
    def check_claude_code(cls) -> bool:
        """Claude Code CLI が利用可能か確認"""
        return shutil.which("claude") is not None


def load_config(env_path: str | None = None) -> Config:
    """設定を .env から読み込んで返す"""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    return Config(
        notion_api_key=os.getenv("NOTION_API_KEY", ""),
        notion_database_id=os.getenv("NOTION_DATABASE_ID", ""),
        headless=os.getenv("HEADLESS", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        claude_model=os.getenv("CLAUDE_MODEL", "sonnet"),
    )
