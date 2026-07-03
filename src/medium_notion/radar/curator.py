"""Curator — Claude Code CLI で新着記事を関心プロファイルに照らして採点"""

import json
import re
import subprocess
import textwrap

from ..config import Config
from .config import RadarConfig
from .errors import ClaudeCliNotFound
from .models import FeedItem, ScoredItem
from .. import logger as log

SCORING_PROMPT = textwrap.dedent("""\
    あなたは Engineering Manager（CTO・事業責任者へ移行中）の情報キュレーターです。
    以下の「関心プロファイル」に照らして、各記事を 0〜10 で採点してください。
    技術そのものより「構造変化・組織・事業インパクト」を重視します。
    JSON 配列のみを出力し、他のテキストは含めないでください。

    出力形式（記事ごとに 1 要素）:
    [
      {{
        "url": "記事のURL（入力と完全一致させる）",
        "score": 0から10の整数,
        "jp_title": "日本語タイトル",
        "summary": "日本語1〜2行の要約",
        "why": "この関心プロファイルにどう刺さるか（刺さらないなら空文字）"
      }}
    ]

    ## 関心プロファイル
    {profile}

    ## 採点対象の記事
    {articles}
""")


class Curator:
    """新着記事を Claude で採点する"""

    def __init__(self, config: Config):
        self.config = config

    def score(self, items: list[FeedItem], radar_cfg: RadarConfig) -> list[ScoredItem]:
        if not items:
            return []

        prompt = self._build_prompt(items, radar_cfg.profile)
        try:
            raw = self._call_claude(prompt)
            scored_raw = self._parse_json_list(raw)
        except ClaudeCliNotFound:
            raise  # 致命的な設定エラー → 握りつぶさず run を失敗させる
        except Exception as e:
            log.warn(f"採点に失敗（素の新着を流します）: {e}")
            scored_raw = []

        return self._merge(items, scored_raw)

    def _build_prompt(self, items: list[FeedItem], profile: list[str]) -> str:
        profile_text = "\n".join(f"- {p}" for p in profile) or "- （未設定）"
        articles_text = "\n".join(
            f"{i + 1}. [{it.source} / {it.layer}] {it.title}\n"
            f"   URL: {it.url}\n"
            f"   概要: {it.summary_raw[:500]}"
            for i, it in enumerate(items)
        )
        return SCORING_PROMPT.format(profile=profile_text, articles=articles_text)

    @staticmethod
    def _coerce_score(value) -> int:
        """Claude が返す score を 0〜10 の整数に正規化する。

        '9/10' や 'high' のような不正値でも例外を投げず 0 にフォールバックし、
        範囲外は 0〜10 にクランプする（採点失敗で run 全体を落とさないため）。
        """
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(10, n))

    def _merge(self, items: list[FeedItem], scored_raw: list[dict]) -> list[ScoredItem]:
        by_url = {d.get("url"): d for d in scored_raw if isinstance(d, dict)}
        result: list[ScoredItem] = []
        for it in items:
            d = by_url.get(it.url, {})
            result.append(
                ScoredItem(
                    item=it,
                    score=self._coerce_score(d.get("score", 0)),
                    jp_title=d.get("jp_title", "") or "",
                    summary=d.get("summary", "") or "",
                    why=d.get("why", "") or "",
                )
            )
        return result

    def _parse_json_list(self, text: str) -> list[dict]:
        m = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1).strip())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
        start = text.find("[")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[start : i + 1])
                            if isinstance(data, list):
                                return data
                        except json.JSONDecodeError:
                            pass
                        break
        return []

    def _call_claude(self, prompt: str) -> str:
        cmd = ["claude", "-p", "--output-format", "text"]
        log.step(f"Claude で採点中 (プロンプト {len(prompt)} 文字)...")
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=600
            )
        except FileNotFoundError:
            raise ClaudeCliNotFound(
                "Claude Code CLI が見つかりません。\n"
                "  → npm install -g @anthropic-ai/claude-code でインストールしてください"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code CLI がタイムアウトしました（10分）")

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "出力なし").strip()[:500]
            raise RuntimeError(f"Claude Code CLI エラー (exit {proc.returncode}): {detail}")
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("Claude Code CLI から空の応答が返されました")
        return output
