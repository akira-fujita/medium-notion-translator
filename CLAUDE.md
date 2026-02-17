# medium-notion-translator

Medium の英語技術記事を日本語翻訳し、構造化要約とともに Notion DB に自動登録する CLI ツール。
EM のナレッジ蓄積パイプライン。

## 技術スタック

- **言語**: Python 3.10+
- **CLI**: Click + Rich
- **ブラウザ**: Playwright（Medium 記事取得）
- **翻訳**: Claude Code CLI（サブプロセス呼び出し）
- **保存先**: Notion API（notion-client SDK）
- **設定**: Pydantic + python-dotenv

## クリティカルルール

1. `.env` / `medium-session.json` を絶対にコミットしない
2. 2ステップ翻訳方式を維持（Step1: 本文→マークダウン, Step2: メタデータ→JSON）
3. 早期バリデーション: 無効ページで Claude CLI を呼ばない
4. セッション必須: `medium-session.json` がなければ即 `RuntimeError`
5. Notion ページ構成を維持: 目次 → 要約（4観点） → 翻訳本文 → 元記事リンク

## よく使うコマンド

```bash
# 翻訳
medium-notion translate -u 'URL' -s 8
medium-notion bookmark -l toNotion --run --gui

# バッチ
medium-notion batch -f urls.txt -s 7 -i 60

# メンテナンス
medium-notion login          # Medium 再ログイン
medium-notion test           # 接続テスト
medium-notion index          # 記事インデックス再構築

# 開発
pip install -e .             # ローカルインストール
pytest                       # テスト実行
playwright install chromium  # ブラウザ更新
```

## キーファイル

```
src/medium_notion/
├── cli.py              # CLI エントリポイント（Click）
├── browser.py          # Medium 記事取得（Playwright）
├── translator.py       # 翻訳エンジン（Claude CLI 呼び出し）
├── notion_client.py    # Notion ページ作成
├── config.py           # 設定管理（Pydantic + .env）
├── models.py           # データモデル（MediumArticle, TranslationResult, NotionPage）
├── slack.py            # Slack 通知（Incoming Webhook）
└── logger.py           # ロガー（loguru）
```

## 設定（.env）

```
NOTION_API_KEY, NOTION_DATABASE_ID（必須）
HEADLESS, LOG_LEVEL, CLAUDE_MODEL, SLACK_WEBHOOK_URL（任意）
```

## 詳細ドキュメント

- **設計仕様・全モジュール詳細**: `SPEC.md`
- **セットアップ・使い方**: `README.md`
