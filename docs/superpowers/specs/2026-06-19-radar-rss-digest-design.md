# radar — RSS Tech ダイジェスト 設計書

> **バージョン**: 0.1.0
> **作成日**: 2026-06-19
> **作成者**: Akira Fujita（with Claude）
> **対象読者**: 開発者（将来の自分）、AI エージェント

---

## 1. 概要

### 1.1 何をするか

複数の Tech 系 RSS/Atom フィード（企業 Engineering Blog / Substack / VC ブログ）を毎朝自動巡回し、
新着記事を Claude が「関心プロファイル」に照らして 0–10 で採点。閾値以上を「今日の刺さる N 本」として
**Slack にプッシュ**し、全件を **Notion の Tech Radar DB に蓄積**する。

既存の Medium 翻訳ツール（`translate` / `bookmark` / `batch`）が **深掘り型**（1 記事を全文翻訳 + 4 観点要約）
であるのに対し、`radar` は **トリアージ/ダイジェスト型**（多数ソースを流し見し、刺さるものだけ拾う）。
リポジトリを「EM ナレッジ蓄積プラットフォーム」として再定義し、2 つのパイプラインが同居する。

### 1.2 解決する課題

- 一次情報（企業 Eng ブログ・VC・Substack）が散在し、毎朝の巡回コストが高い
- 情報量が多すぎて「構造変化」を示す重要な記事が埋もれる
- 「自分の関心（AI 時代の EM / 組織設計 / 構造変化 / 事業側視点）」に照らした選別が手作業

### 1.3 対象ユーザー

Engineering Manager → CTO / 事業責任者 へ移行中の本人。「技術そのもの」より「構造変化」を見る関心軸を持つ。
毎朝 5–10 分で当日の構造変化を把握することがゴール。

---

## 2. アーキテクチャ

### 2.1 データフロー

```
feeds.yml ─────┐
               ├→ RssSource.fetch() ─→ 新着フィルタ ─→ Curator(Claude採点) ─→ 振り分け ─┬→ Slack プッシュ
interests.yml ─┘            ↑                            ↑                  (score≥閾値)  └→ Notion 蓄積
                       state.py(既読除外)          interests.yml                                  ↓
                                                                                          state.py に既読記録
```

1. `feeds.yml` / `interests.yml` を読み込む
2. 各フィードを `RssSource.fetch()` で取得・パース → `FeedItem` のリスト
3. `state.py` で既読（guid/URL）を除外 → 新着のみ
4. 新着ゼロなら **何も出力せず終了**（既存の「空振り通知しない」方針を踏襲）
5. `Curator` が新着 + `interests.yml` を Claude にバッチ投入 → `ScoredItem`（score / 日本語要約 / why）
6. `score >= threshold` を「刺さる」、それ未満を「その他」に振り分け
7. `digest.py` が Slack blocks と Notion rows にレンダリング → 両方へ出力
8. 出力に成功した項目を `state.py` に既読記録

### 2.2 モジュール構成（`src/medium_notion/radar/` を新設）

| ファイル | 責務 | 依存 |
|---|---|---|
| `radar/__init__.py` | パッケージ初期化 | — |
| `radar/models.py` | `FeedItem` / `ScoredItem` / `Digest` データモデル | pydantic |
| `radar/sources/base.py` | `Source` プロトコル（将来 GitHub/Reddit を足す差込口） | — |
| `radar/sources/rss.py` | RSS/Atom 取得・パース → `list[FeedItem]` | feedparser |
| `radar/state.py` | 既読ストア（`radar-seen.json`、guid/URL で重複排除） | — |
| `radar/curator.py` | 新着 + interests.yml → Claude バッチ採点 → `list[ScoredItem]` | claude CLI |
| `radar/digest.py` | `Digest` → Slack blocks / Notion rows の 2 レンダラ | — |
| `radar/config.py` | feeds.yml / interests.yml / radar 用 env のロード | pydantic, pyyaml |

**既存モジュールの拡張**:

| ファイル | 追加内容 |
|---|---|
| `notion_client.py` | Tech Radar DB への行追加メソッド（`append_radar_item` 等）。既存 DB ロジックとは独立 |
| `slack.py` | `post_digest(digest)` — ダイジェスト用の整形投稿 |
| `cli.py` | `radar` コマンド（`--run` / `--dry-run` / `--gui` 不要） |
| `pyproject.toml` | 依存に `feedparser`, `pyyaml` を追加 |

**設計のキモ**: `Source` をプロトコル化し `rss.py` はその一実装。将来 GitHub Trending / Reddit を足すときは
新アダプタを 1 ファイル足すだけで済む。`curator.py` 以降は Source 非依存（`FeedItem` のみに依存）。

### 2.3 ブラウザ不要

RSS/Atom は HTTP GET で取得できるため Playwright は不要。`radar` パイプラインはブラウザ・セッションに
一切依存しない（既存 `translate` 系とは独立）。

---

## 3. 設定ファイル

### 3.1 `feeds.yml`（リポジトリにコミット）

```yaml
- {name: "Anthropic News",          url: "https://www.anthropic.com/news/rss.xml",        layer: "一次情報"}
- {name: "OpenAI Blog",             url: "https://openai.com/blog/rss.xml",               layer: "一次情報"}
- {name: "Cloudflare Blog",         url: "https://blog.cloudflare.com/rss/",              layer: "一次情報"}
- {name: "Netflix TechBlog",        url: "https://netflixtechblog.com/feed",              layer: "一次情報"}
- {name: "Stripe Blog",             url: "https://stripe.com/blog/feed.rss",              layer: "一次情報"}
- {name: "The Pragmatic Engineer",  url: "https://blog.pragmaticengineer.com/rss/",       layer: "Substack"}
- {name: "Latent Space",            url: "https://www.latent.space/feed",                 layer: "Substack"}
- {name: "a16z",                    url: "https://a16z.com/feed/",                        layer: "VC"}
- {name: "Y Combinator Blog",       url: "https://www.ycombinator.com/blog/rss",          layer: "VC"}
```

> 各 URL は実装時に到達性を検証し、無効なものは差し替える。`layer` はダイジェストのグループ見出し。

### 3.2 `interests.yml`（リポジトリにコミット）

```yaml
threshold: 7          # この score 以上を「今日の刺さる」に昇格
max_highlights: 8     # Slack で前面に出す最大件数（多すぎる日の保険）
profile:
  - "AI 時代の EM / engineering manager layer の設計"
  - "組織の AI 導入と、それに伴う構造変化"
  - "CTO・執行役員・事業責任者の視点"
  - "本業（垂直）× 副業（水平）のキャリア設計"
  - "AI が壊す/生む職種、どこに金が流れているか"
```

### 3.3 環境変数（`.env`、コミットしない）

| 変数名 | 必須 | 説明 | デフォルト |
|---|---|---|---|
| `RADAR_NOTION_DATABASE_ID` | radar 使用時 ○ | Tech Radar DB の ID（翻訳 DB とは別） | — |
| `RADAR_SLACK_WEBHOOK_URL` | × | radar 専用 Slack Webhook。未設定なら既存 `SLACK_WEBHOOK_URL` を使用 | `SLACK_WEBHOOK_URL` |
| `CLAUDE_MODEL` | × | 採点に使う Claude モデル（既存と共有） | `sonnet` |

---

## 4. Curator（採点ロジック）

### 4.1 方式

Claude Code CLI を **1 回のバッチ呼び出し**で採点する（記事ごとに呼ばない＝コスト/時間削減）。
`translator.py` の Claude 呼び出しパターン（`claude -p --output-format text`、stdin 経由、```json``` ブロック抽出 → 深さカウントのフォールバック）を再利用する。

**入力**（プロンプトに埋め込む）:
- `interests.yml` の `profile`
- 新着各件の `source / title / 冒頭 ~500 字`

**出力**（JSON 配列）:

```json
[
  {
    "url": "https://...",
    "score": 8,
    "jp_title": "日本語タイトル",
    "summary": "日本語 1–2 行の要約",
    "why": "あなたの関心（EM/組織/構造変化）への影響"
  }
]
```

### 4.2 件数が多い日の扱い

新着が一度のプロンプトに収まらない量（目安 > 30 件 or 合計文字数超過）になった場合はチャンク分割して
複数回呼び出し、結果をマージする。MVP では単一呼び出しを基本とし、チャンク分割は件数で発火。

### 4.3 失敗時

Claude 呼び出しが失敗 / JSON パース不能のときは **採点を諦めて素の新着をそのまま流す**
（score 欠落 = 全件「その他」扱い）。翻訳ツールの「Step2 が失敗しても Step1 は捨てない」と同じ思想で、
取得した情報は失わない。

---

## 5. 出力

### 5.1 Slack（プッシュ）

- `score >= threshold` を「今日の刺さる N 本」として `layer` 別に整形（上限 `max_highlights`）。
- 各ハイライト: `[layer] jp_title — summary（why）` + 元記事リンク。
- 残り（その他）は末尾に 1 ブロックで集約: `📂 その他 M 件: title(link) · title(link) …`
  （Slack に折りたたみ機能がないため、リンクの列挙で代替）。
- 投稿先は `RADAR_SLACK_WEBHOOK_URL`（なければ `SLACK_WEBHOOK_URL`）。

### 5.2 Notion（蓄積）

Tech Radar DB に **1 記事 = 1 行**で append する。

| プロパティ | 型 | 内容 |
|---|---|---|
| `名前` | title | `jp_title`（無ければ原題） |
| `URL` | url | 元記事 URL |
| `Date` | date | 取得日 |
| `Source` | select | フィード名（例: Anthropic News） |
| `Layer` | select | 一次情報 / Substack / VC |
| `Summary` | rich_text | 日本語要約 |
| `Why` | rich_text | 関心への影響 |
| `Score` | number | 0–10 |

> Tech Radar DB はユーザーが Notion 上に作成し、Integration を接続する（既存翻訳 DB と同じ運用）。
> 必要プロパティが揃っているかは `radar --run` 初回に検証し、不足はエラー表示で知らせる。

---

## 6. CLI

| コマンド | 説明 | 主なオプション |
|---|---|---|
| `radar --run` | 取得 → 採点 → Slack + Notion 出力（無人実行の本番経路） | `--limit N`（フィード当たり取得上限）, `--since DAYS` |
| `radar --dry-run` | 取得 → 採点 → **stdout に表示のみ**（Slack/Notion へは送らない） | 同上 |

- 新着ゼロ / 全件既読のときは Slack/Notion へ何も送らず早期終了。
- 致命的エラー（Claude CLI 不在 / Notion 認証失敗等）は既存 `notify_fatal_error` を再利用してアラート。

---

## 7. エラーハンドリング方針

| 事象 | 挙動 |
|---|---|
| 1 フィードの取得/パース失敗 | ログに記録してスキップ、他フィードは継続（全体を止めない） |
| Claude 採点失敗 | 採点なしで素の新着を流す（情報を失わない） |
| Notion 行追加失敗（1 件） | ログ記録してスキップ、他の行は継続 |
| Slack 送信失敗 | ログのみ（メインフローに影響させない、既存方針） |
| 新着ゼロ | 出力せず早期 return（無人実行のシグナル汚染回避） |

---

## 8. テスト方針（TDD）

| 対象 | テスト内容 | 手法 |
|---|---|---|
| `sources/rss.py` | RSS/Atom 双方の fixture から `FeedItem` を正しく抽出 | ローカル XML fixture（ネットワーク非依存） |
| `state.py` | 既読 guid/URL の重複排除、初回（ファイル無）の挙動 | tmp ファイル |
| `curator.py` | Claude 出力（```json``` 込み / 素の JSON / 壊れた JSON）のパースと失敗時フォールバック | Claude 呼び出しをモック |
| `digest.py` | 振り分け（threshold）と Slack/Notion 双方のレンダリング | 純粋関数として検証 |
| `config.py` | feeds.yml / interests.yml のロードとバリデーション | tmp YAML |

ネットワーク・Claude CLI・Notion API は全てモック / fixture 化し、ユニットテストは外部 I/O に依存しない。

---

## 9. 既存資産の再利用

| 既存 | radar での再利用 |
|---|---|
| `translator.py` の Claude CLI 呼び出しパターン | curator が踏襲（必要なら共通ヘルパ `claude_cli.py` に抽出） |
| `notion_client.py` | Tech Radar DB 用メソッドを追加（既存 DB ロジックと分離） |
| `slack.py` | `post_digest` / `notify_fatal_error` を再利用 |
| `config.py` の Pydantic + dotenv | radar 用設定を追加 |
| `scripts/` の launchd 自動化 | `radar --run` を毎朝スケジュール（別 plist or 既存に追加） |

---

## 10. スコープ外（YAGNI / 将来）

- **X（旧 Twitter）**: 無料 API 事実上不可・スクレイピング極めて脆い → 当面やらない
- **Podcast**: 文字起こしが重く高コスト → 当面やらない
- **GitHub Trending / Reddit**: `Source` プロトコルの追加アダプタとして将来対応（MVP では作らない）
- **深掘り連携**: 「radar で拾った 1 本を translate に流す」二段構えは将来検討（今は別パイプラインのまま）

---

## 付録 A: `Source` プロトコル（将来拡張の差込口）

```python
class Source(Protocol):
    name: str
    layer: str
    def fetch(self, limit: int | None = None) -> list[FeedItem]: ...
```

将来 `sources/github_trending.py` / `sources/reddit.py` を同インターフェースで実装すれば、
`curator` 以降を変えずにソースを増やせる。
