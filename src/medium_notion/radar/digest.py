"""Digest 振り分けと Slack レンダラ"""

from .models import ScoredItem, Digest

# Slack の section text は約 3000 文字上限。その他リンクの列挙はこの件数で打ち切る。
MAX_OTHERS_LINKS = 20
# Slack section text のハード上限（3000）。安全マージンを取ってこの値で分割する。
SLACK_SECTION_LIMIT = 2900
# Slack の 1 メッセージあたりブロック数上限。
MAX_SLACK_BLOCKS = 50


def build_digest(
    scored: list[ScoredItem], threshold: int, max_highlights: int
) -> Digest:
    """score 降順に並べ、threshold 以上を highlights（上限あり）、残りを others へ"""
    ordered = sorted(scored, key=lambda s: s.score, reverse=True)
    above = [s for s in ordered if s.score >= threshold]
    below = [s for s in ordered if s.score < threshold]

    highlights = above[:max_highlights]
    overflow = above[max_highlights:]
    others = overflow + below
    return Digest(highlights=highlights, others=others)


def _escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn の制御文字をエスケープする（リンク・表示の破損防止）。

    Slack の仕様に従い & < > のみをエスケープする（順序重要: & を最初に）。
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _display_title(s: ScoredItem) -> str:
    return _escape_mrkdwn(s.jp_title or s.item.title)


def render_slack_text(digest: Digest) -> str:
    """ダイジェストを Slack mrkdwn 文字列に整形する"""
    lines: list[str] = ["*🛰 今朝の Tech Radar*", ""]

    if digest.highlights:
        lines.append(f"*■ 今日の刺さる {len(digest.highlights)}本*")
        for s in digest.highlights:
            title = _display_title(s)
            lines.append(f"• [{s.item.layer}] <{s.item.url}|{title}> (score {s.score})")
            if s.summary:
                lines.append(f"    {_escape_mrkdwn(s.summary)}")
            if s.why:
                lines.append(f"    💡 {_escape_mrkdwn(s.why)}")
            if s.notion_url:
                lines.append(f"    📝 <{s.notion_url}|Notion で開く>")
    else:
        lines.append("_今日の閾値超えはありませんでした_")

    if digest.others:
        lines.append("")
        shown = digest.others[:MAX_OTHERS_LINKS]
        others_links = " · ".join(
            f"<{s.item.url}|{_display_title(s)}>" for s in shown
        )
        hidden = len(digest.others) - len(shown)
        if hidden > 0:
            others_links += f" … ほか {hidden}件"
        lines.append(f"📂 *その他 {len(digest.others)}件*: {others_links}")

    return "\n".join(lines)


def _chunk_for_slack(text: str, limit: int = SLACK_SECTION_LIMIT) -> list[str]:
    """text を行境界で limit 文字以下のチャンクに分割する。

    Slack の section text は 3000 文字上限で、超えると payload 全体が
    invalid_blocks で拒否される。行単位で詰めて複数 section に分ける。
    1 行が limit を超える場合はその行を硬分割する。
    """
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # 1 行が単独で limit 超 → 硬分割
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def render_slack_payload(digest: Digest) -> dict:
    """Slack Incoming Webhook 用 payload を返す。

    section text の 3000 文字上限を超えないよう、本文を複数の section ブロックに
    分割する（Slack は 1 メッセージ最大 50 ブロック）。
    """
    text = render_slack_text(digest)
    chunks = _chunk_for_slack(text)[:MAX_SLACK_BLOCKS]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks
    ]
    return {
        "text": f"🛰 Tech Radar: 刺さる{len(digest.highlights)}本 / その他{len(digest.others)}件",
        "blocks": blocks,
    }
