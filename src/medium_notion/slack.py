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


async def notify_fatal_error(
    webhook_url: str,
    error_type: str,
    message: str,
) -> bool:
    """致命的エラー（実行継続不能）を Slack に通知する

    日次の自動実行（launchd 等）で誰も画面を見ていない状況で、
    セッション切れ・認証失敗・依存ツール不在などが起きたときに、
    気づいて手動対応するためのアラート。

    Args:
        webhook_url: Slack Incoming Webhook の URL
        error_type: エラー種別（例: "SessionExpired", "NotionAuthError"）
        message: 詳細メッセージ

    Returns:
        送信成功なら True
    """
    if not webhook_url:
        return False

    short_message = message if len(message) <= 500 else message[:500] + "..."

    text = (
        f":rotating_light: *Medium → Notion: 致命的エラー*\n"
        f"*種別:* `{error_type}`\n"
        f"```\n{short_message}\n```\n"
        f"_自動処理は中断されました。手動で対応してください。_"
    )

    payload = {
        "text": f":rotating_light: Medium → Notion 致命的エラー: {error_type}",
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
        log.success("Slack 致命的エラー通知を送信しました")
        return True
    except Exception as e:
        log.warn(f"Slack 致命的エラー通知の送信に失敗: {e}")
        return False
