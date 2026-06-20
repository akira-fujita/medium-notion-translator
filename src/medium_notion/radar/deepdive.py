"""DeepDiver — 刺さる記事の全文翻訳＋構造化分析（Claude Code CLI）

translator.py の 2 ステップ思想を踏襲:
  Step 1: 本文を日本語全文翻訳（プレーンな markdown）
  Step 2: 要約・立場ポイント・批判的視点を JSON で抽出
本文が取れなかった場合は翻訳を省き、RSS 概要から分析のみ生成する。
"""

import json
import re
import subprocess
import textwrap

from ..config import Config
from .models import FeedItem, DeepDive
from .. import logger as log

MAX_CHUNK_SIZE = 15000

TRANSLATE_PROMPT = textwrap.dedent("""\
    あなたは技術記事の翻訳者です。以下の英語記事を自然な日本語に翻訳してください。
    技術用語は英語/カタカナを適宜維持し、コードブロックや見出し等のマークダウン構造を保ちます。
    翻訳のみを出力し、前置きや説明は不要です。

    ## タイトル
    {title}

    ## 本文
    {content}
""")

ANALYZE_PROMPT = textwrap.dedent("""\
    あなたは Engineering Manager（CTO・事業責任者へ移行中）を補佐するアナリストです。
    以下の記事を分析し、JSON のみで返してください（他のテキストは含めない）。

    出力形式:
    {{
      "overview": "何についての記事で結論は何か。2〜3文で簡潔に",
      "key_points": "EM→経営側の立場として押さえるべきポイントを2〜4点。組織・事業・意思決定の観点で",
      "critique": "批判的視点を2〜3点。鵜呑みにせず、反論・限界・前提の弱さ・適用できない文脈を指摘する"
    }}

    ## 記事タイトル
    {title}

    ## 記事本文
    {content}
""")


class DeepDiver:
    """刺さる記事を深掘りする"""

    def __init__(self, config: Config):
        self.config = config

    def analyze(self, item: FeedItem, fulltext: str | None) -> DeepDive:
        """記事を深掘りして DeepDive を返す。Claude 失敗時は空の DeepDive。"""
        try:
            if fulltext:
                translation = self._translate(item.title, fulltext)
                analysis = self._analyze(item.title, fulltext)
                return DeepDive(
                    translation=translation,
                    overview=analysis.get("overview", ""),
                    key_points=analysis.get("key_points", ""),
                    critique=analysis.get("critique", ""),
                    fulltext_ok=True,
                )
            # 本文なし → 概要から分析のみ
            analysis = self._analyze(item.title, item.summary_raw)
            return DeepDive(
                translation="",
                overview=analysis.get("overview", ""),
                key_points=analysis.get("key_points", ""),
                critique=analysis.get("critique", ""),
                fulltext_ok=False,
            )
        except Exception as e:
            log.warn(f"深掘りに失敗（行・Slack は維持）: {item.url}: {e}")
            return DeepDive(fulltext_ok=bool(fulltext))

    def _translate(self, title: str, content: str) -> str:
        if len(content) > MAX_CHUNK_SIZE:
            return self._translate_chunked(title, content)
        return self._call_claude(TRANSLATE_PROMPT.format(title=title, content=content))

    def _translate_chunked(self, title: str, content: str) -> str:
        paragraphs = content.split("\n\n")
        chunks: list[str] = []
        current: list[str] = []
        size = 0
        for para in paragraphs:
            if size + len(para) > MAX_CHUNK_SIZE and current:
                chunks.append("\n\n".join(current))
                current = []
                size = 0
            current.append(para)
            size += len(para)
        if current:
            chunks.append("\n\n".join(current))
        parts = [
            self._call_claude(TRANSLATE_PROMPT.format(title=title, content=c))
            for c in chunks
        ]
        return "\n\n".join(parts)

    def _analyze(self, title: str, content: str) -> dict:
        raw = self._call_claude(ANALYZE_PROMPT.format(title=title, content=content[:8000]))
        return self._parse_json(raw) or {}

    def _parse_json(self, text: str) -> dict | None:
        m = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        start = text.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            pass
                        break
        return None

    def _call_claude(self, prompt: str) -> str:
        cmd = ["claude", "-p", "--output-format", "text"]
        log.step(f"Claude で深掘り中 (プロンプト {len(prompt)} 文字)...")
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=600
            )
        except FileNotFoundError:
            raise RuntimeError("Claude Code CLI が見つかりません。")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code CLI がタイムアウトしました（10分）")
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "出力なし").strip()[:500]
            raise RuntimeError(f"Claude Code CLI エラー (exit {proc.returncode}): {detail}")
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("Claude Code CLI から空の応答が返されました")
        return output
