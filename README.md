# Medium → Notion 翻訳パイプライン

Medium の英語技術記事を日本語に翻訳し、構造化された要約とともに Notion データベースに自動追加する CLI ツール。

## 特徴

- Medium 有料記事の全文取得（Playwright + セッション管理）
- Claude Code CLI による高品質な日英翻訳（見出し・コード・リスト等の構造を保持）
- EM 向け構造化要約（概要 / 学び / 活用方法 / 他記事との関連）
- カテゴリの自動分類とタイトルの日英併記
- Notion ページに目次・要約コールアウト・翻訳本文・元記事リンクを自動構成

## アーキテクチャ

```
Medium 記事 URL
    ↓  Playwright（ブラウザ自動化 + セッション認証）
記事の英語テキスト取得（DOM ツリーウォーカーでマークダウン変換）
    ↓  Claude Code CLI（2ステップ方式）
    ↓    Step 1: 本文翻訳（マークダウン出力）
    ↓    Step 2: タイトル翻訳 + カテゴリ + 構造化要約（JSON 出力）
    ↓  Notion API
Notion DB に新規ページ作成（目次 → 要約 → 翻訳 → 元記事リンク）
    ↓
article-index.json に記事を追加（次回の「他記事との関連」分析用）
```

## 前提条件

- Python 3.10+
- Node.js 18+（Claude Code CLI のインストールに必要）
- Claude Code CLI（Max プラン）
- Notion インテグレーション API キー
- Medium アカウント（有料会員）

## セットアップ

```bash
# 1. リポジトリをクローン
git clone <repo-url> medium-notion-translator
cd medium-notion-translator

# 2. Python 環境を構築
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium

# 3. Claude Code CLI をインストール
npm install -g @anthropic-ai/claude-code
claude login

# 4. セットアップウィザード（.env 作成 + 接続テスト）
medium-notion setup

# 5. Medium にログイン（ブラウザが開く）
medium-notion login

# 6. 接続テスト
medium-notion test
```

## 使い方

### 記事を翻訳して Notion に追加

```bash
medium-notion translate -u 'https://medium.com/@author/article-slug-abc123'
```

オプション:

```bash
# スコアを付ける（1-10）
medium-notion translate -u '...' -s 8

# ブラウザを表示して実行（デバッグ時）
medium-notion translate -u '...' --gui
```

### その他のコマンド

```bash
# 記事インデックスを Notion DB から再構築
medium-notion index

# Medium に再ログイン（セッション期限切れ時）
medium-notion login

# 設定と接続の状態チェック
medium-notion test

# 全体のヘルプ
medium-notion -h
```

## Notion DB のプロパティ

対象の Notion データベースに以下のプロパティを作成してください。

| プロパティ | 型 | 内容 |
|-----------|------|------|
| 名前 | Title | 日英併記タイトル（自動） |
| URL | URL | 元の Medium 記事 URL（自動） |
| Categories | Multi-select | AI, LLM, Web3 等のカテゴリ（自動） |
| Score | Number | 記事のスコア 1-10（`-s` で手動指定） |
| read date | Date | 翻訳実行日（自動） |

## Notion ページの構成

生成されるページは以下の構成で作成されます。

```
📑 目次（見出しから自動生成）
──────────
## 要約
  📖 概要          ← コールアウトブロック
  💡 学び・新規性
  🛠 活用方法
  🔗 他の記事との関連
──────────
## 翻訳
  （本文：見出し・段落・コード・リスト・引用等）
──────────
🔖 元記事リンク（bookmark）
```

## 設定 (.env)

```env
NOTION_API_KEY=ntn_xxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
HEADLESS=false
LOG_LEVEL=INFO
CLAUDE_MODEL=sonnet
```

## 仕様書

設計意図や詳細な技術仕様は [SPEC.md](./SPEC.md) を参照してください。

## ライセンス

MIT
