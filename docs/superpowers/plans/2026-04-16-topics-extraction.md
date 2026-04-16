# Topics 自動抽出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 翻訳パイプラインで記事から検索用トピックを自動抽出し、Notion の Topics (multi_select) に登録する

**Architecture:** Step 2 の METADATA_PROMPT を拡張して topics フィールドを JSON 出力に追加。既存 Topics を Notion DB から取得してプロンプトに注入し、表記ゆれを防ぐ。TranslationResult にフィールド追加し、_build_properties で Notion プロパティに変換。

**Tech Stack:** Python 3.10+ / notion-client SDK / Claude Code CLI (subprocess)

---

### Task 1: TranslationResult に topics フィールドを追加

**Files:**
- Modify: `src/medium_notion/models.py:29-37`
- Modify: `tests/conftest.py:39-50`
- Test: `tests/test_models.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
"""データモデルのテスト"""

from medium_notion.models import MediumArticle, TranslationResult


class TestTranslationResult:
    def test_topics_default_empty(self):
        """topics のデフォルトが空リストであること"""
        article = MediumArticle(
            url="https://medium.com/@test/article",
            title="Test Article",
            content="Test content",
        )
        result = TranslationResult(
            original=article,
            japanese_title="テスト記事",
            japanese_content="テスト本文",
        )
        assert result.topics == []

    def test_topics_with_values(self):
        """topics に値を設定できること"""
        article = MediumArticle(
            url="https://medium.com/@test/article",
            title="Test Article",
            content="Test content",
        )
        result = TranslationResult(
            original=article,
            japanese_title="テスト記事",
            japanese_content="テスト本文",
            topics=["Kubernetes", "モジューラーモノリス", "運用負荷"],
        )
        assert result.topics == ["Kubernetes", "モジューラーモノリス", "運用負荷"]
        assert len(result.topics) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `TranslationResult.__init__() got an unexpected keyword argument 'topics'`

- [ ] **Step 3: Write minimal implementation**

In `src/medium_notion/models.py`, add `topics` field to `TranslationResult`:

```python
@dataclass
class TranslationResult:
    """Claude による翻訳結果"""

    original: MediumArticle
    japanese_title: str
    japanese_content: str
    categories: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    summary: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Update conftest fixture**

In `tests/conftest.py`, update `sample_translation` to include topics:

```python
@pytest.fixture
def sample_translation(sample_article):
    return TranslationResult(
        original=sample_article,
        japanese_title="Claude Code の API コストを 40% 削減した方法",
        japanese_content=(
            "この記事では、シンプルなツールを使って API コストを大幅に削減した方法を紹介します。\n\n"
            "重要な発見は、プロンプトキャッシュを効果的に使用することでした。"
        ),
        categories=["AI", "Development"],
        topics=["Claude Code", "プロンプトキャッシュ", "コスト最適化", "API"],
        summary="Claude Code のコスト削減手法。プロンプトキャッシュの活用で40%のコスト削減を実現。",
    )
```

- [ ] **Step 6: Run all tests to verify no regressions**

Run: `pytest -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_models.py src/medium_notion/models.py tests/conftest.py
git commit -m "feat: add topics field to TranslationResult model"
```

---

### Task 2: NotionClient に list_existing_topics() を追加

**Files:**
- Modify: `src/medium_notion/notion_client.py`
- Test: `tests/test_notion_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_notion_client.py`:

```python
class TestListExistingTopics:
    def test_list_existing_topics_returns_unique_topics(self, notion_client):
        """DB 内の Topics を重複排除して返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {
                    "properties": {
                        "Topics": {
                            "multi_select": [
                                {"name": "Kubernetes"},
                                {"name": "モジューラーモノリス"},
                            ]
                        }
                    }
                },
                {
                    "properties": {
                        "Topics": {
                            "multi_select": [
                                {"name": "Kubernetes"},
                                {"name": "運用負荷"},
                            ]
                        }
                    }
                },
            ],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == sorted({"Kubernetes", "モジューラーモノリス", "運用負荷"})
        mock_sdk.data_sources.query.assert_called_once()

    def test_list_existing_topics_empty_db(self, notion_client):
        """DB が空の場合に空リストを返すこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == []

    def test_list_existing_topics_no_topics_property(self, notion_client):
        """Topics プロパティがないページでもエラーにならないこと"""
        mock_sdk = notion_client.client
        mock_sdk.data_sources.query.return_value = {
            "results": [
                {"properties": {"名前": {"title": [{"plain_text": "記事"}]}}},
            ],
            "has_more": False,
            "next_cursor": None,
        }
        topics = notion_client.list_existing_topics()

        assert topics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notion_client.py::TestListExistingTopics -v`
Expected: FAIL — `AttributeError: 'NotionClient' object has no attribute 'list_existing_topics'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/medium_notion/notion_client.py` in class `NotionClient`, after `list_existing_urls`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_notion_client.py::TestListExistingTopics -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/medium_notion/notion_client.py tests/test_notion_client.py
git commit -m "feat: add list_existing_topics to NotionClient"
```

---

### Task 3: _build_properties に Topics multi_select を追加

**Files:**
- Modify: `src/medium_notion/notion_client.py:237-271`
- Test: `tests/test_notion_client.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_notion_client.py` inside `TestNotionClient`:

```python
def test_build_properties_with_topics(self, notion_client, sample_translation):
    """Topics が multi_select として構築されること"""
    props = notion_client._build_properties(sample_translation, score=8)

    assert "Topics" in props
    topics_ms = props["Topics"]["multi_select"]
    assert len(topics_ms) == 4
    assert topics_ms[0]["name"] == "Claude Code"
    assert topics_ms[1]["name"] == "プロンプトキャッシュ"

def test_build_properties_empty_topics(self, notion_client, sample_article):
    """topics が空の場合は Topics プロパティが含まれないこと"""
    result = TranslationResult(
        original=sample_article,
        japanese_title="テスト",
        japanese_content="テスト",
        topics=[],
    )
    props = notion_client._build_properties(result, score=None)

    assert "Topics" not in props
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notion_client.py::TestNotionClient::test_build_properties_with_topics tests/test_notion_client.py::TestNotionClient::test_build_properties_empty_topics -v`
Expected: FAIL — `"Topics" not in props`

- [ ] **Step 3: Write minimal implementation**

In `src/medium_notion/notion_client.py`, update `_build_properties` to add Topics after Categories:

```python
# Topics（multi-select）
if result.topics:
    properties["Topics"] = {
        "multi_select": [
            {"name": topic} for topic in result.topics
        ]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_notion_client.py::TestNotionClient -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/medium_notion/notion_client.py tests/test_notion_client.py
git commit -m "feat: add Topics multi_select to Notion page properties"
```

---

### Task 4: METADATA_PROMPT に topics を追加し _extract_metadata を拡張

**Files:**
- Modify: `src/medium_notion/translator.py:39-84` (METADATA_PROMPT)
- Modify: `src/medium_notion/translator.py:95-139` (translate_article)
- Modify: `src/medium_notion/translator.py:172-211` (_extract_metadata)
- Test: `tests/test_translator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_translator.py`:

```python
class TestExtractMetadata:
    def test_extract_metadata_with_topics(self, mock_config, sample_article):
        """_extract_metadata が topics を含む JSON を正しくパースすること"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト記事",
            "categories": ["AI"],
            "topics": ["Kubernetes", "モジューラーモノリス", "運用負荷"],
            "summary": {
                "overview": "概要テスト",
                "learnings": "学びテスト",
                "use_cases": "活用テスト",
                "connections": "",
            },
        })

        with patch.object(service, "_call_claude", return_value=raw_json):
            title, categories, summary, topics = service._extract_metadata(
                sample_article, [], []
            )

        assert title == "テスト記事"
        assert categories == ["AI"]
        assert topics == ["Kubernetes", "モジューラーモノリス", "運用負荷"]
        assert "概要テスト" in summary

    def test_extract_metadata_without_topics(self, mock_config, sample_article):
        """topics フィールドがない JSON でもエラーにならないこと"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト記事",
            "categories": ["AI"],
            "summary": {
                "overview": "概要テスト",
                "learnings": "",
                "use_cases": "",
                "connections": "",
            },
        })

        with patch.object(service, "_call_claude", return_value=raw_json):
            title, categories, summary, topics = service._extract_metadata(
                sample_article, [], []
            )

        assert topics == []

    def test_extract_metadata_passes_existing_topics(self, mock_config, sample_article):
        """既存 Topics がプロンプトに含まれること"""
        service = TranslationService(mock_config)

        raw_json = json.dumps({
            "japanese_title": "テスト",
            "categories": [],
            "topics": ["Kubernetes"],
            "summary": {"overview": "", "learnings": "", "use_cases": "", "connections": ""},
        })

        existing_topics = ["Kubernetes", "モジューラーモノリス"]

        with patch.object(service, "_call_claude", return_value=raw_json) as mock_claude:
            service._extract_metadata(sample_article, [], existing_topics)
            prompt_text = mock_claude.call_args[0][0]
            assert "Kubernetes" in prompt_text
            assert "モジューラーモノリス" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_translator.py::TestExtractMetadata -v`
Expected: FAIL — signature mismatch or missing topics in return value

- [ ] **Step 3: Update METADATA_PROMPT**

In `src/medium_notion/translator.py`, update `METADATA_PROMPT`:

```python
METADATA_PROMPT = textwrap.dedent("""\
    あなたは Engineering Manager 向けのナレッジキュレーターです。
    以下の技術記事を分析し、JSON で結果を返してください。
    JSON のみを出力し、他のテキストは含めないでください。

    出力形式:
    {{
      "japanese_title": "日本語タイトル",
      "categories": ["カテゴリ1", "カテゴリ2"],
      "topics": ["トピック1", "トピック2", "..."],
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

    topics のルール:
    - 記事の内容から検索用キーワードを 8〜15個 抽出する
    - 技術用語（5〜10個）: フレームワーク、ライブラリ、パターン名、プロトコル等
    - 業務・組織観点のキーワード（2〜5個）: 運用負荷、チーム分割、コスト最適化等
    - 表記ルール:
      - 製品名・プロトコル名・略語は英語のまま（例: Kubernetes, gRPC, ACID, CI/CD）
      - 概念・方法論・業務課題は日本語（例: モジューラーモノリス, 分散トレーシング, 運用負荷）
    - 下記の「既存 Topics 一覧」に同じ概念があれば、既存の表記を優先的に使うこと

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

    既存 Topics 一覧（同じ概念は既存の表記を優先すること）:
    {existing_topics}

    過去に読んだ記事一覧（Notion DB に登録済み）:
    {existing_articles}
""")
```

- [ ] **Step 4: Update _extract_metadata signature and implementation**

In `src/medium_notion/translator.py`, update `_extract_metadata`:

```python
def _extract_metadata(
    self,
    article: MediumArticle,
    existing_articles: list[dict],
    existing_topics: list[str],
) -> tuple[str | None, list[str], str | None, list[str]]:
    """タイトル翻訳・カテゴリ・構造化要約・トピックスを抽出"""
    # 既存記事一覧をフォーマット
    if existing_articles:
        articles_text = "\n".join(
            f"- {a.get('title', '?')} [{', '.join(a.get('categories', []))}]"
            for a in existing_articles[:50]
        )
    else:
        articles_text = "（まだ登録された記事はありません）"

    # 既存 Topics をフォーマット
    if existing_topics:
        topics_text = ", ".join(existing_topics)
    else:
        topics_text = "（まだ登録された Topics はありません）"

    prompt = METADATA_PROMPT.format(
        title=article.title,
        content_preview=article.content[:3000],
        existing_topics=topics_text,
        existing_articles=articles_text,
    )

    try:
        raw = self._call_claude(prompt)
        data = self._parse_json(raw)
        if data:
            japanese_title = data.get("japanese_title", "")
            categories = data.get("categories", [])
            topics = data.get("topics", [])
            summary_data = data.get("summary", {})

            if isinstance(summary_data, dict):
                summary = self._format_structured_summary(summary_data)
            else:
                summary = str(summary_data)

            return japanese_title, categories, summary, topics
    except Exception as e:
        log.warn(f"メタデータ抽出に失敗（翻訳は成功済み）: {e}")

    return None, [], None, []
```

- [ ] **Step 5: Update translate_article to pass existing_topics and set topics**

In `src/medium_notion/translator.py`, update `translate_article`:

```python
def translate_article(
    self,
    article: MediumArticle,
    existing_articles: list[dict] | None = None,
    existing_topics: list[str] | None = None,
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

    # === Step 2: タイトル翻訳・カテゴリ・構造化要約・Topics を抽出 ===
    log.step("[Step 2/2] タイトル翻訳・カテゴリ・要約・Topics を抽出中...")
    japanese_title, categories, summary, topics = self._extract_metadata(
        article, existing_articles or [], existing_topics or []
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
        topics=topics,
        summary=summary,
    )

    log.success(
        f"完了: タイトル=「{display_title}」, カテゴリ={categories}, Topics={len(topics)}件"
    )
    return result
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_translator.py::TestExtractMetadata -v`
Expected: PASS

- [ ] **Step 7: Run all tests to check for regressions**

Run: `pytest -v`
Expected: All PASS (existing translator tests may need updating due to _extract_metadata signature change — see next step)

- [ ] **Step 8: Fix any broken existing tests**

The old `test_parse_translation` tests in `TestTranslationService` reference `_parse_translation` which may not exist in current code. If tests fail, update them to match the current API.

- [ ] **Step 9: Commit**

```bash
git add src/medium_notion/translator.py tests/test_translator.py
git commit -m "feat: add topics extraction to METADATA_PROMPT and _extract_metadata"
```

---

### Task 5: CLI ワイヤリング — Topics を取得・渡し・表示・インデックス保存

**Files:**
- Modify: `src/medium_notion/cli.py`
- Test: Manual verification (CLI integration)

- [ ] **Step 1: Update _translate to fetch and pass existing_topics**

In `src/medium_notion/cli.py`, update `_translate`:

After `existing_articles = _load_article_index(config)` (line 195), add:

```python
# 5.5 既存 Topics の取得
existing_topics = notion.list_existing_topics()
```

Update the translator call:

```python
result = translator.translate_article(
    article,
    existing_articles=existing_articles,
    existing_topics=existing_topics,
)
```

- [ ] **Step 2: Update _show_result to display topics**

```python
def _show_result(result, page):
    """実行結果を表示"""
    console.print()
    console.print("[bold green]✓ 完了[/bold green]")
    console.print()
    console.print(f"  [bold]タイトル[/bold]  {result.japanese_title}")
    console.print(f"  [bold]カテゴリ[/bold]  {', '.join(result.categories) if result.categories else '-'}")
    console.print(f"  [bold]Topics[/bold]   {', '.join(result.topics) if result.topics else '-'}")
    if result.summary:
        summary = result.summary[:120] + "..." if len(result.summary) > 120 else result.summary
        console.print(f"  [bold]要約[/bold]    {summary}")
    console.print()
    console.print(f"  [bold]元記事[/bold]   {result.original.url}")
    console.print(f"  [bold]Notion[/bold]   {page.url}")
    console.print()
```

- [ ] **Step 3: Update _append_to_index to include topics**

```python
def _append_to_index(config: Config, result) -> None:
    """翻訳結果をインデックスに追加して保存"""
    articles = _load_article_index(config)

    existing_urls = {a.get("url") for a in articles}
    if result.original.url not in existing_urls:
        articles.append({
            "title": result.japanese_title,
            "categories": result.categories,
            "topics": result.topics,
            "url": result.original.url,
        })
        config.index_path.write_text(
            json.dumps(articles, ensure_ascii=False, indent=2)
        )
        log.step(f"インデックス更新: {len(articles)} 件")
```

- [ ] **Step 4: Update _batch_translate to fetch and pass existing_topics**

In `_batch_translate`, after `existing_urls |= notion_urls` (line 369), add:

```python
existing_topics = notion.list_existing_topics()
```

Update the translator call inside the loop:

```python
result = translator.translate_article(
    article,
    existing_articles=existing_articles,
    existing_topics=existing_topics,
)
```

Update the in-memory index append to include topics:

```python
existing_articles.append({
    "title": result.japanese_title,
    "categories": result.categories,
    "topics": result.topics,
    "url": url,
})
```

- [ ] **Step 5: Update _bookmark_run to fetch and pass existing_topics**

In `_bookmark_run`, after `existing_urls |= notion.list_existing_urls()` (line 699), add:

```python
existing_topics = notion.list_existing_topics()
```

Update the translator call inside the loop:

```python
result = translator.translate_article(
    article,
    existing_articles=existing_articles,
    existing_topics=existing_topics,
)
```

Update the in-memory index append:

```python
existing_articles.append({
    "title": result.japanese_title,
    "categories": result.categories,
    "topics": result.topics,
    "url": url,
})
```

- [ ] **Step 6: Run all tests**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/medium_notion/cli.py
git commit -m "feat: wire topics through CLI pipeline (translate, batch, bookmark)"
```

---

### Task 6: 全体テスト実行・最終確認

- [ ] **Step 1: Run full test suite**

Run: `pytest -v --tb=short`
Expected: All PASS

- [ ] **Step 2: Verify docs consistency**

Check `README.md` and `SPEC.md` for any mention of Notion properties or translation output format that needs updating.

- [ ] **Step 3: Final commit (docs if updated)**

```bash
git add -A
git commit -m "docs: update specs for Topics property support"
```
