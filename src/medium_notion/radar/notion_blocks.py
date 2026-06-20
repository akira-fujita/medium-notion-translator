"""マークダウン → Notion ブロック変換（radar 深掘り本文用）

notion_client.py の本文変換と同等の責務だが、あちらは TranslationResult に
密結合しているため、radar 用に自己完結した軽量版を用意する。
対応: 見出し(#〜###) / コード / 引用 / 箇条書き / 番号リスト / 段落。
インライン書式は **太字** `コード` [リンク](URL) に対応。
（将来 notion_client と統一する余地あり）
"""

import re

from ..notion_client import _normalize_code_language

MAX_BLOCK_TEXT_LENGTH = 2000


def _split_text(text: str, max_length: int = MAX_BLOCK_TEXT_LENGTH) -> list[str]:
    """長文を句点・改行境界で max_length 以下に分割する。"""
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        window = remaining[:max_length]
        cut = max(window.rfind("。"), window.rfind("\n"), window.rfind(". "))
        if cut <= 0:
            cut = max_length - 1
        chunks.append(remaining[: cut + 1])
        remaining = remaining[cut + 1 :]
    if remaining:
        chunks.append(remaining)
    return chunks


def _inline(text: str) -> list[dict]:
    """**太字** `コード` [リンク](URL) を Notion rich_text に変換。"""
    pattern = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
    parts: list[dict] = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            parts.append(_text_obj(text[pos : m.start()]))
        token = m.group(0)
        if token.startswith("**"):
            parts.append(_text_obj(token[2:-2], bold=True))
        elif token.startswith("`"):
            parts.append(_text_obj(token[1:-1], code=True))
        else:
            mm = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            parts.append(_text_obj(mm.group(1), link=mm.group(2)))
        pos = m.end()
    if pos < len(text):
        parts.append(_text_obj(text[pos:]))
    return parts or [_text_obj("")]


def _text_obj(content: str, bold=False, code=False, link: str | None = None) -> dict:
    obj: dict = {"type": "text", "text": {"content": content}}
    if link:
        obj["text"]["link"] = {"url": link}
    ann = {}
    if bold:
        ann["bold"] = True
    if code:
        ann["code"] = True
    if ann:
        obj["annotations"] = ann
    return obj


def _heading(text: str, level: int) -> dict:
    key = f"heading_{level}"
    return {"type": key, key: {"rich_text": _inline(text)}}


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": _inline(text)}}


def _bullet(text: str) -> dict:
    return {"type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _inline(text)}}


def _numbered(text: str) -> dict:
    return {"type": "numbered_list_item",
            "numbered_list_item": {"rich_text": _inline(text)}}


def _quote(text: str) -> dict:
    return {"type": "quote", "quote": {"rich_text": _inline(text)}}


def _code(code: str, language: str = "plain text") -> dict:
    return {"type": "code", "code": {
        "rich_text": [{"type": "text", "text": {"content": code}}],
        "language": language,
    }}


def markdown_to_blocks(content: str) -> list[dict]:
    """マークダウン文字列を Notion ブロックのリストに変換する。"""
    blocks: list[dict] = []
    # コードフェンス内の空行で分断しないよう、フェンス追跡しつつ段落分割
    paragraphs = _split_paragraphs(content)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith("### "):
            blocks.append(_heading(para[4:], 3))
        elif para.startswith("## "):
            blocks.append(_heading(para[3:], 2))
        elif para.startswith("# "):
            blocks.append(_heading(para[2:], 1))
        elif para.startswith("```"):
            lines = para.split("\n")
            first = lines[0].lstrip("`").strip()
            # Notion は固定の language enum のみ受け付ける。別名/未対応は正規化（無効は plain text）
            language = _normalize_code_language(first or "plain text")
            body = lines[1:-1] if len(lines) > 1 and lines[-1].strip() == "```" else lines[1:]
            for chunk in _split_text("\n".join(body)):
                blocks.append(_code(chunk, language))
        elif para.startswith("> "):
            blocks.append(_quote("\n".join(l.lstrip("> ").strip() for l in para.split("\n"))))
        elif re.match(r"^\d+\.\s", para):
            for line in para.split("\n"):
                m = re.match(r"^\d+\.\s+(.*)", line.strip())
                if m:
                    blocks.append(_numbered(m.group(1).strip()))
        elif para.startswith("- ") or para.startswith("* "):
            for line in para.split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    blocks.append(_bullet(line[2:].strip()))
        else:
            for chunk in _split_text(para):
                blocks.append(_paragraph(chunk))
    return blocks


def _split_paragraphs(content: str) -> list[str]:
    """空行で段落分割。ただしコードフェンス内の空行は区切らない。"""
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
            continue
        if not line.strip() and not in_fence:
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs
