# medium-notion-translator 仕様書

> **バージョン**: 0.1.0
> **最終更新**: 2025-02-12
> **作成者**: Akira Fujita
> **対象読者**: 開発者（将来の自分を含む）、AI エージェント

---

## 1. プロダクト概要

### 1.1 何をするツールか

Medium の英語技術記事を日本語に翻訳し、Notion データベースに構造化されたページとして自動登録する CLI ツール。
Engineering Manager が技術ナレッジを効率的に蓄積・活用するためのパイプラインとして設計されている。

### 1.2 解決する課題

- Medium の英語記事を読むコストが高い
- 読んだ記事のナレッジが散逸して再利用できない
- 記事同士の関連性が見えず、体系的な学びにつながらない

### 1.3 対象ユーザー

Engineering Manager（EM）。Web3 に限らず、技術記事全般を対象とする。
EM としてのナレッジ蓄積が主目的であり、特定プロダクト（TOKI 等）に依存しない汎用ツール。

---

## 2. アーキテクチャ

### 2.1 全体構成

```
┌──────────┐     ┌───────────┐     ┌────────────┐     ┌──────────┐
│  Medium  │────▶│  browser  │────▶│ translator │────▶│  Notion  │
│ (記事)   │     │(Playwright)│     │(Claude CLI)│     │  (API)   │
└──────────┘     └───────────┘     └────────────┘     └──────────┘
                       │                  │                  │
                       ▼                  ▼                  ▼
                 medium-session     article-index       Notion DB
                    .json              .json            (ページ)
```

### 2.2 パイプラインの流れ

```
1. 設定読み込み (.env)
2. Claude Code CLI の存在確認
3. Notion DB への接続確認
4. Playwright で Medium 記事を取得（セッション必須）
5. 既存記事インデックス読み込み (article-index.json)
6. Claude Code CLI で翻訳（2ステップ）
   Step 1: 本文の日本語翻訳（マークダウン出力）
   Step 2: メタデータ抽出（JSON 出力）
           - 日本語タイトル
           - カテゴリ分類
           - 構造化要約（4観点）
7. Notion DB にページ作成
8. インデックスに新記事を追加・保存
9. 結果表示
```

### 2.3 ファイル構成

```
medium-notion-translator/
├── pyproject.toml              # プロジェクト定義・依存関係
├── .env                        # 環境変数（API キー等）
├── .env.example                # .env のテンプレート
├── .gitignore
├── medium-session.json         # Playwright セッション（自動生成）
├── article-index.json          # 既存記事インデックス（自動生成）
├── src/
│   └── medium_notion/
│       ├── __init__.py
│       ├── cli.py              # CLI エントリポイント（Click）
│       ├── browser.py          # Medium 記事取得（Playwright）
│       ├── translator.py       # 翻訳エンジン（Claude Code CLI）
│       ├── notion_client.py    # Notion ページ作成（Notion API）
│       ├── config.py           # 設定管理（Pydantic + dotenv）
│       ├── models.py           # データモデル定義
│       ├── slack.py            # Slack 通知（Incoming Webhook）
│       └── logger.py           # ロガー（loguru）
└── tests/
```

---

## 3. モジュール詳細

### 3.1 cli.py — CLI エントリポイント

**フレームワーク**: Click

**コマンド一覧**:

| コマンド | 説明 | 主なオプション |
|---------|------|--------------|
| `translate` | 記事を翻訳して Notion に追加 | `-u URL`（必須）, `-s SCORE`（1-10）, `--headless/--gui` |
| `batch` | URL リストから一括翻訳 | `-f FILE`（必須）, `-s SCORE`, `-i INTERVAL`（デフォルト30秒）, `--headless/--gui` |
| `bookmark` | リストの URL をファイルに出力 | `-l LIST_NAME`（デフォルト `Reading list`）, `-o OUTPUT`（デフォルト `bookmarks.txt`）, `--clean`（処理済み記事をリストから削除）, `--run`（エクスポート→翻訳→削除を一括実行）, `-s SCORE`（--run 時のスコア）, `-i INTERVAL`（--run 時の待機秒、デフォルト30）, `--headless/--gui` |
| `login` | Medium にブラウザでログイン | なし（常に GUI モード） |
| `index` | Notion DB から記事インデックスを構築 | なし |
| `setup` | 対話型セットアップウィザード | なし |
| `test` | 設定と接続の状態チェック | なし |

**設計方針**:
- 全コマンドで `-h` / `--help` を使用可能（`CONTEXT_SETTINGS`）
- `medium-notion -h` でプログラム全体の使い方を表示
- エラーは `RuntimeError` を catch して `rich` で整形表示（スタックトレースを出さない）
- 結果は `rich` の Panel / Table で見やすく表示

**translate コマンドの処理フロー**:
1. 設定読み込み → 2. Claude CLI 確認 → 3. Notion 接続確認 → 4. 記事取得 → 5. インデックス読み込み → 6. 翻訳 → 7. Notion 登録 → 8. インデックス更新 → 9. 結果表示

**batch コマンドの処理フロー**:
1. URL ファイル読み込み・パース（`#` コメント・空行を除外）
2. 設定読み込み（1回） → 3. Claude CLI 確認（1回） → 4. Notion 接続確認（1回）
5. 既存インデックス読み込み（1回）→ 処理済み URL を set 化
6. ブラウザ初期化（1回 — 全記事で共有）
7. 記事ごとのループ:
   - 処理済みチェック → スキップ or 取得 → 翻訳 → Notion 登録 → メモリ上でインデックス追加
   - エラー時はログに記録してスキップ、次の記事へ
   - 最後の記事以外はインターバル待機（デフォルト30秒）
8. ブラウザ終了 → インデックス一括保存 → バッチ結果サマリー表示

**bookmark コマンドの処理フロー**:
1. 設定読み込み（1回）
2. 既存記事と照合（ローカルインデックス + Notion DB）
3. ブラウザ初期化
4. リストページへの遷移:
   - `Reading list` の場合: `/me/list/reading-list` に直接アクセス
   - カスタムリストの場合: `/me/lists`（ライブラリ）にアクセス → リスト名を検索 → クリックして遷移
5. `browser.fetch_reading_list()` で URL 一覧取得
   - 無限スクロールで全記事を読み込み
   - JavaScript で DOM から記事 URL パターンにマッチするリンクを抽出
   - フォールバック: 厳密パターンで0件 → 緩い条件で再試行
6. テキストファイルに出力（未処理 URL は通常行、処理済みは `#` コメントアウト）
7. 結果サマリー表示
8. `--clean` オプション指定時: 処理済み記事をリストから自動削除
   - `browser.remove_articles_from_list()` で記事カードのブックマークボタン → リストピッカーでチェック解除
   - 記事ごとにリストページを再読み込みして DOM を最新化
   - 成功・失敗件数を表示

**`--run` オプション指定時の処理フロー**（エクスポート→翻訳→削除を一括実行）:
1. 設定読み込み（1回） → Claude CLI 確認 → Notion 接続確認 + 既存 URL 取得
2. ブラウザ初期化（1回 — 全フェーズで共有）
3. **Phase 1: エクスポート** — 通常の bookmark と同じ URL 取得・ファイル出力
4. **Phase 2: 翻訳** — 未処理 URL を batch と同じロジックで翻訳 → Notion 登録
   - `browser.fetch_article()` → `translator.translate_article()` → `notion.create_page()`
   - 記事間に `--interval` 秒の待機
   - 翻訳失敗した記事はリストに残る（削除しない）
5. **Phase 3: リスト削除** — 処理済み（既存 + 今回翻訳分）をリストから削除
   - `browser.remove_articles_from_list()` で一括削除
6. ブラウザ終了 → インデックス保存 → 最終サマリー表示
7. **Slack 通知**（`SLACK_WEBHOOK_URL` 設定時のみ）
   - 翻訳した記事のサマリーと Notion ページ URL を Incoming Webhook で送信
   - 送信失敗時はログ出力のみ（メインフローに影響しない）

出力ファイル形式（`batch -f` にそのまま渡せる）:
```text
# Medium「toNotion」(2025-02-12 取得, 8件)
# 処理済みの記事は batch 実行時に自動スキップされます
https://medium.com/@user/article-1-abc123
https://medium.com/@user/article-2-def456
# https://medium.com/@user/article-3-ghi789  (処理済み)
```

**インデックス管理**:
- `_load_article_index()`: `article-index.json` から既存記事一覧を読み込む
- `_append_to_index()`: 翻訳完了後に新記事を追加（URL ベースで重複チェック）
- `index` コマンド: Notion DB から全記事を取得してインデックスを再構築

### 3.2 browser.py — Medium 記事取得

**技術**: Playwright（Chromium、非同期 API）

**クラス**: `BrowserClient`

**セッション管理**:
- ログインセッションは `medium-session.json` に保存
- `login` コマンドで GUI ブラウザを開いて手動ログイン → セッション保存
- `translate` コマンド実行時はセッションファイルの存在が必須
- セッションがない場合は `RuntimeError` で即座にエラー終了

**記事取得フロー** (`fetch_article`):
1. セッションファイル存在チェック → なければ即 `RuntimeError`
2. 記事ページにアクセス（`domcontentloaded` で待機）
3. HTTP ステータスコードチェック（>= 400 でエラー）
4. JavaScript で 404 / 無効ページ検出
5. 記事コンテナの検出（`ARTICLE_CONTAINER_SELECTORS` を順に試行）
6. ページスクロール（遅延ロードコンテンツのトリガー）
7. タイトル・著者・本文を抽出

**コンテンツ抽出** (`_extract_content`):
- JavaScript の DOM ツリーウォーカーで再帰的に走査
- マークダウン形式に変換しながら抽出
- 対応要素: 見出し（h1-h4）、段落（インライン書式含む）、コードブロック、引用、リスト、画像キャプション
- インライン書式: `**太字**`、`*斜体*`、`` `コード` ``、`[リンク](URL)`
- スキップ: nav, footer, header, button, aside, script, style 等の非コンテンツ要素
- フォールバック: コンテナが見つからない場合は `TreeWalker` で body 全体からテキスト抽出

**コンテナセレクタ**（優先度順）:
```python
["article", "[data-testid='story-content']", ".postArticle-content", "main", "[role='main']"]
```

**ボット検出回避**:
- `navigator.webdriver` を `undefined` に上書き
- カスタム User-Agent 設定
- Chromium 起動時に `--disable-blink-features=AutomationControlled`

**リスト取得フロー** (`fetch_reading_list(list_name)`):
1. セッションファイル存在チェック
2. リストページへの遷移:
   - `Reading list`（デフォルト）: `/me/list/reading-list` に直接アクセス
   - カスタムリスト: `/me/lists` にアクセス → `_navigate_to_custom_list()` でリスト名を DOM から検索 → クリック遷移
3. ログインページへのリダイレクト検出（セッション期限切れの早期検出）
4. 無限スクロール（`scrollHeight` が変化しなくなるまで、最大 50 回）
5. JavaScript で全 `<a>` タグの href を走査し、記事 URL パターンにマッチするものを抽出
6. URL パターン: `/@user/slug-hash`, `/publication/slug-hash`, `/p/hash`
7. ナビ・フッター等の非記事リンクを除外（`/me/`, `/m/`, `/tag/`, `/plans` 等）
8. フォールバック: 厳密パターンで 0 件 → 緩い条件で再試行、それでも 0 件 → デバッグ情報出力

**カスタムリスト遷移** (`_navigate_to_custom_list`):
- ライブラリページの DOM 内で `h2`, `h3`, `a` 等のテキストからリスト名を検索
- 見つかったらクリック可能な親要素（`<a>` タグ等）を探して遷移
- 見つからない場合は利用可能なリスト名をエラーメッセージに含めて表示

**リスト記事削除** (`remove_articles_from_list(list_name, urls_to_remove)`):
- 記事ごとにリストページへ再遷移（`_navigate_to_list_page`）して DOM を最新化
- 無限スクロール（`_scroll_to_load_all`）で全記事を読み込み
- 指定 URL ごとに `_remove_single_article()` を実行
- 戻り値: `(成功した URL リスト, 失敗した URL リスト)`

**単一記事削除** (`_remove_single_article(url)`):
ブックマークボタン方式で記事をリストから削除する。
1. URL のパス部分で DOM 内の `<a>` リンクを照合
2. マッチしたリンクの親コンテナを遡り、記事カードを特定
3. カードをビューポート中央にスクロール（`scrollIntoView`）
4. カード内のブックマークボタンを検出（`aria-label` に "bookmark" / "save" / "list" を含む `<button>`）
5. ブックマークボタンを座標クリック → リストピッカーポップアップが開く
6. ピッカー内のオーバーレイからリスト名（例: "toNotion"）を含む行を検出してクリック（チェック解除）
7. Escape キーでピッカーを閉じる
8. ボタンやリスト名が見つからない場合はデバッグ情報をログ出力して失敗扱い

**404 検出ロジック**:
- `document.title === 'Medium'`
- `bodyText` に "page not found", "404", "this page doesn't" 等を含む
- ただし記事構造（`article`, `h1` 等）がある場合は除外

### 3.3 translator.py — 翻訳エンジン

**技術**: Claude Code CLI（`claude -p --output-format text`）をサブプロセスとして呼び出し

**クラス**: `TranslationService`

**2ステップ方式**:

| ステップ | 目的 | 入力 | 出力形式 |
|---------|------|------|---------|
| Step 1 | 本文翻訳 | 記事全文 | プレーンテキスト（マークダウン） |
| Step 2 | メタデータ抽出 | 記事先頭 3000 文字 + 既存記事一覧 | JSON |

**Step 1: 翻訳プロンプト** (`TRANSLATE_PROMPT`):
- ロール: 技術記事の翻訳者
- ルール: 自然な日本語、技術用語は英語/カタカナ維持、コードブロック維持、マークダウン形式
- 長い記事（> 15,000 文字）はチャンク分割して翻訳

**Step 2: メタデータプロンプト** (`METADATA_PROMPT`):
- ロール: Engineering Manager 向けのナレッジキュレーター
- 出力 JSON 構造:
  ```json
  {
    "japanese_title": "日本語タイトル",
    "categories": ["カテゴリ1", "カテゴリ2"],
    "summary": {
      "overview": "記事全体の要旨（2〜3文）",
      "learnings": "学べる新しい知見（2〜3点）",
      "use_cases": "EM・チームでの実務活用方法（2〜3点）",
      "connections": "過去記事との関連性・組み合わせアイデア"
    }
  }
  ```

**構造化要約の4観点**:

| 観点 | 絵文字 | 内容 |
|------|-------|------|
| 概要 | 📖 | 何についての記事で、結論は何か |
| 学び・新規性 | 💡 | EM として知るべき新しい知見（既知の一般論は除外） |
| 活用方法 | 🛠 | チーム展開、1on1、意思決定での活用法 |
| 他の記事との関連 | 🔗 | 既存記事と組み合わせた価値創出の提案 |

**カテゴリ選択肢**:
```
Web3, DeFi, Blockchain, Cross-chain, Bridge, Smart Contract,
Layer2, NFT, DAO, Security, Development, AI, ML, LLM,
DevOps, DevTools, Programming, Cloud, Infrastructure,
Frontend, Backend, Mobile, Data, Design, Career, Other
```

**タイトル形式**: `日本語タイトル | English Title`（日英併記）

**JSON パース**:
- ```` ```json ``` ```` ブロックからの抽出を優先
- フォールバック: トップレベルの `{ }` を深さカウントで探索
- パース失敗時も翻訳結果（Step 1）は保持

**Claude CLI 呼び出し**:
- コマンド: `claude -p --output-format text`
- プロンプトは `stdin` 経由で渡す
- タイムアウト: 600 秒（10 分）

### 3.4 notion_client.py — Notion ページ作成

**技術**: notion-client（公式 Python SDK）

**クラス**: `NotionClient`

**Notion DB プロパティ**:

| プロパティ名 | 型 | 内容 |
|------------|------|------|
| `名前` | title | 日英併記タイトル |
| `URL` | url | 元記事の URL |
| `read date` | date | 翻訳実行日 |
| `Categories` | multi_select | 自動分類カテゴリ |
| `Score` | number | ユーザー指定スコア（1-10、任意） |

**ページ本文の構造**:

```
┌─────────────────────────────────────┐
│ 📑 目次（table_of_contents）         │  ← 先頭
├─────────────────────────────────────┤
│ ── 区切り線 ──                       │
├─────────────────────────────────────┤
│ ## 要約                              │
│   ### 📖 概要                        │
│   ┌ callout (📖) ──────────────┐    │
│   │ 記事の要旨...               │    │
│   └────────────────────────────┘    │
│   ### 💡 学び・新規性                 │
│   ┌ callout (💡) ──────────────┐    │
│   │ 新しい知見...               │    │
│   └────────────────────────────┘    │
│   ### 🛠 活用方法                     │
│   ┌ callout (🛠) ──────────────┐    │
│   │ 活用の提案...               │    │
│   └────────────────────────────┘    │
│   ### 🔗 他の記事との関連              │
│   ┌ callout (🔗) ──────────────┐    │
│   │ 関連記事の提案...            │    │
│   └────────────────────────────┘    │
├─────────────────────────────────────┤
│ ── 区切り線 ──                       │
├─────────────────────────────────────┤
│ ## 翻訳                              │
│ （翻訳本文：見出し・段落・コード・     │
│   リスト・引用・画像キャプション等）    │
├─────────────────────────────────────┤
│ ── 区切り線 ──                       │
│ 🔖 元記事 bookmark                   │
└─────────────────────────────────────┘
```

**対応する Notion ブロックタイプ**:

| マークダウン要素 | Notion ブロック | 備考 |
|----------------|---------------|------|
| `# 見出し` | `heading_1` / `heading_2` / `heading_3` | 目次に自動反映 |
| 通常段落 | `paragraph`（`rich_text` + インライン書式） | |
| `` ``` コード ``` `` | `code` | 言語指定対応 |
| `> 引用` | `quote` | |
| `- 箇条書き` | `bulleted_list_item` | |
| `1. 番号リスト` | `numbered_list_item` | |
| `[画像: ...]` | `paragraph`（italic） | |
| 区切り | `divider` | |
| 元記事リンク | `bookmark` | |
| 目次 | `table_of_contents` | ページ先頭 |
| 要約セクション | `callout`（絵文字アイコン付き） | |

**インライン書式パーサー** (`_parse_inline_markdown`):
- 正規表現で `**太字**`、`*斜体*`、`` `コード` ``、`[テキスト](URL)` を検出
- Notion `rich_text` の `annotations`（bold, italic, code）と `link` に変換
- プレーンテキスト部分もそのまま `rich_text` オブジェクトとして出力

**API 制限への対応**:
- テキストブロック最大 2000 文字（`MAX_BLOCK_TEXT_LENGTH`）
- 超過時は句点（。）またはピリオド（. ）で分割

**既存記事一覧取得** (`list_articles`):
- Notion DB をページネーション（100件ずつ）で全件取得
- `read date` の降順でソート
- タイトルとカテゴリを返す

### 3.5 config.py — 設定管理

**技術**: Pydantic BaseModel + python-dotenv

**環境変数**:

| 変数名 | 必須 | 説明 | デフォルト |
|--------|-----|------|-----------|
| `NOTION_API_KEY` | ○ | Notion Integration の API キー | - |
| `NOTION_DATABASE_ID` | ○ | Notion データベースの ID | - |
| `HEADLESS` | × | ブラウザを非表示で実行 | `false` |
| `LOG_LEVEL` | × | ログレベル | `INFO` |
| `CLAUDE_MODEL` | × | Claude のモデル名 | `sonnet` |
| `SLACK_WEBHOOK_URL` | × | Slack Incoming Webhook URL（--run 完了時に通知） | - |

**自動生成ファイル**:
- `session_path`: `medium-session.json`（Playwright セッション）
- `index_path`: `article-index.json`（記事インデックス）

**バリデーション**:
- `NOTION_API_KEY`: 空文字・プレースホルダ（`ntn_your`）を拒否
- `NOTION_DATABASE_ID`: 空文字・プレースホルダ（`your_`）を拒否、ハイフン自動除去
- Database ID は API 呼び出し時にハイフン付き UUID 形式に自動変換

### 3.6 models.py — データモデル

**MediumArticle**（取得した記事）:
```
url, title, content, author, publish_date, tags, is_preview_only
+ word_count (property), char_count (property)
```

**TranslationResult**（翻訳結果）:
```
original (MediumArticle), japanese_title, japanese_content,
categories, summary
+ notion_title (property)
```

**NotionPage**（作成されたページ）:
```
page_id, title, url, created_at
```

### 3.7 logger.py — ロガー

**技術**: loguru

**ログ関数**:
- `step(message)`: 処理ステップ（▶ マーク）
- `success(message)`: 成功（✓ マーク）
- `warn(message)`: 警告（⚠ マーク）
- `error(message)`: エラー（✗ マーク）

---

## 4. 外部依存関係

### 4.1 Python パッケージ

| パッケージ | バージョン | 用途 |
|-----------|-----------|------|
| click | >= 8.0 | CLI フレームワーク |
| python-dotenv | >= 1.0 | .env ファイル読み込み |
| playwright | >= 1.40 | ブラウザ自動化 |
| notion-client | >= 2.0 | Notion API SDK |
| pydantic | >= 2.0 | 設定バリデーション |
| loguru | >= 0.7 | ロギング |
| rich | >= 13.0 | CLI 出力の装飾 |

### 4.2 外部サービス

| サービス | 用途 | 認証方法 |
|---------|------|---------|
| Medium | 記事取得元 | Playwright セッション（手動ログイン） |
| Claude Code CLI | 翻訳エンジン | Max プラン（`claude login`） |
| Notion API | 記事保存先 | Integration API キー |

### 4.3 システム要件

- Python >= 3.10
- Node.js（Claude Code CLI のインストールに必要）
- Chromium（Playwright が自動インストール）

---

## 5. データフロー

### 5.1 article-index.json の構造

`translate` コマンドと `index` コマンドでは保存する構造が異なる。

**translate コマンド実行時**（url を含む）:
```json
[
  {
    "title": "日本語タイトル | English Title",
    "categories": ["AI", "LLM"],
    "url": "https://medium.com/..."
  }
]
```

**index コマンド実行時**（Notion DB から再構築、url を含まない）:
```json
[
  {
    "title": "日本語タイトル | English Title",
    "categories": ["AI", "LLM"]
  }
]
```

**ライフサイクル**:
- `medium-notion index`: Notion DB から全件取得して再構築（タイトルとカテゴリのみ）
- `medium-notion translate`: 翻訳完了後に自動追加（url 込み、URL ベースで重複チェック）
- 翻訳時に Step 2 のプロンプトに渡され「他の記事との関連」分析に使用
- 最大 50 件がプロンプトに含まれる

### 5.2 medium-session.json

Playwright の `storage_state` をそのまま JSON 保存。
Cookie やローカルストレージの情報を含む。

---

## 6. エラーハンドリング方針

### 6.1 早期バリデーション（翻訳前に検出）

| チェック | タイミング | エラー |
|---------|----------|--------|
| セッションファイル未存在 | 記事取得前 | `RuntimeError` |
| HTTP ステータス >= 400 | ページアクセス直後 | `RuntimeError` |
| 404 / 無効ページ検出 | DOM 読み込み後 | `RuntimeError` |
| コンテンツ抽出失敗 | DOM 走査後 | `RuntimeError`（フォールバック後） |

### 6.2 設計原則

- **無効なページで Claude を呼ばない**: HTTP ステータスと DOM チェックで事前に検出
- **スタックトレースを見せない**: `RuntimeError` を CLI 層で catch して整形表示
- **翻訳結果は捨てない**: Step 2（メタデータ）が失敗しても Step 1（翻訳本文）は保持
- **セッション期限切れは明示的に伝える**: `login` コマンドの再実行を促す

---

## 7. 設計上の判断とその理由

### 7.1 なぜ 2 ステップ翻訳か

Claude CLI に対して 1 回のプロンプトで「翻訳 + メタデータ抽出」を行うと、JSON の構文エラーや出力形式の混在が頻発した。
本文翻訳（プレーンテキスト出力）と メタデータ抽出（JSON 出力）を分離することで、それぞれの出力品質が安定した。

### 7.2 なぜローカルインデックスか

翻訳のたびに Notion DB を全件クエリすると API コストと待ち時間が大きい。
`article-index.json` にキャッシュすることで、通常の翻訳時はファイル読み込みのみで済む。
完全なリフレッシュが必要な場合は `index` コマンドで再構築する。

### 7.3 なぜセッション必須か

ユーザーは Medium 有料会員であり、読みたい記事はほぼ全て有料記事。
ログイン状態でなければ本文を取得できないため、セッションの存在を前提とし、なければ即座にエラーにする。

### 7.4 なぜ DOM ツリーウォーカーか

Medium の DOM 構造は頻繁に変わる。特定の CSS クラスや data-testid に依存すると壊れやすい。
`article` → `main` → `body` の順でコンテナを探し、その中を再帰的に走査する方式にすることで、DOM 変更への耐性を高めている。

### 7.5 なぜ構造化要約か

単なる「3行要約」では EM としてのナレッジ蓄積に不十分。
「概要 → 学び → 活用 → 関連」の 4 観点で構造化することで、読み返したときの実用性を高めている。

---

## 8. Notion DB スキーマ

翻訳先の Notion データベースには以下のプロパティが必要:

| プロパティ名 | Notion 型 | 設定元 |
|------------|----------|--------|
| `名前` | Title | 自動（日英併記タイトル） |
| `URL` | URL | 自動（元記事 URL） |
| `read date` | Date | 自動（実行日） |
| `Categories` | Multi-select | 自動（AI 分類） |
| `Score` | Number | 手動（`-s` オプション） |

---

## 9. CLI ユーザーフロー

### 9.1 初回セットアップ

```bash
# 1. インストール
pip install -e .
playwright install chromium

# 2. 設定ファイル作成
medium-notion setup

# 3. Medium ログイン（ブラウザが開く）
medium-notion login

# 4. 接続テスト
medium-notion test
```

### 9.2 日常の翻訳作業

```bash
# 1記事を翻訳して Notion に追加
medium-notion translate -u 'https://medium.com/@user/article-abc123'

# スコア付き
medium-notion translate -u 'https://medium.com/@user/article-abc123' -s 8

# ブラウザを表示して実行（デバッグ時）
medium-notion translate -u 'https://medium.com/@user/article-abc123' --gui
```

### 9.3 複数記事の一括翻訳

```bash
# URL リストファイルを作成
cat > urls.txt << 'EOF'
# 今週読みたい記事
https://medium.com/@user/article-1-abc123
https://medium.com/@user/article-2-def456
https://medium.com/@user/article-3-ghi789
EOF

# 一括翻訳（処理済み記事は自動スキップ）
medium-notion batch -f urls.txt

# スコア付き・インターバル60秒
medium-notion batch -f urls.txt -s 7 -i 60
```

### 9.4 ブックマークから一括翻訳

```bash
# カスタムリスト「toNotion」の URL をエクスポート
medium-notion bookmark -l toNotion

# デフォルト（Reading list）の場合
medium-notion bookmark

# 出力ファイルの内容を確認（必要に応じて編集可能）
cat bookmarks.txt

# そのまま一括翻訳に渡す
medium-notion batch -f bookmarks.txt

# 翻訳済み記事をリストから自動削除（リストをクリーンに保つ）
medium-notion bookmark -l toNotion --clean
```

### 9.5 メンテナンス

```bash
# 記事インデックスを Notion DB から再構築
medium-notion index

# セッション期限切れ時の再ログイン
medium-notion login
```

---

## 10. 今後の拡張方針

開発時に以下の方針を守ること:

1. **EM 汎用ツールとして維持**: 特定プロダクト（TOKI 等）に依存する機能を入れない
2. **2 ステップ方式を維持**: 翻訳とメタデータ抽出は分離したまま
3. **早期バリデーション優先**: 無効な入力で Claude を呼ばない
4. **セッション必須を維持**: Medium 有料会員前提
5. **Notion ページの視認性**: 目次 → 要約（4観点） → 本文 → 元記事リンクの構成を維持
6. **ローカルインデックス**: 毎回 Notion DB をクエリしない

---

## 付録 A: 環境変数テンプレート (.env)

```env
NOTION_API_KEY=ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
HEADLESS=false
LOG_LEVEL=INFO
CLAUDE_MODEL=sonnet
```

## 付録 B: 要約プロンプトの観点

| # | 観点 | プロンプト上の指示 |
|---|------|-------------------|
| 1 | 📖 概要 | 「何についての記事で、結論は何か」を簡潔に |
| 2 | 💡 学び・新規性 | EM として知っておくべき新しい知見。既知の一般論は含めない |
| 3 | 🛠 活用方法 | 「チームにどう展開できるか」「1on1 や意思決定でどう活かせるか」 |
| 4 | 🔗 他の記事との関連 | 過去の記事一覧を参照し、組み合わせて価値が生まれる提案 |
