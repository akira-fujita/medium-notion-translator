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
    ↓    Step 2: タイトル翻訳 + カテゴリ + Topics + 構造化要約（JSON 出力）
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

### クイックセットアップ（推奨）

```bash
git clone <repo-url> medium-notion-translator
cd medium-notion-translator
./scripts/setup.sh
```

Python 環境構築 → Playwright → Dock アプリ作成 → .env 設定 → Medium ログインまで一括で実行します。

### 手動セットアップ

```bash
# 1. リポジトリをクローン
git clone <repo-url> medium-notion-translator
cd medium-notion-translator

# 2. Python 環境を構築
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
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

### 複数記事の一括翻訳

```bash
# URL リストファイルから一括翻訳（処理済み記事は自動スキップ）
medium-notion batch -f urls.txt

# スコア付き・インターバル60秒
medium-notion batch -f urls.txt -s 7 -i 60
```

URL ファイルの形式（1行1URL、`#` でコメント）:

```text
# 今週読みたい記事
https://medium.com/@user/article-1-abc123
https://medium.com/@user/article-2-def456
```

### ブックマークから一括翻訳

Medium のリスト（ブックマーク）に保存した記事を一括翻訳できます。
`--run` を使えば、URL エクスポート → 翻訳 → リスト削除を1コマンドで実行できます。

```bash
# ワンコマンドで全自動（エクスポート→翻訳→リスト削除）
medium-notion bookmark -l toNotion --run --gui

# スコア付き・インターバル60秒
medium-notion bookmark -l toNotion --run -s 8 -i 60
```

ステップを分けて実行する場合:

```bash
# 1. カスタムリスト「toNotion」の URL をエクスポート
medium-notion bookmark -l toNotion

# 2. エクスポートした URL リストを一括翻訳
medium-notion batch -f bookmarks.txt

# 3. 翻訳済み記事をリストから自動削除
medium-notion bookmark -l toNotion --clean
```

デフォルトの Reading list を使う場合は `-l` 不要です。

```bash
medium-notion bookmark
```

`--clean` を付けると、Notion DB に登録済みの記事を Medium のリストから自動削除します。
リストを常にクリーンに保ちたい場合に便利です。

### Slack 通知

`--run` の完了後に翻訳結果を Slack に通知できます。`.env` に Webhook URL を設定するだけで有効になります。

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

Slack Incoming Webhook は https://api.slack.com/messaging/webhooks で作成できます。
未設定の場合、通知はスキップされます（他の機能に影響しません）。

通知ルール:

| 状況 | 通知 |
|---|---|
| 新規記事を処理した | ✅ 成功サマリーを送信 |
| 一部記事で失敗があった | ✅ 失敗サマリーを送信 |
| **致命的エラー（セッション切れ・認証失敗・依存ツール不在）** | 🚨 アラート通知を送信 |
| 空振り（リスト空 / 全件処理済み） | 通知しない |

致命的エラー通知は launchd 等での無人実行時に「気づいて手動対応する」ためのシグナル。
内容を見て、必要に応じて `medium-notion login` でセッションを更新してください。

### 日次自動実行（launchd）

毎日決まった時刻にバックグラウンドでヘッドレス実行する設定が用意されています。
朝 7:00 / 昼 13:00 / 夜 22:00 の 3 回スケジュールされており、Mac が起動しているタイミングで処理されます。

セットアップ:

```bash
bash scripts/launchd/install.sh
```

これだけで `~/Library/LaunchAgents/com.akira.medium-bookmark.plist` が配置・ロードされます。

確認・即時実行:

```bash
launchctl list | grep com.akira.medium-bookmark
launchctl start com.akira.medium-bookmark   # 即時実行で動作確認
tail -f logs/launchd-bookmark.log
```

アンインストール:

```bash
launchctl unload ~/Library/LaunchAgents/com.akira.medium-bookmark.plist
rm ~/Library/LaunchAgents/com.akira.medium-bookmark.plist
```

スリープ中の予定時刻に launchd が発火しなかった場合、復帰時に未実行分が実行されます（macOS の `StartCalendarInterval` の期待挙動。バージョンや状況によっては落ちることもあるため、3回スケジュールで冗長化しています）。

完全シャットダウン状態からの自動起動も必要なら、別途以下も設定（充電中のみ動作）:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00
```

多重実行は安全に no-op になる設計です:
- `run-daily.sh` 側で `mkdir` ベースの排他ロック（`logs/.run-daily.lock`）→ 重なった起動は即終了
- 既存 URL は Notion 側 + ローカルインデックスで吸収され二重登録されない
- 空振り（リスト空 / 全件処理済み）はサイレントに終了

### その他のコマンド

```bash
# 記事インデックスを Notion DB から再構築
medium-notion index

# 既存記事に Topics を自動付与（バックフィル）
medium-notion backfill-topics

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
| Topics | Multi-select | 検索用キーワード 8〜15個（自動） |
| Score | Number | 記事のスコア 1-10（`-s` で手動指定） |
| create date | Date | ページ作成日（翻訳実行日、自動） |

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
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

## 仕様書

設計意図や詳細な技術仕様は [SPEC.md](./SPEC.md) を参照してください。

## ライセンス

MIT
