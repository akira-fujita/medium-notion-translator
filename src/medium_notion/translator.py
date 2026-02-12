"""翻訳モジュール — Claude Code CLI (Max プラン) を使用

2ステップ方式:
  Step 1: 記事本文をマークダウンで翻訳（プレーンテキスト出力）
  Step 2: タイトル翻訳・カテゴリ・構造化要約を JSON で取得
"""

import json
import subprocess
import textwrap

from .config import Config
from .models import MediumArticle, TranslationResult
from . import logger as log

# --- Step 1: 翻訳プロンプト（マークダウン出力） ---
TRANSLATE_PROMPT = textwrap.dedent("""\
    あなたは技術記事の翻訳者です。以下の英語記事を日本語に翻訳してください。

    ## ルール
    - 自然で読みやすい日本語にする
    - 技術用語（Web3, blockchain, cross-chain bridge, DeFi, smart contract 等）は
      原文の英語をそのまま残すか、「クロスチェーンブリッジ」のようにカタカナ表記する
    - コードブロックやコマンドはそのまま維持する
    - 段落構造を維持する
    - マークダウン形式で出力する
    - 翻訳のみを出力し、前置きや説明は不要

    ---

    ## 記事タイトル
    {title}

    ## 記事本文
    {content}
""")

# --- Step 2: メタデータ抽出プロンプト（JSON 出力） ---
METADATA_PROMPT = textwrap.dedent("""\
    あなたは Engineering Manager 向けのナレッジキュレーターです。
    以下の技術記事を分析し、JSON で結果を返してください。
    JSON のみを出力し、他のテキストは含めないでください。

    出力形式:
    {{
      "japanese_title": "日本語タイトル",
      "categories": ["カテゴリ1", "カテゴリ2"],
      "summary": {{
        "overview": "記事全体の要旨を2〜3文で簡潔にまとめる",
        "learnings": "この記事から学べる新しい知見・新規性を箇条書き（各項目1文）で2〜3点",
        "use_cases": "EM・開発チームが実務に落とし込める具体的な活用方法を2〜3点",
        "connections": "過去に読んだ記事との関連性・組み合わせて活用できるアイデアを1〜2点（該当なしなら空文字）"
      }}
    }}

    japanese_title のルール:
    - 記事タイトルを自然な日本語に翻訳する
    - 技術用語（Claude Code, API, Web3 等の固有名詞）は英語のまま残す

    summary の各フィールドのルール:
    - overview: 「何についての記事で、結論は何か」を簡潔に
    - learnings: EMとして知っておくべき新しい知見。既知の一般論は含めない
    - use_cases: 「チームにどう展開できるか」「1on1や意思決定でどう活かせるか」の視点
    - connections: 下記の「過去に読んだ記事一覧」を参照し、関連する記事があればタイトルを引用して
      具体的にどう組み合わせると価値が生まれるかを提案する。該当がなければ空文字 ""

    カテゴリの選択肢（1〜3個選択）:
    Web3, DeFi, Blockchain, Cross-chain, Bridge, Smart Contract,
    Layer2, NFT, DAO, Security, Development, AI, ML, LLM,
    DevOps, DevTools, Programming, Cloud, Infrastructure,
    Frontend, Backend, Mobile, Data, Design, Career, Other

    ---

    記事タイトル: {title}

    記事本文（先頭3000文字）:
    {content_preview}

    ---

    過去に読んだ記事一覧（Notion DB に登録済み）:
    {existing_articles}
""")

MAX_CHUNK_SIZE = 15000


class TranslationService:
    """Claude Code CLI を使った翻訳サービス（2ステップ方式）"""

    def __init__(self, config: Config):
        self.config = config

    def translate_article(
        self,
        article: MediumArticle,
        existing_articles: list[dict] | None = None,
    ) -> TranslationResult:
        """記事を日本語に翻訳（2ステップ）"""
        log.step(f"記事を翻訳中: 「{article.title}」({article.char_count}文字)")

        # === Step 1: 翻訳 ===
        log.step("[Step 1/2] 本文を翻訳中...")
        if article.char_count > MAX_CHUNK_SIZE:
            translated_content = self._translate_chunked(article)
        else:
            prompt = TRANSLATE_PROMPT.format(
                title=article.title,
                content=article.content,
            )
            translated_content = self._call_claude(prompt)

        log.success(f"翻訳完了 ({len(translated_content)} 文字)")

        # === Step 2: タイトル翻訳・カテゴリ・構造化要約を抽出 ===
        log.step("[Step 2/2] タイトル翻訳・カテゴリ・要約を抽出中...")
        japanese_title, categories, summary = self._extract_metadata(
            article, existing_articles or []
        )

        # 日英併記タイトル: 「日本語タイトル | English Title」
        if japanese_title and japanese_title != article.title:
            display_title = f"{japanese_title} | {article.title}"
        else:
            display_title = article.title

        result = TranslationResult(
            original=article,
            japanese_title=display_title,
            japanese_content=translated_content,
            categories=categories,
            summary=summary,
        )

        log.success(
            f"完了: タイトル=「{display_title}」, カテゴリ={categories}"
        )
        return result

    def _translate_chunked(self, article: MediumArticle) -> str:
        """長い記事をチャンク分割して翻訳"""
        paragraphs = article.content.split("\n\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for para in paragraphs:
            if current_size + len(para) > MAX_CHUNK_SIZE and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            current_chunk.append(para)
            current_size += len(para)

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        log.step(f"{len(chunks)} チャンクに分割しました")

        translated_parts: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            log.step(f"チャンク {i}/{len(chunks)} を翻訳中...")
            prompt = TRANSLATE_PROMPT.format(
                title=article.title,
                content=chunk,
            )
            translated_parts.append(self._call_claude(prompt))

        return "\n\n".join(translated_parts)

    def _extract_metadata(
        self,
        article: MediumArticle,
        existing_articles: list[dict],
    ) -> tuple[str | None, list[str], str | None]:
        """タイトル翻訳・カテゴリ・構造化要約を抽出"""
        # 既存記事一覧をフォーマット
        if existing_articles:
            articles_text = "\n".join(
                f"- {a.get('title', '?')} [{', '.join(a.get('categories', []))}]"
                for a in existing_articles[:50]  # 最大50件
            )
        else:
            articles_text = "（まだ登録された記事はありません）"

        prompt = METADATA_PROMPT.format(
            title=article.title,
            content_preview=article.content[:3000],
            existing_articles=articles_text,
        )

        try:
            raw = self._call_claude(prompt)
            data = self._parse_json(raw)
            if data:
                japanese_title = data.get("japanese_title", "")
                categories = data.get("categories", [])
                summary_data = data.get("summary", {})

                # 構造化要約をマークダウン文字列に変換
                if isinstance(summary_data, dict):
                    summary = self._format_structured_summary(summary_data)
                else:
                    summary = str(summary_data)

                return japanese_title, categories, summary
        except Exception as e:
            log.warn(f"メタデータ抽出に失敗（翻訳は成功済み）: {e}")

        return None, [], None

    @staticmethod
    def _format_structured_summary(data: dict) -> str:
        """構造化された要約データをマークダウン文字列に変換"""
        sections = []

        if data.get("overview"):
            sections.append(f"📖 概要\n{data['overview']}")

        if data.get("learnings"):
            sections.append(f"💡 学び・新規性\n{data['learnings']}")

        if data.get("use_cases"):
            sections.append(f"🛠 活用方法\n{data['use_cases']}")

        if data.get("connections"):
            sections.append(f"🔗 他の記事との関連\n{data['connections']}")

        return "\n\n".join(sections) if sections else ""

    def _parse_json(self, text: str) -> dict | None:
        """テキストから JSON を抽出してパース"""
        import re

        # ```json ブロック
        m = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        # トップレベルの { } を探す
        brace_start = text.find("{")
        if brace_start != -1:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except json.JSONDecodeError:
                            pass
                        break

        return None

    def _call_claude(self, prompt: str) -> str:
        """Claude Code CLI を呼び出して応答を取得（stdin 経由）"""
        cmd = [
            "claude",
            "-p",
            "--output-format", "text",
        ]

        log.step(f"Claude Code CLI を呼び出し中 (プロンプト {len(prompt)} 文字)...")

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if proc.returncode != 0:
                stderr_msg = proc.stderr.strip() if proc.stderr else ""
                stdout_msg = proc.stdout.strip() if proc.stdout else ""
                debug_info = []
                if stderr_msg:
                    debug_info.append(f"stderr: {stderr_msg[:500]}")
                if stdout_msg:
                    debug_info.append(f"stdout: {stdout_msg[:500]}")
                detail = "\n  ".join(debug_info) if debug_info else "出力なし"
                raise RuntimeError(
                    f"Claude Code CLI エラー (exit code: {proc.returncode}):\n  {detail}"
                )

            output = proc.stdout.strip()
            if not output:
                raise RuntimeError(
                    "Claude Code CLI から空の応答が返されました。\n"
                    "  → claude login でログイン状態を確認してください"
                )

            log.success(f"Claude Code CLI 応答取得 ({len(output)} 文字)")
            return output

        except FileNotFoundError:
            raise RuntimeError(
                "Claude Code CLI が見つかりません。\n"
                "  → npm install -g @anthropic-ai/claude-code でインストールしてください\n"
                "  → claude login でログインしてください"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code CLI がタイムアウトしました（10分）")
