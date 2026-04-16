"""Notion 連携 — データベースへのページ追加"""

import re
from datetime import date, datetime

from notion_client import Client as NotionSDKClient
from notion_client.errors import APIResponseError

from .config import Config
from .models import TranslationResult, NotionPage
from . import logger as log

# Notion ブロックの最大文字数（API 制限）
MAX_BLOCK_TEXT_LENGTH = 2000

# Notion API がサポートするコードブロック言語
NOTION_CODE_LANGUAGES = {
    "abap", "abc", "agda", "arduino", "ascii art", "assembly",
    "bash", "basic", "bnf", "c", "c#", "c++", "clojure",
    "coffeescript", "coq", "css", "dart", "dhall", "diff",
    "docker", "ebnf", "elixir", "elm", "erlang", "f#", "flow",
    "fortran", "gherkin", "glsl", "go", "graphql", "groovy",
    "haskell", "hcl", "html", "idris", "java", "javascript",
    "json", "julia", "kotlin", "latex", "less", "lisp",
    "livescript", "llvm ir", "lua", "makefile", "markdown",
    "markup", "matlab", "mathematica", "mermaid", "nix",
    "notion formula", "objective-c", "ocaml", "pascal", "perl",
    "php", "plain text", "powershell", "prolog", "protobuf",
    "purescript", "python", "r", "racket", "reason", "ruby",
    "rust", "sass", "scala", "scheme", "scss", "shell",
    "smalltalk", "solidity", "sql", "swift", "toml", "typescript",
    "vb.net", "verilog", "vhdl", "visual basic", "webassembly",
    "xml", "yaml", "java/c/c++/c#",
}

# よくある言語名の別名マッピング
_LANGUAGE_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "sh": "shell",
    "yml": "yaml",
    "dockerfile": "docker",
    "objectivec": "objective-c",
    "objective c": "objective-c",
    "cplusplus": "c++",
    "csharp": "c#",
    "fsharp": "f#",
    "golang": "go",
    "tex": "latex",
    "text": "plain text",
    "txt": "plain text",
    "": "plain text",
}


def _normalize_code_language(language: str) -> str:
    """コード言語名を Notion がサポートする名前に正規化する"""
    lang = language.strip().lower()
    # 完全一致
    if lang in NOTION_CODE_LANGUAGES:
        return lang
    # 別名マッピング
    if lang in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[lang]
    # 部分一致（例: "python3" → "python"）
    for supported in NOTION_CODE_LANGUAGES:
        if lang.startswith(supported) or supported.startswith(lang):
            return supported
    # マッチしない場合は plain text にフォールバック
    return "plain text"


class NotionClient:
    """Notion API を使ってデータベースにページを作成するクライアント"""

    def __init__(self, config: Config):
        self.config = config
        self.client = NotionSDKClient(auth=config.notion_api_key)
        self.database_id = config.notion_database_id_formatted
        self._has_topics_property = False

    def check_access(self) -> bool:
        """データベースへのアクセス権限を確認"""
        try:
            db = self.client.data_sources.retrieve(data_source_id=self.database_id)
            db_title = ""
            for t in db.get("title", []):
                db_title += t.get("plain_text", "")
            # DB スキーマから Topics プロパティの有無を検出
            db_props = db.get("properties", {})
            self._has_topics_property = "Topics" in db_props
            log.success(f"Notion DB に接続: 「{db_title}」")
            return True
        except APIResponseError as e:
            if e.status == 404:
                log.error(
                    "Notion DB が見つかりません。\n"
                    "  → Database ID を確認してください\n"
                    "  → インテグレーションに DB へのアクセス権限を付与してください\n"
                    "    (DB → ... → コネクト → インテグレーションを追加)"
                )
            elif e.status == 401:
                log.error("Notion API キーが無効です")
            else:
                log.error(f"Notion API エラー: {e}")
            return False

    def list_articles(self) -> list[dict]:
        """DB 内の既存記事一覧を取得（タイトル・カテゴリ）"""
        articles = []
        try:
            has_more = True
            start_cursor = None
            while has_more:
                params = {
                    "data_source_id": self.database_id,
                    "page_size": 100,
                    "sorts": [{"property": "create date", "direction": "descending"}],
                }
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = self.client.data_sources.query(**params)

                for page in response.get("results", []):
                    props = page.get("properties", {})

                    # タイトル取得
                    title_parts = props.get("名前", {}).get("title", [])
                    title = "".join(t.get("plain_text", "") for t in title_parts)

                    # カテゴリ取得
                    cats_data = props.get("Categories", {}).get("multi_select", [])
                    categories = [c.get("name", "") for c in cats_data]

                    if title:
                        articles.append({
                            "title": title,
                            "categories": categories,
                        })

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

            log.step(f"既存記事 {len(articles)} 件を取得")
        except APIResponseError as e:
            log.warn(f"既存記事一覧の取得に失敗: {e}")

        return articles

    def list_existing_urls(self) -> set[str]:
        """DB 内の既存記事の URL 一覧を取得（重複チェック用）"""
        urls: set[str] = set()

        try:
            has_more = True
            start_cursor = None
            while has_more:
                params: dict = {
                    "data_source_id": self.database_id,
                    "page_size": 100,
                }
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = self.client.data_sources.query(**params)

                for page in response.get("results", []):
                    props = page.get("properties", {})
                    url_val = props.get("URL", {}).get("url")
                    if url_val:
                        urls.add(url_val)

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

            log.step(f"Notion DB に登録済みの URL: {len(urls)} 件")
        except Exception as e:
            log.warn(f"Notion DB の URL 取得に失敗: {e}")

        return urls

    def list_existing_topics(self) -> list[str]:
        """DB 内の既存 Topics を重複排除してソート済みリストで返す"""
        topics: set[str] = set()

        try:
            has_more = True
            start_cursor = None
            while has_more:
                params: dict = {
                    "data_source_id": self.database_id,
                    "page_size": 100,
                }
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = self.client.data_sources.query(**params)

                for page in response.get("results", []):
                    props = page.get("properties", {})
                    topics_data = props.get("Topics", {}).get("multi_select", [])
                    for t in topics_data:
                        name = t.get("name", "")
                        if name:
                            topics.add(name)

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

            log.step(f"既存 Topics: {len(topics)} 件")
        except Exception as e:
            log.warn(f"既存 Topics の取得に失敗: {e}")

        return sorted(topics)

    def list_pages_without_topics(self) -> list[dict]:
        """Topics が未設定のページ一覧を取得（バックフィル用）"""
        pages: list[dict] = []

        try:
            has_more = True
            start_cursor = None
            while has_more:
                params: dict = {
                    "data_source_id": self.database_id,
                    "page_size": 100,
                }
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = self.client.data_sources.query(**params)

                for page in response.get("results", []):
                    props = page.get("properties", {})

                    # Topics が空または未設定のページを対象にする
                    topics_data = props.get("Topics", {}).get("multi_select", [])
                    if topics_data:
                        continue

                    title_parts = props.get("名前", {}).get("title", [])
                    title = "".join(t.get("plain_text", "") for t in title_parts)
                    url = props.get("URL", {}).get("url", "")

                    if title:
                        pages.append({
                            "page_id": page["id"],
                            "title": title,
                            "url": url,
                        })

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

            log.step(f"Topics 未設定: {len(pages)} 件")
        except APIResponseError as e:
            log.warn(f"ページ一覧の取得に失敗: {e}")

        return pages

    def get_page_text(self, page_id: str) -> str:
        """ページの blocks からテキストを抽出する"""
        texts: list[str] = []

        try:
            has_more = True
            start_cursor = None
            while has_more:
                params: dict = {"block_id": page_id}
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = self.client.blocks.children.list(**params)

                for block in response.get("results", []):
                    block_type = block.get("type", "")
                    block_data = block.get(block_type, {})
                    rich_text = block_data.get("rich_text", [])
                    text = "".join(
                        t.get("plain_text", "") for t in rich_text
                    )
                    if text:
                        texts.append(text)

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

        except Exception as e:
            log.warn(f"ページ本文の取得に失敗: {e}")

        return "\n".join(texts)

    def update_page_topics(self, page_id: str, topics: list[str]) -> None:
        """ページの Topics プロパティを更新する"""
        self.client.pages.update(
            page_id=page_id,
            properties={
                "Topics": {
                    "multi_select": [
                        {"name": topic} for topic in topics
                    ]
                }
            },
        )

    def create_page(
        self,
        result: TranslationResult,
        score: int | None = None,
    ) -> NotionPage:
        """翻訳結果を Notion DB に新規ページとして追加"""
        log.step(f"Notion にページを作成中: 「{result.japanese_title}」")

        # プロパティの構築
        properties = self._build_properties(result, score)

        # 本文ブロックの構築
        children = self._build_content_blocks(result)

        # Notion API は 1 リクエストあたり最大 100 ブロック
        MAX_BLOCKS_PER_REQUEST = 100

        try:
            # 最初の 100 ブロックでページを作成
            first_batch = children[:MAX_BLOCKS_PER_REQUEST]
            response = self.client.pages.create(
                parent={"data_source_id": self.database_id},
                properties=properties,
                children=first_batch,
            )

            page_id = response["id"]
            page_url = response.get("url", "")

            # 残りのブロックを 100 件ずつ追記
            remaining = children[MAX_BLOCKS_PER_REQUEST:]
            if remaining:
                log.step(
                    f"ブロック数 {len(children)} → "
                    f"{len(remaining)} ブロックを追記中..."
                )
            for i in range(0, len(remaining), MAX_BLOCKS_PER_REQUEST):
                chunk = remaining[i : i + MAX_BLOCKS_PER_REQUEST]
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=chunk,
                )

            log.success(f"Notion ページ作成完了: {page_url}")

            return NotionPage(
                page_id=page_id,
                title=result.japanese_title,
                url=page_url,
                created_at=datetime.now(),
            )

        except APIResponseError as e:
            log.error(f"Notion ページ作成失敗: {e}")
            raise RuntimeError(f"Notion API エラー: {e}")

    def _build_properties(
        self,
        result: TranslationResult,
        score: int | None = None,
    ) -> dict:
        """Notion DB のプロパティを構築"""
        properties: dict = {
            # 名前（タイトル）
            "名前": {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": result.japanese_title},
                    }
                ]
            },
            # URL（元記事）
            "URL": {"url": result.original.url},
            # create date（ページ作成日 = 翻訳登録日）
            "create date": {"date": {"start": date.today().isoformat()}},
        }

        # Categories（multi-select）
        if result.categories:
            properties["Categories"] = {
                "multi_select": [
                    {"name": cat} for cat in result.categories
                ]
            }

        # Topics（multi-select） — DB にプロパティが存在する場合のみ
        if result.topics and self._has_topics_property:
            properties["Topics"] = {
                "multi_select": [
                    {"name": topic} for topic in result.topics
                ]
            }

        # Score（オプション）
        if score is not None:
            properties["Score"] = {"number": score}

        return properties

    def _build_content_blocks(self, result: TranslationResult) -> list[dict]:
        """翻訳本文を Notion ブロックに変換"""
        blocks: list[dict] = []

        # 目次（ページ先頭に配置して全体を把握しやすくする）
        blocks.append(self._table_of_contents_block())
        blocks.append(self._divider_block())

        # 要約セクション（構造化された各セクションを個別コールアウトで表示）
        if result.summary:
            blocks.append(self._heading_block("要約", level=2))
            blocks.extend(self._build_summary_blocks(result.summary))
            blocks.append(self._divider_block())

        # 翻訳本文
        blocks.append(self._heading_block("翻訳", level=2))

        # 本文を段落ブロックに分割
        paragraphs = result.japanese_content.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 見出し判定
            if para.startswith("### "):
                blocks.append(self._heading_block(para[4:], level=3))
            elif para.startswith("## "):
                blocks.append(self._heading_block(para[3:], level=2))
            elif para.startswith("# "):
                blocks.append(self._heading_block(para[2:], level=1))
            elif para.startswith("```"):
                # コードブロック
                code_content = para.strip("`").strip()
                lang_end = code_content.find("\n")
                if lang_end > 0:
                    language = code_content[:lang_end].strip()
                    code_content = code_content[lang_end + 1:]
                else:
                    language = "plain text"
                language = _normalize_code_language(language)
                for chunk in self._split_text(code_content, MAX_BLOCK_TEXT_LENGTH):
                    blocks.append(self._code_block(chunk, language))
            elif para.startswith("> "):
                # 引用ブロック
                quote_text = "\n".join(
                    line.lstrip("> ").strip()
                    for line in para.split("\n")
                )
                blocks.append(self._quote_block(quote_text))
            elif re.match(r"^\d+\.\s", para):
                # 番号付きリスト
                for line in para.split("\n"):
                    line = line.strip()
                    m = re.match(r"^\d+\.\s+(.*)", line)
                    if m:
                        blocks.append(
                            self._numbered_list_block(m.group(1).strip())
                        )
            elif para.startswith("- ") or para.startswith("* "):
                # 箇条書き
                for line in para.split("\n"):
                    line = line.strip()
                    if line.startswith("- ") or line.startswith("* "):
                        blocks.append(
                            self._bulleted_list_block(line[2:].strip())
                        )
            elif para.startswith("[画像:"):
                # 画像キャプション → イタリックの段落
                blocks.append(self._paragraph_block(para, italic=True))
            else:
                # 通常の段落（インライン書式付き）
                for chunk in self._split_text(para, MAX_BLOCK_TEXT_LENGTH):
                    blocks.append(self._rich_paragraph_block(chunk))

        # 元記事リンク
        blocks.append(self._divider_block())
        blocks.append(self._bookmark_block(result.original.url))

        return blocks

    # === rich_text パーサー ===

    @staticmethod
    def _parse_inline_markdown(text: str) -> list[dict]:
        """マークダウンのインライン書式を Notion rich_text 配列に変換

        対応書式:
          **太字**  →  bold
          *斜体*    →  italic
          `コード`  →  code
          [テキスト](URL)  →  リンク
        """
        parts: list[dict] = []

        # パターン: リンク > 太字 > 斜体 > インラインコード > プレーンテキスト
        pattern = re.compile(
            r'\[([^\]]+)\]\(([^)]+)\)'   # [text](url)
            r'|\*\*(.+?)\*\*'            # **bold**
            r'|\*(.+?)\*'                # *italic*
            r'|`([^`]+)`'                # `code`
        )

        last_end = 0
        for m in pattern.finditer(text):
            # マッチ前のプレーンテキスト
            if m.start() > last_end:
                plain = text[last_end:m.start()]
                if plain:
                    parts.append(_text_obj(plain))

            if m.group(1) is not None:
                # リンク [text](url)
                parts.append(_text_obj(m.group(1), link=m.group(2)))
            elif m.group(3) is not None:
                # 太字 **bold**
                parts.append(_text_obj(m.group(3), bold=True))
            elif m.group(4) is not None:
                # 斜体 *italic*
                parts.append(_text_obj(m.group(4), italic=True))
            elif m.group(5) is not None:
                # インラインコード `code`
                parts.append(_text_obj(m.group(5), code=True))

            last_end = m.end()

        # 残りのテキスト
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining:
                parts.append(_text_obj(remaining))

        # パースできなかった場合はプレーンテキスト
        if not parts:
            parts.append(_text_obj(text))

        return parts

    # === ブロック生成ヘルパー ===

    def _rich_paragraph_block(self, text: str) -> dict:
        """インライン書式付きの段落ブロック"""
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": self._parse_inline_markdown(text),
            },
        }

    @staticmethod
    def _paragraph_block(text: str, italic: bool = False) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [_text_obj(text, italic=italic)]
            },
        }

    @staticmethod
    def _heading_block(text: str, level: int = 2) -> dict:
        heading_type = f"heading_{min(level, 3)}"
        return {
            "object": "block",
            "type": heading_type,
            heading_type: {
                "rich_text": [_text_obj(text)]
            },
        }

    @staticmethod
    def _callout_block(text: str, emoji: str = "📝") -> dict:
        return {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"type": "emoji", "emoji": emoji},
                "rich_text": [_text_obj(text)],
            },
        }

    @staticmethod
    def _table_of_contents_block() -> dict:
        """目次ブロック — Notion が自動的に見出しから目次を生成する"""
        return {
            "object": "block",
            "type": "table_of_contents",
            "table_of_contents": {"color": "gray"},
        }

    def _build_summary_blocks(self, summary: str) -> list[dict]:
        """構造化要約をセクションごとのコールアウトブロックに分割

        入力形式（_format_structured_summary の出力）:
          📖 概要
          テキスト...

          💡 学び・新規性
          テキスト...

          🛠 活用方法
          テキスト...

          🔗 他の記事との関連
          テキスト...
        """
        # セクション区切りで分割（空行2つ）
        sections = summary.split("\n\n")
        blocks: list[dict] = []

        # 絵文字→セクション対応マップ
        emoji_map = {
            "📖": "📖",
            "💡": "💡",
            "🛠": "🛠",
            "🔗": "🔗",
        }

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            header = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            # ヘッダーから絵文字を抽出
            emoji = "📝"
            for key in emoji_map:
                if header.startswith(key):
                    emoji = emoji_map[key]
                    break

            # セクション見出し（heading_3 で目次に反映される）
            blocks.append(self._heading_block(header, level=3))

            # 本文をコールアウトブロックで表示
            if body:
                callout_text = body[:MAX_BLOCK_TEXT_LENGTH]
                blocks.append(self._callout_block(callout_text, emoji=emoji))

        # セクション分割できなかった場合はフォールバック
        if not blocks:
            blocks.append(self._callout_block(
                summary[:MAX_BLOCK_TEXT_LENGTH], emoji="📝"
            ))

        return blocks

    @staticmethod
    def _code_block(code: str, language: str = "plain text") -> dict:
        return {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [_text_obj(code)],
                "language": language,
            },
        }

    @staticmethod
    def _quote_block(text: str) -> dict:
        return {
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [_text_obj(text)],
            },
        }

    @staticmethod
    def _bulleted_list_block(text: str) -> dict:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [_text_obj(text)]
            },
        }

    @staticmethod
    def _numbered_list_block(text: str) -> dict:
        return {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": [_text_obj(text)]
            },
        }

    @staticmethod
    def _bookmark_block(url: str) -> dict:
        return {
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": url},
        }

    @staticmethod
    def _divider_block() -> dict:
        return {"object": "block", "type": "divider", "divider": {}}

    @staticmethod
    def _split_text(text: str, max_length: int) -> list[str]:
        """テキストを最大長で分割"""
        if len(text) <= max_length:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            split_pos = text.rfind("。", 0, max_length)
            if split_pos == -1:
                split_pos = text.rfind(". ", 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            else:
                split_pos += 1
            chunks.append(text[:split_pos])
            text = text[split_pos:].strip()
        return chunks


# === モジュールレベルのヘルパー関数 ===

def _text_obj(
    content: str,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    link: str | None = None,
) -> dict:
    """Notion rich_text オブジェクトを生成"""
    obj: dict = {
        "type": "text",
        "text": {"content": content},
    }
    if link and link.strip() and link.strip().startswith(("http://", "https://")):
        obj["text"]["link"] = {"url": link}

    annotations = {}
    if bold:
        annotations["bold"] = True
    if italic:
        annotations["italic"] = True
    if code:
        annotations["code"] = True
    if annotations:
        obj["annotations"] = annotations

    return obj
