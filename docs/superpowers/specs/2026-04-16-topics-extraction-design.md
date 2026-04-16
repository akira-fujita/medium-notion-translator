# Topics 自動抽出 — 設計仕様

## 概要

翻訳パイプラインの Step 2（METADATA_PROMPT）を拡張し、記事本文から検索用トピックを抽出して Notion の `Topics` (multi_select) に自動登録する。

## 決定事項

| 項目 | 決定 |
|------|------|
| スコープ | Topics のみ（Status / Last reviewed 等は対象外） |
| 言語表記 | ハイブリッド: 固有名詞は英語、概念・方法論は日本語 |
| タグ爆発対策 | 既存 Topics を全件 LLM に渡し、同じ概念は既存表記を優先 |
| 個数 | 8〜15個（技術用語 5〜10 + 業務・組織観点 2〜5） |
| 粒度 | 技術用語 + 業務・組織の概念（EM ナレッジ活用目的） |

## 表記ルール

| 区分 | 表記 | 例 |
|------|------|------|
| 製品名・プロトコル名 | 英語 | `Kubernetes`, `gRPC`, `Kafka`, `PostgreSQL` |
| パターン名・方法論 | 日本語 | `モジューラーモノリス`, `サーガパターン`, `CQRS` |
| 業務・組織課題 | 日本語 | `運用負荷`, `チーム分割`, `オンコール`, `技術的負債` |
| 略語・頭字語 | 英語 | `ACID`, `DDD`, `CI/CD` |

## 変更対象

- `src/medium_notion/models.py` — `TranslationResult` に `topics` フィールド追加
- `src/medium_notion/translator.py` — `METADATA_PROMPT` に `topics` を追加、既存 Topics 参照
- `src/medium_notion/notion_client.py` — `list_existing_topics()` 追加、`_build_properties()` 拡張
- `src/medium_notion/cli.py` — Topics 取得・表示・インデックス保存のワイヤリング
- `tests/` — 全変更箇所のテスト

## データフロー

```
翻訳開始
  -> Notion から既存 Topics 一覧取得 (list_existing_topics)
  -> Step 2 プロンプトに existing_topics を注入
  -> Claude が JSON 返却 (topics フィールド含む)
  -> TranslationResult.topics にセット
  -> Notion ページ作成時に Topics multi_select として登録
```

## スコープ外

- 既存 21 記事へのバックフィル
- Status / Last reviewed / 他のプロパティ追加
- Topics の重複マージ UI
