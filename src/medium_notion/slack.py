"""Slack 通知 — Incoming Webhook によるサマリー送信"""

import httpx

from . import logger as log


async def notify_slack(
    webhook_url: str,
    successes: list[tuple[str, str, str]],  # (medium_url, japanese_title, notion_url)
    failures: list[tuple[str, str]],         # (medium_url, error)
) -> bool:
    """翻訳結果を Slack にまとめて通知する

    Args:
        webhook_url: Slack Incoming Webhook の URL
        successes: 成功した記事のリスト (Medium URL, 日本語タイトル, Notion URL)
        failures: 失敗した記事のリスト (Medium URL, エラーメッセージ)

    Returns:
        送信成功なら True
    """
    if not webhook_url:
        return False

    # メッセージ構築
    total = len(successes) + len(failures)
    lines = [f"*Medium → Notion 翻訳完了*  ({total}件処理)"]
    lines.append("")

    if successes:
        lines.append(f":white_check_mark: 成功: {len(successes)}件")
    if failures:
        lines.append(f":x: 失敗: {len(failures)}件")

    lines.append("")

    # 成功した記事のリンク一覧
    for medium_url, title, notion_url in successes:
        lines.append(f":link: <{notion_url}|{title}>")

    # 失敗した記事
    if failures:
        lines.append("")
        for medium_url, error in failures:
            short_url = medium_url[:60] + "..." if len(medium_url) > 60 else medium_url
            lines.append(f":warning: {short_url}")

    text = "\n".join(lines)

    payload = {
        "text": f"Medium → Notion: {len(successes)}件翻訳完了",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                },
            },
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
        log.success("Slack 通知を送信しました")
        return True
    except Exception as e:
        log.warn(f"Slack 通知の送信に失敗: {e}")
        return False
