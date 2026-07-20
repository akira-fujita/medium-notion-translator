# radar 深掘り（刺さる記事の全文翻訳＋分析）設計書

> **バージョン**: 0.1.0
> **作成日**: 2026-06-20
> **作成者**: Akira Fujita（with Claude）
> **前提**: `2026-06-19-radar-rss-digest-design.md`（radar 本体）

---

## 1. 概要

radar が「刺さる」と採点した記事（score ≥ threshold）に対し、記事本文を取得して
**全文翻訳＋構造化分析**を生成し、Notion の該当行の**ページ本文**に書き込む。

radar 本体は「流し見トリアージ」のまま。深掘りは**刺さった記事だけ**に限定して
「発見（radar）→ 深掘り（deepdive）」の二段構えを 1 回の朝の実行で完結させる。

### 1.1 生成する内容（ページ本文）

| セクション | 絵文字 | 内容 |
|---|---|---|
| 要約 | 📖 | 何についての記事で結論は何か（2〜3文）|
| 全文翻訳 | 📝 | 記事本文の日本語訳（マークダウン維持）|
| 立場として押さえるポイント | 🎯 | EM→経営側の視点で押さえるべき点（2〜4点）|
| 批判的視点 | ⚠️ | 鵜呑みにしない・反論・限界・前提の弱さ（2〜3点）|

DB 行の既存プロパティ（Summary 1-2行 / Why / Score 等）はそのまま。深掘りは**本文に追記**。

---

## 2. スコープ

- **対象**: `score >= threshold` のハイライトのみ。
- **1 実行あたりの上限**: `deepdive_max`（デフォルト 8）。超過分は深掘りせず行のみ（コスト・時間防御）。`log` で残数を報告。
- **タイミング**: 毎朝の `radar`（`--run` 相当）に統合。`--dry-run` 時は深掘りもスキップ。
- **オプトアウト**: `radar --no-deepdive` で従来の軽量動作に戻せる。

---

## 3. アーキテクチャ

### 3.1 データフロー（radar 本体への追加点）

```
… 採点 → build_digest →
  ┌─ ハイライト（score≥閾値, 上限 deepdive_max）ごとに:
  │    ① 本文取得（fetch_fulltext）
  │    ② Claude 深掘り（DeepDiver.analyze）→ 翻訳＋3分析
  │    ③ ScoredItem に deepdive 結果を保持
  └─
→ Notion 書き込み（行 + ハイライトはページ本文に深掘りブロック）
→ Slack（📝 リンクはリッチページを指す）→ 既読化
```

### 3.2 モジュール構成（追加）

| ファイル | 責務 | 依存 |
|---|---|---|
| `radar/fulltext.py` | 記事本文の取得。RSS 全文 or URL から `trafilatura` 抽出。取れなければ `None` | trafilatura, httpx |
| `radar/deepdive.py` | `DeepDiver`：本文 + Claude → `DeepDive`（translation/overview/key_points/critique） | claude CLI |
| `radar/models.py`（拡張）| `DeepDive` dataclass、`ScoredItem.deepdive: DeepDive \| None` | — |
| `radar/notion_writer.py`（拡張）| 行作成時、ハイライトはページ本文に深掘りブロックを append | notion SDK |
| `radar/pipeline.py`（拡張）| ハイライトに対し fulltext→deepdive を回し ScoredItem に格納 | — |
| `radar/config.py`（拡張）| `deepdive_max`（interests.yml）| — |
| `cli.py`（拡張）| `--no-deepdive` フラグ | — |

### 3.3 `DeepDive` データモデル

```python
@dataclass
class DeepDive:
    translation: str    # 全文翻訳（マークダウン）
    overview: str       # 📖 要約
    key_points: str     # 🎯 立場として押さえるポイント
    critique: str       # ⚠️ 批判的視点
    fulltext_ok: bool   # 本文取得できたか（False なら翻訳は空・要約のみ）
```

---

## 4. 本文取得（fulltext.py）

`fetch_fulltext(item: FeedItem) -> str | None`:

1. RSS エントリに全文があればそれを使う（`FeedItem.content_full` を新設し rss.py で取り込む。`e.content[0].value` が概要より十分長ければ採用）。
2. 無ければ `trafilatura.fetch_url(item.url)` → `trafilatura.extract()` で本文抽出。
3. 取得失敗（None / 極端に短い / 例外）→ `None` を返す（呼び出し側はフォールバック）。
4. タイムアウト・例外は握りつぶしてログ（無人実行を止めない）。

> JS 依存サイト・paywall・bot ブロックは取得不可になりうる。その場合は深掘りせず
> 行＋既存 Summary のみ（`DeepDive.fulltext_ok=False`、本文に「⚠️ 全文取得不可」を残す）。

---

## 5. 深掘り（deepdive.py）

`DeepDiver(config).analyze(item, fulltext) -> DeepDive`:

- 本文が取れた場合: Claude に「全文翻訳 + 要約 + 立場ポイント + 批判的視点」を依頼。
  - 長文（> 15000 字）は翻訳をチャンク分割（translator.py の方式を踏襲）。
  - 翻訳（プレーンmd）と分析（JSON）を**分離**（既存の 2 ステップ思想）。
- 本文が取れなかった場合（fulltext=None）: 翻訳は空、要約等は RSS 概要から最小生成、`fulltext_ok=False`。
- Claude 失敗時: 既存方針どおり握りつぶし、空の `DeepDive`（行・Slack は維持）。

Claude 呼び出しは `translator.py` のパターン（`claude -p`, stdin, JSON フォールバック）を再利用。
共通化できる部分は `claude_cli` ヘルパ抽出を検討（DRY）。

---

## 6. Notion 書き込み（notion_writer.py 拡張）

- 行作成は従来どおり。**戻り値の page_id を使い**、ハイライトはページ本文にブロック append:
  - `## 📖 要約` + 段落
  - `## 📝 全文翻訳` + 本文（マークダウン→Notion ブロック化。`notion_client.py` の既存パーサ／2000字分割を再利用）
  - `## 🎯 立場として押さえるポイント` + 箇条書き
  - `## ⚠️ 批判的視点` + 箇条書き
  - 末尾に元記事 bookmark
- 本文構築ロジックは `notion_client.py` に重複実装が多いので、**ブロック生成の共通関数を切り出して再利用**（マークダウン→blocks 変換）。
- 1 ブロック append 失敗は行を壊さずスキップ＋ログ。

---

## 7. 設定

`interests.yml` に追加:

```yaml
deepdive_max: 8   # 1 実行で深掘りする刺さる記事の上限（コスト防御）
```

CLI: `radar --no-deepdive`（深掘り無効）。dry-run は深掘りしない。

---

## 8. エラーハンドリング

| 事象 | 挙動 |
|---|---|
| 本文取得失敗 | 深掘りスキップ、`fulltext_ok=False`、本文に「⚠️ 全文取得不可」、行は作成 |
| Claude 失敗 | 深掘り空、行・Slack は維持（情報を捨てない）|
| ページ本文 append 失敗 | ログのみ、行は残る |
| deepdive_max 超過 | 超過分は深掘りせず行のみ、残数をログ |

---

## 9. テスト方針（TDD）

| 対象 | テスト |
|---|---|
| `fulltext.py` | RSS 全文あり→それ採用 / 無し→trafilatura（モック）/ 失敗→None |
| `deepdive.py` | Claude 出力（翻訳＋JSON）のパース、本文なし時のフォールバック、Claude 失敗時 |
| `notion_writer` | 深掘りブロック生成（マークダウン→blocks）、page_id 経由の append 呼び出し |
| `pipeline` | ハイライトのみ深掘りが回る / deepdive_max 上限 / dry-run はスキップ / --no-deepdive |
| markdown→blocks 共通関数 | 見出し・段落・箇条書き・コードの変換と 2000 字分割 |

ネットワーク・Claude・Notion は全てモック。

---

## 10. 新規依存（要確認）

- **`trafilatura`** — 任意サイトの本文抽出。依存が多め（lxml 等）だが本文抽出の定番で精度が高い。
  - 代替案: `readability-lxml`（軽量だが精度やや劣る）。MVP は trafilatura。

---

## 11. スコープ外 / 将来

- 取得不可サイトの Playwright フォールバック（重い。当面しない）
- 過去記事との関連（Medium translate の 🔗 相当）は今回入れない（radar の Notion に関連分析の土台がまだ薄いため）
- 深掘り対象を「score≥閾値」以外（手動指定・お気に入り）に広げる拡張
