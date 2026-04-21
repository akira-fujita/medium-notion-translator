---
name: translate-medium
description: Medium 記事を日本語翻訳して Notion DB に登録する。引数なしなら toNotion リスト一括、URL 指定なら単発翻訳。"翻訳して" "Medium を Notion に" 等のリクエスト時に使用。
---

# Translate Medium → Notion

Medium の英語技術記事を日本語翻訳し、構造化要約・Topics 付きで Notion DB に自動登録する。
このプロジェクトの `medium-notion` CLI を叩く薄いラッパー。

## 実行モード（引数で分岐）

ユーザーが `/translate-medium` に渡した引数 `$ARGUMENTS` を見て分岐する:

| 引数パターン | 実行コマンド |
|---|---|
| 空（引数なし） | `bookmark -l toNotion --run --gui` |
| URL 1つ | `translate -u <URL>` |
| URL + `-s N` | `translate -u <URL> -s N` |
| `-s N` + URL（逆順） | `translate -u <URL> -s N` |

URL は `https://medium.com/` もしくは `https://<publication>.medium.com/` で始まる文字列として抽出する。

## 事前確認

1. カレントディレクトリが `medium-notion-translator` リポジトリ配下であること（`pyproject.toml` の `name = "medium-notion-translator"` で確認）
2. `.venv/bin/medium-notion` が存在すること（なければ `pip install -e .` を案内）
3. `.env` と `medium-session.json` が存在すること（なければ `medium-notion setup` / `medium-notion login` を案内）

いずれか欠けていたら、実行前にユーザーに不足を報告する。

## 実行手順

1. 引数から URL とスコアを抽出して実行コマンドを決定
2. ユーザーに「これから何を実行するか」を1文で伝える（例: `toNotion リスト一括翻訳を開始します` / `<URL> を翻訳します`）
3. Bash ツールで以下を実行（バックグラウンド推奨、長時間処理のため）:
   ```bash
   cd <リポジトリルート> && .venv/bin/medium-notion <サブコマンド + 引数> 2>&1 | tee logs/translate-medium.log
   ```
4. 進捗を適宜確認（`TaskOutput` で完了待ち）
5. 完了後、成功件数・失敗件数をサマリーで報告

## 注意事項

- `translate` 単発実行はクォータ節約のため推奨。`bookmark --run` は toNotion リスト全件処理で時間がかかる
- Score は 1〜10 の整数（`-s 8` など）。範囲外は CLI 側で弾かれる
- Notion DB のプロパティ `create date` / `Topics` / `Categories` は作成時に自動設定される
- 失敗時は `logs/translate-medium.log` を確認し、Notion プロパティ不整合・セッション切れ・Claude CLI 未ログインを順にチェック

## 関連 CLI（skill では扱わないが参考）

- `medium-notion batch -f urls.txt -s 7` — URL リストファイル一括
- `medium-notion backfill-topics` — 既存ページの Topics 欠損をリカバリ
- `medium-notion index` — 記事インデックス再構築
- `medium-notion test` — 接続テスト
