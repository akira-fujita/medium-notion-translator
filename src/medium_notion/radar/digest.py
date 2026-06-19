"""Digest 振り分けと Slack レンダラ"""

from .models import ScoredItem, Digest


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


def _display_title(s: ScoredItem) -> str:
    return s.jp_title or s.item.title


def render_slack_text(digest: Digest) -> str:
    """ダイジェストを Slack mrkdwn 文字列に整形する"""
    lines: list[str] = ["*🛰 今朝の Tech Radar*", ""]

    if digest.highlights:
        lines.append(f"*■ 今日の刺さる {len(digest.highlights)}本*")
        for s in digest.highlights:
            title = _display_title(s)
            lines.append(f"• [{s.item.layer}] <{s.item.url}|{title}> (score {s.score})")
            if s.summary:
                lines.append(f"    {s.summary}")
            if s.why:
                lines.append(f"    💡 {s.why}")
    else:
        lines.append("_今日の閾値超えはありませんでした_")

    if digest.others:
        lines.append("")
        others_links = " · ".join(
            f"<{s.item.url}|{_display_title(s)}>" for s in digest.others
        )
        lines.append(f"📂 *その他 {len(digest.others)}件*: {others_links}")

    return "\n".join(lines)


def render_slack_payload(digest: Digest) -> dict:
    """Slack Incoming Webhook 用 payload を返す"""
    text = render_slack_text(digest)
    return {
        "text": f"🛰 Tech Radar: 刺さる{len(digest.highlights)}本 / その他{len(digest.others)}件",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ],
    }
