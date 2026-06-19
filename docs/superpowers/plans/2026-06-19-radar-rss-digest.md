# radar — RSS Tech ダイジェスト Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 複数の Tech 系 RSS/Atom フィードを毎朝巡回し、Claude が関心プロファイルで採点した結果を Slack にプッシュ + Notion に蓄積する `radar` コマンドを追加する。

**Architecture:** `src/medium_notion/radar/` に新パッケージを作る。`Source` プロトコル（rss.py が実装）→ 既読除外（state.py）→ Claude バッチ採点（curator.py）→ 振り分け & 2 レンダラ（digest.py）。既存の Claude CLI 呼び出し・Notion SDK・slack.py・config パターンを再利用。ブラウザ非依存。

**Tech Stack:** Python 3.10+, Click, feedparser, pyyaml, notion-client, httpx, pytest + pytest-asyncio。Claude Code CLI をサブプロセスで採点に使用。

## Global Constraints

- Python >= 3.10（既存）
- 新規依存は `feedparser`, `pyyaml` のみ（最小限に保つ）
- データモデルは `@dataclass` で書く（既存 `models.py` に合わせる。spec の "pydantic" 表記より既存コード優先）
- Claude CLI 呼び出しは `subprocess.run(["claude", "-p", "--output-format", "text"], input=prompt, text=True, capture_output=True, timeout=600)` パターンを踏襲
- JSON 抽出は ```json ブロック → トップレベル `{}` 深さカウントのフォールバック方式（既存 `translator._parse_json` と同等）
- 外部 I/O（ネットワーク / Claude CLI / Notion API）はテストで全てモック / fixture 化し、ユニットテストはネットワーク非依存
- ログは `from medium_notion import logger as log` の `log.step/success/warn/error` を使う
- 新着ゼロ / 全件既読のときは Slack/Notion へ何も送らず早期 return
- テストは `tests/test_radar_*.py` に配置（既存のフラット構成に合わせる）

---

### Task 1: 依存追加と radar 設定ローダ

**Files:**
- Modify: `pyproject.toml`（dependencies に `feedparser>=6.0`, `pyyaml>=6.0` 追加）
- Create: `src/medium_notion/radar/__init__.py`（空）
- Create: `src/medium_notion/radar/config.py`
- Test: `tests/test_radar_config.py`

**Interfaces:**
- Produces:
  - `FeedSpec`（dataclass）: `name: str`, `url: str`, `layer: str`
  - `RadarConfig`（dataclass）: `feeds: list[FeedSpec]`, `threshold: int`, `max_highlights: int`, `profile: list[str]`
  - `load_radar_config(feeds_path: str = "feeds.yml", interests_path: str = "interests.yml") -> RadarConfig`

- [ ] **Step 1: 依存を追加**

`pyproject.toml` の `dependencies` リストに 2 行追加:

```toml
dependencies = [
    "click>=8.0",
    "python-dotenv>=1.0",
    "playwright>=1.40",
    "notion-client>=2.0",
    "pydantic>=2.0",
    "loguru>=0.7",
    "rich>=13.0",
    "feedparser>=6.0",
    "pyyaml>=6.0",
]
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_radar_config.py`:

```python
import textwrap
from medium_notion.radar.config import load_radar_config, RadarConfig, FeedSpec


def test_load_radar_config_parses_feeds_and_interests(tmp_path):
    feeds = tmp_path / "feeds.yml"
    feeds.write_text(textwrap.dedent("""\
        - {name: "Anthropic News", url: "https://a.example/rss", layer: "一次情報"}
        - {name: "a16z", url: "https://b.example/feed", layer: "VC"}
    """))
    interests = tmp_path / "interests.yml"
    interests.write_text(textwrap.dedent("""\
        threshold: 7
        max_highlights: 8
        profile:
          - "AI 時代の EM"
          - "組織の構造変化"
    """))

    cfg = load_radar_config(str(feeds), str(interests))

    assert isinstance(cfg, RadarConfig)
    assert cfg.threshold == 7
    assert cfg.max_highlights == 8
    assert cfg.profile == ["AI 時代の EM", "組織の構造変化"]
    assert cfg.feeds == [
        FeedSpec(name="Anthropic News", url="https://a.example/rss", layer="一次情報"),
        FeedSpec(name="a16z", url="https://b.example/feed", layer="VC"),
    ]


def test_load_radar_config_defaults_when_optional_missing(tmp_path):
    feeds = tmp_path / "feeds.yml"
    feeds.write_text('- {name: "X", url: "https://x.example/rss", layer: "Substack"}\n')
    interests = tmp_path / "interests.yml"
    interests.write_text("profile:\n  - \"何か\"\n")

    cfg = load_radar_config(str(feeds), str(interests))

    assert cfg.threshold == 7        # default
    assert cfg.max_highlights == 8   # default
    assert len(cfg.feeds) == 1
```

- [ ] **Step 3: テストが失敗することを確認**

Run: `pytest tests/test_radar_config.py -v`
Expected: FAIL（`ModuleNotFoundError: medium_notion.radar.config`）

- [ ] **Step 4: 実装**

`src/medium_notion/radar/__init__.py`: 空ファイル（`""" radar パッケージ """` のみ）

`src/medium_notion/radar/config.py`:

```python
"""radar 設定ローダ — feeds.yml / interests.yml を読み込む"""

from dataclasses import dataclass, field

import yaml


@dataclass
class FeedSpec:
    """1 フィードの定義"""
    name: str
    url: str
    layer: str


@dataclass
class RadarConfig:
    """radar の動作設定（YAML 由来）"""
    feeds: list[FeedSpec] = field(default_factory=list)
    threshold: int = 7
    max_highlights: int = 8
    profile: list[str] = field(default_factory=list)


def load_radar_config(
    feeds_path: str = "feeds.yml",
    interests_path: str = "interests.yml",
) -> RadarConfig:
    """feeds.yml と interests.yml を読み込んで RadarConfig を返す"""
    with open(feeds_path, encoding="utf-8") as f:
        feeds_raw = yaml.safe_load(f) or []
    feeds = [
        FeedSpec(name=item["name"], url=item["url"], layer=item["layer"])
        for item in feeds_raw
    ]

    with open(interests_path, encoding="utf-8") as f:
        interests_raw = yaml.safe_load(f) or {}

    return RadarConfig(
        feeds=feeds,
        threshold=int(interests_raw.get("threshold", 7)),
        max_highlights=int(interests_raw.get("max_highlights", 8)),
        profile=list(interests_raw.get("profile", [])),
    )
```

- [ ] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_radar_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: コミット**

```bash
git add pyproject.toml src/medium_notion/radar/__init__.py src/medium_notion/radar/config.py tests/test_radar_config.py
git commit -m "feat(radar): add feeds.yml/interests.yml config loader"
```

---

### Task 2: radar データモデル

**Files:**
- Create: `src/medium_notion/radar/models.py`
- Test: `tests/test_radar_models.py`

**Interfaces:**
- Produces:
  - `FeedItem`（dataclass）: `url: str`, `title: str`, `source: str`, `layer: str`, `summary_raw: str = ""`, `published: str | None = None`, `guid: str = ""`。property `key -> str`（dedup キー = `guid or url`）
  - `ScoredItem`（dataclass）: `item: FeedItem`, `score: int = 0`, `jp_title: str = ""`, `summary: str = ""`, `why: str = ""`
  - `Digest`（dataclass）: `highlights: list[ScoredItem]`, `others: list[ScoredItem]`。property `is_empty -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_models.py`:

```python
from medium_notion.radar.models import FeedItem, ScoredItem, Digest


def test_feeditem_key_prefers_guid():
    item = FeedItem(url="https://x/a", title="T", source="S", layer="L", guid="g-1")
    assert item.key == "g-1"


def test_feeditem_key_falls_back_to_url():
    item = FeedItem(url="https://x/a", title="T", source="S", layer="L")
    assert item.key == "https://x/a"


def test_digest_is_empty():
    assert Digest(highlights=[], others=[]).is_empty is True
    fi = FeedItem(url="u", title="t", source="s", layer="l")
    assert Digest(highlights=[ScoredItem(item=fi)], others=[]).is_empty is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_models.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/medium_notion/radar/models.py`:

```python
"""radar データモデル"""

from dataclasses import dataclass, field


@dataclass
class FeedItem:
    """フィードから取得した 1 記事（採点前）"""
    url: str
    title: str
    source: str
    layer: str
    summary_raw: str = ""
    published: str | None = None
    guid: str = ""

    @property
    def key(self) -> str:
        """重複排除キー（guid 優先、無ければ URL）"""
        return self.guid or self.url


@dataclass
class ScoredItem:
    """Claude 採点後の記事"""
    item: FeedItem
    score: int = 0
    jp_title: str = ""
    summary: str = ""
    why: str = ""


@dataclass
class Digest:
    """振り分け済みのダイジェスト"""
    highlights: list[ScoredItem] = field(default_factory=list)
    others: list[ScoredItem] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.highlights and not self.others
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_models.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add src/medium_notion/radar/models.py tests/test_radar_models.py
git commit -m "feat(radar): add FeedItem/ScoredItem/Digest models"
```

---

### Task 3: 既読ストア（state）

**Files:**
- Create: `src/medium_notion/radar/state.py`
- Test: `tests/test_radar_state.py`

**Interfaces:**
- Consumes: `FeedItem`（Task 2）
- Produces:
  - `SeenStore(path: str)`
  - `SeenStore.filter_new(items: list[FeedItem]) -> list[FeedItem]`（既読キーを除外して返す。同一バッチ内の重複も 1 件に）
  - `SeenStore.mark_seen(items: list[FeedItem]) -> None`（キーを記録してファイルへ保存）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_state.py`:

```python
from medium_notion.radar.models import FeedItem
from medium_notion.radar.state import SeenStore


def _item(url, guid=""):
    return FeedItem(url=url, title="t", source="s", layer="l", guid=guid)


def test_first_run_all_new(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    items = [_item("https://x/a"), _item("https://x/b")]
    assert store.filter_new(items) == items


def test_marked_items_are_filtered_out(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path)
    a, b = _item("https://x/a"), _item("https://x/b")
    store.mark_seen([a])

    store2 = SeenStore(path)  # 再ロード（永続化を検証）
    assert store2.filter_new([a, b]) == [b]


def test_dedup_within_batch(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"))
    dup = [_item("https://x/a"), _item("https://x/a")]
    assert len(store.filter_new(dup)) == 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_state.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/medium_notion/radar/state.py`:

```python
"""radar 既読ストア — 処理済み記事キーを JSON で永続化"""

import json
import os

from .models import FeedItem


class SeenStore:
    """処理済み記事のキー（guid/URL）を保持し、新着を判定する"""

    def __init__(self, path: str):
        self.path = path
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if not os.path.exists(self.path):
            return set()
        try:
            with open(self.path, encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()

    def filter_new(self, items: list[FeedItem]) -> list[FeedItem]:
        """既読キーと、同一バッチ内の重複を除外した新着リストを返す"""
        result: list[FeedItem] = []
        batch_keys: set[str] = set()
        for item in items:
            if item.key in self._seen or item.key in batch_keys:
                continue
            batch_keys.add(item.key)
            result.append(item)
        return result

    def mark_seen(self, items: list[FeedItem]) -> None:
        """キーを記録してファイルへ保存する"""
        for item in items:
            self._seen.add(item.key)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self._seen), f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_state.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add src/medium_notion/radar/state.py tests/test_radar_state.py
git commit -m "feat(radar): add SeenStore for dedup/state tracking"
```

---

### Task 4: RSS ソースアダプタ

**Files:**
- Create: `src/medium_notion/radar/sources/__init__.py`（空）
- Create: `src/medium_notion/radar/sources/base.py`
- Create: `src/medium_notion/radar/sources/rss.py`
- Test: `tests/test_radar_rss.py`
- Test fixture: `tests/fixtures/sample_feed.xml`

**Interfaces:**
- Consumes: `FeedItem`（Task 2）, `FeedSpec`（Task 1）
- Produces:
  - `Source`（Protocol）: 属性 `name: str`, `layer: str`、メソッド `fetch(limit: int | None = None) -> list[FeedItem]`
  - `RssSource(spec: FeedSpec)`（`Source` 実装）。`fetch` は `feedparser.parse(self.spec.url)` を呼び、各 entry を `FeedItem` に変換。`limit` 指定時は先頭 `limit` 件。
  - パース時に `feedparser.parse` を使うため、テストはローカル XML 文字列を `feedparser.parse(xml_string)` で読めることを利用（ネットワーク非依存）。`RssSource` に `_parse(raw)` を分離し、テストはそれを叩く。

- [ ] **Step 1: フィクスチャを作る**

`tests/fixtures/sample_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Blog</title>
    <item>
      <title>First Post</title>
      <link>https://example.com/posts/first</link>
      <guid>https://example.com/posts/first</guid>
      <description>This is the first post summary.</description>
      <pubDate>Mon, 16 Jun 2026 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Post</title>
      <link>https://example.com/posts/second</link>
      <guid>guid-second-123</guid>
      <description>Second post about AI org change.</description>
      <pubDate>Tue, 17 Jun 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_radar_rss.py`:

```python
from pathlib import Path

from medium_notion.radar.config import FeedSpec
from medium_notion.radar.sources.rss import RssSource

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_extracts_feed_items():
    spec = FeedSpec(name="Sample Blog", url="https://example.com/rss", layer="一次情報")
    source = RssSource(spec)
    items = source._parse(FIXTURE.read_text(encoding="utf-8"))

    assert len(items) == 2
    first = items[0]
    assert first.title == "First Post"
    assert first.url == "https://example.com/posts/first"
    assert first.source == "Sample Blog"
    assert first.layer == "一次情報"
    assert "first post summary" in first.summary_raw.lower()
    assert items[1].guid == "guid-second-123"


def test_parse_respects_limit():
    spec = FeedSpec(name="Sample Blog", url="https://example.com/rss", layer="一次情報")
    source = RssSource(spec)
    items = source._parse(FIXTURE.read_text(encoding="utf-8"), limit=1)
    assert len(items) == 1
```

- [ ] **Step 3: テストが失敗することを確認**

Run: `pytest tests/test_radar_rss.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 4: 実装**

`src/medium_notion/radar/sources/__init__.py`: 空ファイル

`src/medium_notion/radar/sources/base.py`:

```python
"""Source プロトコル — 取得元の共通インターフェース"""

from typing import Protocol

from ..models import FeedItem


class Source(Protocol):
    """記事取得元。将来 GitHub Trending / Reddit もこの形で実装する"""
    name: str
    layer: str

    def fetch(self, limit: int | None = None) -> list[FeedItem]: ...
```

`src/medium_notion/radar/sources/rss.py`:

```python
"""RSS/Atom ソースアダプタ"""

import feedparser

from ..config import FeedSpec
from ..models import FeedItem
from ... import logger as log


class RssSource:
    """1 つの RSS/Atom フィードから FeedItem を取得する"""

    def __init__(self, spec: FeedSpec):
        self.spec = spec
        self.name = spec.name
        self.layer = spec.layer

    def fetch(self, limit: int | None = None) -> list[FeedItem]:
        """フィード URL を取得して FeedItem のリストを返す"""
        parsed = feedparser.parse(self.spec.url)
        return self._to_items(parsed, limit)

    def _parse(self, raw: str, limit: int | None = None) -> list[FeedItem]:
        """生 XML 文字列をパースする（テスト用・ネットワーク非依存）"""
        parsed = feedparser.parse(raw)
        return self._to_items(parsed, limit)

    def _to_items(self, parsed, limit: int | None) -> list[FeedItem]:
        entries = parsed.entries
        if limit is not None:
            entries = entries[:limit]
        items: list[FeedItem] = []
        for e in entries:
            url = e.get("link", "")
            if not url:
                continue
            items.append(
                FeedItem(
                    url=url,
                    title=e.get("title", "(no title)"),
                    source=self.spec.name,
                    layer=self.spec.layer,
                    summary_raw=e.get("summary", ""),
                    published=e.get("published", None),
                    guid=e.get("id", "") or e.get("guid", ""),
                )
            )
        return items
```

- [ ] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_radar_rss.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: コミット**

```bash
git add src/medium_notion/radar/sources/ tests/test_radar_rss.py tests/fixtures/sample_feed.xml
git commit -m "feat(radar): add Source protocol and RSS adapter"
```

---

### Task 5: Curator（Claude 採点）

**Files:**
- Create: `src/medium_notion/radar/curator.py`
- Test: `tests/test_radar_curator.py`

**Interfaces:**
- Consumes: `FeedItem`（Task 2）, `ScoredItem`（Task 2）, `RadarConfig`（Task 1）, `Config`（既存 `medium_notion.config`）
- Produces:
  - `Curator(config: Config)`
  - `Curator.score(items: list[FeedItem], radar_cfg: RadarConfig) -> list[ScoredItem]`
  - 内部: `_build_prompt(items, profile) -> str`, `_call_claude(prompt) -> str`, `_parse_json_list(text) -> list[dict]`, `_merge(items, scored_raw) -> list[ScoredItem]`
  - Claude 失敗時は全件 `ScoredItem(item=..., score=0)` で返す（情報を捨てない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_curator.py`:

```python
from unittest.mock import patch

from medium_notion.config import Config
from medium_notion.radar.config import RadarConfig
from medium_notion.radar.models import FeedItem
from medium_notion.radar.curator import Curator


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def _items():
    return [
        FeedItem(url="https://x/a", title="AI org change", source="a16z", layer="VC"),
        FeedItem(url="https://x/b", title="Some rust internals", source="Stripe", layer="一次情報"),
    ]


def test_score_merges_claude_output():
    radar_cfg = RadarConfig(profile=["AI 時代の EM"], threshold=7)
    fake = (
        '```json\n[{"url":"https://x/a","score":9,"jp_title":"AIで組織が変わる",'
        '"summary":"要約A","why":"EM に直撃"},'
        '{"url":"https://x/b","score":3,"jp_title":"Rust 内部","summary":"要約B","why":""}]\n```'
    )
    curator = Curator(_cfg())
    with patch.object(curator, "_call_claude", return_value=fake):
        scored = curator.score(_items(), radar_cfg)

    by_url = {s.item.url: s for s in scored}
    assert by_url["https://x/a"].score == 9
    assert by_url["https://x/a"].jp_title == "AIで組織が変わる"
    assert by_url["https://x/a"].why == "EM に直撃"
    assert by_url["https://x/b"].score == 3


def test_score_falls_back_when_claude_fails():
    radar_cfg = RadarConfig(profile=["x"], threshold=7)
    curator = Curator(_cfg())
    with patch.object(curator, "_call_claude", side_effect=RuntimeError("boom")):
        scored = curator.score(_items(), radar_cfg)

    assert len(scored) == 2
    assert all(s.score == 0 for s in scored)
    # 原題はフォールバックでも残る
    assert {s.item.url for s in scored} == {"https://x/a", "https://x/b"}


def test_score_empty_input_returns_empty():
    curator = Curator(_cfg())
    assert curator.score([], RadarConfig()) == []
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_curator.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/medium_notion/radar/curator.py`:

```python
"""Curator — Claude Code CLI で新着記事を関心プロファイルに照らして採点"""

import json
import re
import subprocess
import textwrap

from ..config import Config
from .config import RadarConfig
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

    def _merge(self, items: list[FeedItem], scored_raw: list[dict]) -> list[ScoredItem]:
        by_url = {d.get("url"): d for d in scored_raw if isinstance(d, dict)}
        result: list[ScoredItem] = []
        for it in items:
            d = by_url.get(it.url, {})
            result.append(
                ScoredItem(
                    item=it,
                    score=int(d.get("score", 0) or 0),
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
            raise RuntimeError(
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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_curator.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add src/medium_notion/radar/curator.py tests/test_radar_curator.py
git commit -m "feat(radar): add Curator for Claude relevance scoring"
```

---

### Task 6: Digest 振り分け & レンダラ

**Files:**
- Create: `src/medium_notion/radar/digest.py`
- Test: `tests/test_radar_digest.py`

**Interfaces:**
- Consumes: `ScoredItem`/`Digest`（Task 2）
- Produces:
  - `build_digest(scored: list[ScoredItem], threshold: int, max_highlights: int) -> Digest`（score 降順、`>= threshold` を highlights（上限 max_highlights、あふれは others へ）、未満を others）
  - `render_slack_text(digest: Digest) -> str`（Slack mrkdwn 文字列）
  - `render_slack_payload(digest: Digest) -> dict`（`{"text":..., "blocks":[...]}`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_digest.py`:

```python
from medium_notion.radar.models import FeedItem, ScoredItem
from medium_notion.radar.digest import build_digest, render_slack_text, render_slack_payload


def _scored(url, score, layer="VC", jp="JP", summary="S", why="W"):
    fi = FeedItem(url=url, title="EN", source="src", layer=layer)
    return ScoredItem(item=fi, score=score, jp_title=jp, summary=summary, why=why)


def test_build_digest_splits_by_threshold_sorted():
    scored = [_scored("u1", 5), _scored("u2", 9), _scored("u3", 7)]
    d = build_digest(scored, threshold=7, max_highlights=8)
    assert [s.item.url for s in d.highlights] == ["u2", "u3"]  # 降順
    assert [s.item.url for s in d.others] == ["u1"]


def test_build_digest_respects_max_highlights():
    scored = [_scored(f"u{i}", 8) for i in range(5)]
    d = build_digest(scored, threshold=7, max_highlights=3)
    assert len(d.highlights) == 3
    assert len(d.others) == 2  # あふれは others


def test_render_slack_text_contains_highlight_and_others():
    d = build_digest([_scored("u1", 9, jp="刺さる記事"), _scored("u2", 2, jp="その他記事")],
                     threshold=7, max_highlights=8)
    text = render_slack_text(d)
    assert "刺さる記事" in text
    assert "u1" in text
    assert "その他" in text  # その他セクション見出し


def test_render_slack_payload_shape():
    d = build_digest([_scored("u1", 9)], threshold=7, max_highlights=8)
    payload = render_slack_payload(d)
    assert "text" in payload and "blocks" in payload
    assert isinstance(payload["blocks"], list)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_digest.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`src/medium_notion/radar/digest.py`:

```python
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
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_digest.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: コミット**

```bash
git add src/medium_notion/radar/digest.py tests/test_radar_digest.py
git commit -m "feat(radar): add digest builder and Slack renderer"
```

---

### Task 7: Notion 書き込み（Tech Radar DB）と env 拡張

**Files:**
- Modify: `src/medium_notion/config.py`（`radar_notion_database_id`, `radar_slack_webhook_url` 追加 + ローダ）
- Create: `src/medium_notion/radar/notion_writer.py`
- Test: `tests/test_radar_notion_writer.py`
- Test: `tests/test_radar_config_env.py`

**Interfaces:**
- Consumes: `Config`（既存）, `ScoredItem`（Task 2）
- Produces:
  - `Config.radar_notion_database_id: str | None`, `Config.radar_slack_webhook_url: str | None`
  - `Config.radar_notion_database_id_formatted -> str`（ハイフン付き UUID。未設定なら空文字）
  - `RadarNotionWriter(config: Config)`、`append_item(scored: ScoredItem, when: date) -> None`
  - `RadarNotionWriter._build_properties(scored: ScoredItem, when: date) -> dict`（テスト対象。Notion プロパティ dict を返す）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_config_env.py`:

```python
import os
from medium_notion.config import load_config


def test_radar_env_loaded(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "ntn_real_key")
    monkeypatch.setenv("NOTION_DATABASE_ID", "a" * 32)
    monkeypatch.setenv("RADAR_NOTION_DATABASE_ID", "b" * 32)
    monkeypatch.setenv("RADAR_SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    cfg = load_config()
    assert cfg.radar_notion_database_id == "b" * 32
    assert cfg.radar_slack_webhook_url == "https://hooks.slack.test/x"
    assert cfg.radar_notion_database_id_formatted == (
        f"{'b'*8}-{'b'*4}-{'b'*4}-{'b'*4}-{'b'*12}"
    )
```

`tests/test_radar_notion_writer.py`:

```python
from datetime import date

from medium_notion.config import Config
from medium_notion.radar.models import FeedItem, ScoredItem
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
    scored = ScoredItem(item=fi, score=0)  # jp_title 空
    writer = RadarNotionWriter(_cfg())
    props = writer._build_properties(scored, date(2026, 6, 19))
    assert props["名前"]["title"][0]["text"]["content"] == "EN Only"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_config_env.py tests/test_radar_notion_writer.py -v`
Expected: FAIL（`AttributeError`/`ModuleNotFoundError`）

- [ ] **Step 3: config.py を拡張**

`src/medium_notion/config.py` の `Config` クラスにフィールド追加（`slack_webhook_url` の下）:

```python
    slack_webhook_url: str | None = None
    radar_notion_database_id: str | None = None
    radar_slack_webhook_url: str | None = None
```

`notion_database_id_formatted` property の下に追加:

```python
    @property
    def radar_notion_database_id_formatted(self) -> str:
        """radar 用 DB ID をハイフン付き UUID 形式に変換（未設定なら空文字）"""
        d = (self.radar_notion_database_id or "").replace("-", "")
        if len(d) == 32:
            return f"{d[:8]}-{d[8:12]}-{d[12:16]}-{d[16:20]}-{d[20:]}"
        return d
```

`load_config` の `Config(...)` 呼び出しに追加:

```python
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
        radar_notion_database_id=os.getenv("RADAR_NOTION_DATABASE_ID") or None,
        radar_slack_webhook_url=os.getenv("RADAR_SLACK_WEBHOOK_URL") or None,
```

- [ ] **Step 4: notion_writer.py を実装**

`src/medium_notion/radar/notion_writer.py`:

```python
"""Tech Radar DB への 1 記事 = 1 行 書き込み"""

from datetime import date

from notion_client import Client as NotionSDKClient

from ..config import Config
from .models import ScoredItem
from .. import logger as log

MAX_TEXT = 2000


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": (content or "")[:MAX_TEXT]}}]


class RadarNotionWriter:
    """Tech Radar データベースに採点済み記事を追加する"""

    def __init__(self, config: Config):
        self.client = NotionSDKClient(auth=config.notion_api_key)
        self.database_id = config.radar_notion_database_id_formatted

    def _build_properties(self, scored: ScoredItem, when: date) -> dict:
        title = scored.jp_title or scored.item.title
        return {
            "名前": {"title": [{"type": "text", "text": {"content": title[:MAX_TEXT]}}]},
            "URL": {"url": scored.item.url},
            "Date": {"date": {"start": when.isoformat()}},
            "Source": {"select": {"name": scored.item.source}},
            "Layer": {"select": {"name": scored.item.layer}},
            "Summary": {"rich_text": _rich_text(scored.summary)},
            "Why": {"rich_text": _rich_text(scored.why)},
            "Score": {"number": scored.score},
        }

    def append_item(self, scored: ScoredItem, when: date) -> None:
        """1 記事を Tech Radar DB に追加する。失敗時はログのみ（継続）"""
        try:
            self.client.pages.create(
                parent={"data_source_id": self.database_id},
                properties=self._build_properties(scored, when),
            )
        except Exception as e:
            log.warn(f"Notion 追加に失敗（スキップ）: {scored.item.url}: {e}")
```

- [ ] **Step 5: テストが通ることを確認**

Run: `pytest tests/test_radar_config_env.py tests/test_radar_notion_writer.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: コミット**

```bash
git add src/medium_notion/config.py src/medium_notion/radar/notion_writer.py tests/test_radar_config_env.py tests/test_radar_notion_writer.py
git commit -m "feat(radar): add Tech Radar Notion writer and radar env config"
```

---

### Task 8: Slack 投稿関数

**Files:**
- Modify: `src/medium_notion/slack.py`（`post_digest` 追加）
- Test: `tests/test_radar_slack.py`

**Interfaces:**
- Consumes: `Digest`（Task 2）, `render_slack_payload`（Task 6）
- Produces:
  - `async def post_digest(webhook_url: str, digest: Digest) -> bool`（既存 `notify_slack` と同じ httpx パターン。空 digest または webhook 未設定なら送らず False）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_slack.py`:

```python
import pytest

from medium_notion.radar.models import FeedItem, ScoredItem, Digest
from medium_notion.slack import post_digest


def _digest():
    fi = FeedItem(url="https://x/a", title="t", source="s", layer="VC")
    return Digest(highlights=[ScoredItem(item=fi, score=9, jp_title="題")], others=[])


async def test_post_digest_no_webhook_returns_false():
    assert await post_digest("", _digest()) is False


async def test_post_digest_empty_digest_returns_false():
    assert await post_digest("https://hooks.slack.test/x", Digest()) is False


async def test_post_digest_posts_payload(monkeypatch):
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json, timeout):
            sent["url"] = url
            sent["json"] = json
            return FakeResp()

    monkeypatch.setattr("medium_notion.slack.httpx.AsyncClient", lambda: FakeClient())
    ok = await post_digest("https://hooks.slack.test/x", _digest())
    assert ok is True
    assert sent["url"] == "https://hooks.slack.test/x"
    assert "blocks" in sent["json"]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_slack.py -v`
Expected: FAIL（`ImportError: cannot import name 'post_digest'`）

- [ ] **Step 3: 実装**

`src/medium_notion/slack.py` の末尾に追加（ファイル先頭の import 群に `from .radar.digest import render_slack_payload` と `from .radar.models import Digest` を追加）:

```python
async def post_digest(webhook_url: str, digest: "Digest") -> bool:
    """Tech Radar ダイジェストを Slack に投稿する

    Args:
        webhook_url: Slack Incoming Webhook URL
        digest: 振り分け済みダイジェスト

    Returns:
        送信成功なら True。webhook 未設定 / 空ダイジェストなら False
    """
    if not webhook_url or digest.is_empty:
        return False

    payload = render_slack_payload(digest)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
        log.success("Slack ダイジェストを送信しました")
        return True
    except Exception as e:
        log.warn(f"Slack ダイジェスト送信に失敗: {e}")
        return False
```

> import の循環に注意: `slack.py` から `radar.digest` を import する。`radar.digest` は `slack` を import しないので循環しない。`Digest` の型ヒントは文字列 `"Digest"` で前方参照にしておくと安全（上で import 済みなら実体でも可）。

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_slack.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add src/medium_notion/slack.py tests/test_radar_slack.py
git commit -m "feat(radar): add post_digest Slack publisher"
```

---

### Task 9: orchestrator と CLI コマンド

**Files:**
- Create: `src/medium_notion/radar/pipeline.py`
- Modify: `src/medium_notion/cli.py`（`radar` コマンド追加）
- Create: `feeds.yml`（リポジトリルート）
- Create: `interests.yml`（リポジトリルート）
- Modify: `.env.example`（radar 用 env 追記）
- Test: `tests/test_radar_pipeline.py`

**Interfaces:**
- Consumes: 全 Task の成果物
- Produces:
  - `run_radar(config: Config, radar_cfg: RadarConfig, seen: SeenStore, *, dry_run: bool, limit: int | None, when: date, scorer=None, notion_writer=None, slack_post=None) -> Digest`
    - 依存（scorer/notion_writer/slack_post）は注入可能にしてテストでモックする。None のとき本番実装を使う。
  - フロー: 各 feed を `RssSource.fetch(limit)` → 集約 → `seen.filter_new` → 空なら空 `Digest` を返して終了 → `scorer.score` → `build_digest` → dry_run でなければ Notion 各行 append + Slack post → `seen.mark_seen`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_radar_pipeline.py`:

```python
from datetime import date
from unittest.mock import MagicMock

from medium_notion.config import Config
from medium_notion.radar.config import RadarConfig, FeedSpec
from medium_notion.radar.models import FeedItem, ScoredItem, Digest
from medium_notion.radar.state import SeenStore
from medium_notion.radar.pipeline import run_radar


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def test_run_radar_empty_when_no_new_items(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))

    # フィードは1件返すが、既読として事前登録 → 新着ゼロ
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )
    seen.mark_seen([item])

    scorer = MagicMock()
    digest = run_radar(_cfg(), radar_cfg, seen, dry_run=True, limit=None,
                       when=date(2026, 6, 19), scorer=scorer)
    assert digest.is_empty
    scorer.score.assert_not_called()  # 新着ゼロなら採点しない


def test_run_radar_dry_run_does_not_write(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )

    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=item, score=9, jp_title="題")]
    notion_writer = MagicMock()
    slack_post = MagicMock()

    digest = run_radar(_cfg(), radar_cfg, seen, dry_run=True, limit=None,
                       when=date(2026, 6, 19), scorer=scorer,
                       notion_writer=notion_writer, slack_post=slack_post)

    assert len(digest.highlights) == 1
    notion_writer.append_item.assert_not_called()
    slack_post.assert_not_called()
    # dry_run でも既読化はしない（次回も拾えるように）
    assert seen.filter_new([item]) == [item]


def test_run_radar_writes_and_marks_seen(tmp_path, monkeypatch):
    radar_cfg = RadarConfig(feeds=[FeedSpec("S", "https://x/rss", "VC")], threshold=7)
    seen = SeenStore(str(tmp_path / "seen.json"))
    item = FeedItem(url="https://x/a", title="t", source="S", layer="VC")
    monkeypatch.setattr(
        "medium_notion.radar.pipeline.RssSource.fetch", lambda self, limit=None: [item]
    )

    scorer = MagicMock()
    scorer.score.return_value = [ScoredItem(item=item, score=9, jp_title="題")]
    notion_writer = MagicMock()
    slack_post = MagicMock()

    run_radar(_cfg(), radar_cfg, seen, dry_run=False, limit=None,
              when=date(2026, 6, 19), scorer=scorer,
              notion_writer=notion_writer, slack_post=slack_post)

    notion_writer.append_item.assert_called_once()
    slack_post.assert_called_once()
    assert seen.filter_new([item]) == []  # 既読化された
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/test_radar_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: pipeline.py を実装**

`src/medium_notion/radar/pipeline.py`:

```python
"""radar オーケストレーション — fetch → 採点 → 振り分け → 出力"""

import asyncio
from datetime import date

from ..config import Config
from .config import RadarConfig
from .curator import Curator
from .digest import build_digest
from .models import Digest
from .notion_writer import RadarNotionWriter
from .sources.rss import RssSource
from .state import SeenStore
from .. import logger as log


def run_radar(
    config: Config,
    radar_cfg: RadarConfig,
    seen: SeenStore,
    *,
    dry_run: bool,
    limit: int | None,
    when: date,
    scorer=None,
    notion_writer=None,
    slack_post=None,
) -> Digest:
    """radar パイプラインを実行して Digest を返す"""
    # 1. 全フィード取得（1 件失敗しても継続）
    all_items = []
    for spec in radar_cfg.feeds:
        try:
            all_items.extend(RssSource(spec).fetch(limit))
        except Exception as e:
            log.warn(f"フィード取得失敗（スキップ）: {spec.name}: {e}")

    # 2. 新着のみ
    new_items = seen.filter_new(all_items)
    log.step(f"新着 {len(new_items)} 件 / 取得 {len(all_items)} 件")
    if not new_items:
        log.success("新着なし。何も出力しません。")
        return Digest()

    # 3. 採点
    scorer = scorer or Curator(config)
    scored = scorer.score(new_items, radar_cfg)

    # 4. 振り分け
    digest = build_digest(scored, radar_cfg.threshold, radar_cfg.max_highlights)

    if dry_run:
        log.step("dry-run: Notion/Slack へは送信しません")
        return digest

    # 5. Notion 蓄積
    writer = notion_writer or RadarNotionWriter(config)
    for s in digest.highlights + digest.others:
        writer.append_item(s, when)

    # 6. Slack プッシュ
    webhook = config.radar_slack_webhook_url or config.slack_webhook_url
    if webhook:
        poster = slack_post
        if poster is None:
            from ..slack import post_digest
            poster = lambda url, d: asyncio.run(post_digest(url, d))
        poster(webhook, digest)

    # 7. 既読化
    seen.mark_seen(new_items)
    return digest
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/test_radar_pipeline.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: CLI コマンドを追加**

`src/medium_notion/cli.py` に `radar` コマンドを追加する。既存コマンドの近く（他の `@cli.command()` と同じスタイル）に配置:

```python
@cli.command()
@click.option("--dry-run", is_flag=True, help="取得・採点のみ。Slack/Notion へ送らず stdout 表示")
@click.option("--limit", type=int, default=None, help="フィード当たりの取得上限")
def radar(dry_run, limit):
    """RSS フィードを巡回し、採点ダイジェストを Slack + Notion に出力する"""
    from datetime import date as _date
    from .radar.config import load_radar_config
    from .radar.state import SeenStore
    from .radar.pipeline import run_radar
    from .radar.digest import render_slack_text

    try:
        config = load_config()
        radar_cfg = load_radar_config()
        seen = SeenStore("radar-seen.json")
        digest = run_radar(
            config, radar_cfg, seen,
            dry_run=dry_run, limit=limit, when=_date.today(),
        )
        if digest.is_empty:
            console.print("[yellow]新着なし[/yellow]")
            return
        console.print(render_slack_text(digest))
        if not dry_run:
            console.print(
                f"\n[green]✓ Notion {len(digest.highlights) + len(digest.others)}件 / "
                f"Slack 投稿完了[/green]"
            )
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise SystemExit(1)
```

> `console` と `load_config` は cli.py 内で既に定義/import 済みのものを使う（既存コマンドと同じ）。実装時に既存の import とヘルパ名を確認して合わせること。

- [ ] **Step 6: 設定ファイルのひな形を作る**

`feeds.yml`（リポジトリルート、spec §3.1 の URL）:

```yaml
- {name: "Anthropic News",         url: "https://www.anthropic.com/news/rss.xml",   layer: "一次情報"}
- {name: "OpenAI Blog",            url: "https://openai.com/blog/rss.xml",          layer: "一次情報"}
- {name: "Cloudflare Blog",        url: "https://blog.cloudflare.com/rss/",         layer: "一次情報"}
- {name: "Netflix TechBlog",       url: "https://netflixtechblog.com/feed",         layer: "一次情報"}
- {name: "Stripe Blog",            url: "https://stripe.com/blog/feed.rss",         layer: "一次情報"}
- {name: "The Pragmatic Engineer", url: "https://blog.pragmaticengineer.com/rss/",  layer: "Substack"}
- {name: "Latent Space",           url: "https://www.latent.space/feed",            layer: "Substack"}
- {name: "a16z",                   url: "https://a16z.com/feed/",                   layer: "VC"}
- {name: "Y Combinator Blog",      url: "https://www.ycombinator.com/blog/rss",     layer: "VC"}
```

`interests.yml`（リポジトリルート、spec §3.2）:

```yaml
threshold: 7
max_highlights: 8
profile:
  - "AI 時代の EM / engineering manager layer の設計"
  - "組織の AI 導入と、それに伴う構造変化"
  - "CTO・執行役員・事業責任者の視点"
  - "本業（垂直）× 副業（水平）のキャリア設計"
  - "AI が壊す/生む職種、どこに金が流れているか"
```

`.env.example` に追記:

```
# --- radar (RSS ダイジェスト) ---
RADAR_NOTION_DATABASE_ID=
RADAR_SLACK_WEBHOOK_URL=
```

- [ ] **Step 7: フィード URL の到達性を検証**

Run（手動・ネットワーク確認、CI ではスキップ）:

```bash
python -c "import feedparser, yaml; [print(f['name'], len(feedparser.parse(f['url']).entries)) for f in yaml.safe_load(open('feeds.yml'))]"
```

Expected: 各フィードで entries 数が 1 以上。0 や例外のものは URL を修正。

- [ ] **Step 8: 全テストを通す**

Run: `pytest -q`
Expected: 既存テスト + radar テスト全て PASS

- [ ] **Step 9: コミット**

```bash
git add src/medium_notion/radar/pipeline.py src/medium_notion/cli.py feeds.yml interests.yml .env.example tests/test_radar_pipeline.py
git commit -m "feat(radar): add pipeline orchestrator and radar CLI command"
```

---

### Task 10: ドキュメント整合

**Files:**
- Modify: `CLAUDE.md`（よく使うコマンドに `radar` 追記、キーファイルに `radar/` 追記）
- Modify: `README.md`（radar の使い方セクション追加）
- Modify: `SPEC.md`（radar パイプラインの章を追加 or 設計書へのリンク）

**Interfaces:** なし（ドキュメントのみ）

- [ ] **Step 1: CLAUDE.md 更新**

「よく使うコマンド」に追加:

```bash
# Tech Radar（RSS ダイジェスト）
medium-notion radar            # 取得→採点→Slack+Notion
medium-notion radar --dry-run  # 送信せず stdout 確認
```

「キーファイル」に追加:

```
├── radar/              # RSS ダイジェスト（取得→採点→Slack+Notion）
│   ├── pipeline.py     # オーケストレーション
│   ├── curator.py      # Claude 採点
│   ├── digest.py       # 振り分け & Slack レンダラ
│   ├── sources/rss.py  # RSS/Atom アダプタ
│   ├── notion_writer.py# Tech Radar DB 書き込み
│   └── state.py        # 既読ストア
```

- [ ] **Step 2: README.md に radar セクション追加**

セットアップ（Tech Radar DB を Notion に作成し Integration 接続、`RADAR_NOTION_DATABASE_ID` を設定）と
`medium-notion radar` / `--dry-run` の使い方、`feeds.yml` / `interests.yml` の編集方法を記載する。

- [ ] **Step 3: SPEC.md に章追加 or リンク**

設計書 `docs/superpowers/specs/2026-06-19-radar-rss-digest-design.md` への参照を「詳細ドキュメント」節に追加。

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md README.md SPEC.md
git commit -m "docs(radar): document radar command and architecture"
```

---

## Self-Review

**Spec coverage:**
- §2.2 モジュール構成 → Task 1–9 で全モジュール作成 ✅
- §3 設定ファイル → Task 1（ローダ）+ Task 9（ひな形）✅
- §4 Curator → Task 5 ✅
- §5 出力（Slack/Notion）→ Task 6（Slack レンダラ）, Task 7（Notion）, Task 8（Slack 投稿）✅
- §6 CLI → Task 9 ✅
- §7 エラーハンドリング → Task 9（feed 失敗継続）, Task 7（Notion 失敗継続）, Task 5（Claude 失敗フォールバック）, Task 8（Slack 失敗ログのみ）✅
- §8 テスト方針 → 各 Task に TDD ステップ ✅
- §10 スコープ外 → X/Podcast/GitHub/Reddit は未実装（`Source` プロトコルで将来差込）✅

**Type consistency:**
- `FeedItem.key`, `ScoredItem.item/score/jp_title/summary/why`, `Digest.highlights/others/is_empty` を Task 2 で定義し Task 3–9 で一貫使用 ✅
- `RssSource.fetch(limit)` のシグネチャを Task 4 定義・Task 9 で使用一致 ✅
- `Config.radar_notion_database_id_formatted` を Task 7 定義・Task 7 writer で使用 ✅
- `build_digest(scored, threshold, max_highlights)` を Task 6 定義・Task 9 で使用一致 ✅

**Placeholder scan:** 各ステップに実コード記載済み。TODO/TBD なし ✅

**注意（実装時に確認）:** Task 9 の CLI は cli.py 既存の `console` / `load_config` / コマンド登録スタイルに合わせること。Task 8 の import は循環回避のため `slack.py → radar.digest` の一方向に保つこと。
