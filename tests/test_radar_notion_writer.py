from datetime import date
from unittest.mock import MagicMock

from medium_notion.config import Config
from medium_notion.radar.models import FeedItem, ScoredItem, DeepDive
from medium_notion.radar.notion_writer import RadarNotionWriter


def _cfg():
    return Config(
        notion_api_key="ntn_real_key",
        notion_database_id="a" * 32,
        radar_notion_database_id="b" * 32,
    )


def test_build_properties_maps_all_fields():
    fi = FeedItem(url="https://x/a", title="EN Title", source="a16z", layer="VC")
    scored = ScoredItem(item=fi, score=8, jp_title="日本語題", summary="要約", why="刺さる理由")
    writer = RadarNotionWriter(_cfg())
    props = writer._build_properties(scored, date(2026, 6, 19))

    assert props["名前"]["title"][0]["text"]["content"] == "日本語題"
    assert props["URL"]["url"] == "https://x/a"
    assert props["Date"]["date"]["start"] == "2026-06-19"
    assert props["Source"]["select"]["name"] == "a16z"
    assert props["Layer"]["select"]["name"] == "VC"
    assert props["Summary"]["rich_text"][0]["text"]["content"] == "要約"
    assert props["Why"]["rich_text"][0]["text"]["content"] == "刺さる理由"
    assert props["Score"]["number"] == 8


def test_build_properties_falls_back_to_original_title():
    fi = FeedItem(url="https://x/a", title="EN Only", source="s", layer="L")
    scored = ScoredItem(item=fi, score=0)
    writer = RadarNotionWriter(_cfg())
    props = writer._build_properties(scored, date(2026, 6, 19))
    assert props["名前"]["title"][0]["text"]["content"] == "EN Only"


def test_append_item_returns_created_page_url():
    fi = FeedItem(url="https://x/a", title="T", source="s", layer="VC")
    scored = ScoredItem(item=fi, score=8, jp_title="題")
    writer = RadarNotionWriter(_cfg())
    writer.client = MagicMock()
    writer.client.pages.create.return_value = {"url": "https://notion.so/created-xyz"}

    url = writer.append_item(scored, date(2026, 6, 19))
    assert url == "https://notion.so/created-xyz"


def test_append_item_returns_none_on_failure():
    fi = FeedItem(url="https://x/a", title="T", source="s", layer="VC")
    scored = ScoredItem(item=fi, score=8, jp_title="題")
    writer = RadarNotionWriter(_cfg())
    writer.client = MagicMock()
    writer.client.pages.create.side_effect = RuntimeError("boom")

    assert writer.append_item(scored, date(2026, 6, 19)) is None


def test_append_item_writes_deepdive_body_when_present():
    fi = FeedItem(url="https://x/a", title="T", source="a16z", layer="VC")
    dd = DeepDive(translation="## 本文\n\n訳文です。", overview="概要",
                  key_points="押さえる点", critique="批判", fulltext_ok=True)
    scored = ScoredItem(item=fi, score=8, jp_title="題", deepdive=dd)
    writer = RadarNotionWriter(_cfg())
    writer.client = MagicMock()
    writer.client.pages.create.return_value = {"id": "page-1", "url": "https://notion.so/p1"}

    writer.append_item(scored, date(2026, 6, 19))

    # 本文ブロックが append された
    assert writer.client.blocks.children.append.called
    # append された全ブロックの text を集めて、4セクション見出しが含まれる
    all_text = ""
    for call in writer.client.blocks.children.append.call_args_list:
        for b in call.kwargs.get("children", []):
            for key in ("heading_2", "paragraph", "bulleted_list_item"):
                if key in b:
                    all_text += "".join(rt["text"]["content"] for rt in b[key]["rich_text"])
    assert "要約" in all_text
    assert "全文翻訳" in all_text
    assert "押さえるべきポイント" in all_text
    assert "批判的視点" in all_text


def test_deepdive_body_section_order():
    """ページ本文は 要約 → ポイント → 批判 → 全文翻訳（末尾）の順"""
    fi = FeedItem(url="https://x/a", title="T", source="a16z", layer="VC")
    dd = DeepDive(translation="本文の訳テキスト", overview="概要", key_points="押さえる点",
                  critique="批判", fulltext_ok=True)
    writer = RadarNotionWriter(_cfg())
    blocks = writer._build_deepdive_blocks(dd, "https://x/a")
    # 見出しテキストを順番に取り出す
    heads = []
    for b in blocks:
        if b["type"] == "heading_2":
            heads.append("".join(rt["text"]["content"] for rt in b["heading_2"]["rich_text"]))
    assert heads == ["📖 要約", "🎯 立場として押さえるべきポイント", "⚠️ 批判的視点", "📝 全文翻訳"]


def test_deepdive_body_batched_over_100_blocks():
    fi = FeedItem(url="https://x/a", title="T", source="a16z", layer="VC")
    # 200 段落の翻訳 → 100 ブロック上限で複数回 append される
    long_translation = "\n\n".join(f"段落{i}。" for i in range(200))
    dd = DeepDive(translation=long_translation, overview="概要", key_points="点",
                  critique="批判", fulltext_ok=True)
    scored = ScoredItem(item=fi, score=8, jp_title="題", deepdive=dd)
    writer = RadarNotionWriter(_cfg())
    writer.client = MagicMock()
    writer.client.pages.create.return_value = {"id": "page-1", "url": "https://notion.so/p1"}

    writer.append_item(scored, date(2026, 6, 19))

    assert writer.client.blocks.children.append.call_count >= 2
    for call in writer.client.blocks.children.append.call_args_list:
        assert len(call.kwargs["children"]) <= 100
