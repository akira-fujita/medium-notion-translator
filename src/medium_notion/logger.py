"""ロガー設定"""

import sys

from loguru import logger


def setup_logger(level: str = "INFO") -> None:
    """アプリケーションロガーを設定"""
    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
            "{message}"
        ),
        level=level,
        colorize=True,
    )


def step(message: str) -> None:
    """処理ステップをログ出力"""
    logger.info(f"▶ {message}")


def success(message: str) -> None:
    """成功メッセージをログ出力"""
    logger.success(f"✓ {message}")


def warn(message: str) -> None:
    """警告メッセージをログ出力"""
    logger.warning(f"⚠ {message}")


def error(message: str) -> None:
    """エラーメッセージをログ出力"""
    logger.error(f"✗ {message}")
