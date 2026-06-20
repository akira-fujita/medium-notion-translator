from medium_notion.radar.notion_blocks import markdown_to_blocks


def _types(blocks):
    return [b["type"] for b in blocks]


def test_headings_paragraph_bullet_code():
    md = "## 見出し\n\n本文の段落です。\n\n- 箇条書き1\n- 箇条書き2\n\n```python\nprint(1)\n```"
    blocks = markdown_to_blocks(md)
    t = _types(blocks)
    assert "heading_2" in t
    assert "paragraph" in t
    assert t.count("bulleted_list_item") == 2
    assert "code" in t


def test_code_fence_language_normalized():
    """別名/未対応の言語タグは Notion が受け付ける値に正規化（無効は plain text）"""
    blocks = markdown_to_blocks("```ts\nconst x = 1;\n```")
    code = [b for b in blocks if b["type"] == "code"][0]
    assert code["code"]["language"] == "typescript"  # ts → typescript

    blocks2 = markdown_to_blocks("```madeuplang\nx\n```")
    code2 = [b for b in blocks2 if b["type"] == "code"][0]
    assert code2["code"]["language"] == "plain text"  # 未知 → plain text


def test_long_paragraph_split_under_2000_and_inline_bold():
    para = "本文。" * 800  # 2400字超
    blocks = markdown_to_blocks(para + "\n\nこれは **重要** な点です。")
    para_blocks = [b for b in blocks if b["type"] == "paragraph"]
    # 各段落ブロックは 2000 文字以下
    for b in para_blocks:
        total = sum(len(rt["text"]["content"]) for rt in b["paragraph"]["rich_text"])
        assert total <= 2000
    # 太字が rich_text の annotations に反映される
    last = para_blocks[-1]["paragraph"]["rich_text"]
    assert any(rt.get("annotations", {}).get("bold") for rt in last)
