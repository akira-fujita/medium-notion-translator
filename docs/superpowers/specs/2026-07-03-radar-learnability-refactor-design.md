# Tech Radar 「学べる具体」リニューアル — 設計

- 日付: 2026-07-03
- 対象: `src/medium_notion/radar/`（Tech Radar パイプライン）+ `feeds.yml` / `interests.yml`
- ステータス: 設計合意済み（Codex 2 巡レビュー反映、ブロッカーなし）
- 関連: `2026-06-19-radar-rss-digest-design.md` / `2026-06-20-radar-deepdive-design.md` / `docs/RADAR.md`

## 1. 背景と課題

Tech Radar は毎朝 RSS を巡回し、Claude が関心プロファイルで採点、刺さる記事を深掘りして
Slack + Notion に出す。運用してみて、ユーザ（EM → CTO/執行役員へ移行中）の実感は
**「毎朝のダイジェストが役に立たない」**。

根本原因は 2 つ:

1. **ソースが持論寄り** — 現行 10 フィードは論説・thought-leadership が主成分で、
   ポジショントーク（意見だけで具体の乏しい記事）を量産しやすい。
2. **分析が浅い** — 元記事が持論だと、要約も「仕事への影響」コメントも一般論に薄まる。

ユーザにとっての価値は **「この記事から何を学べるか」**。学べる具体 =
(1) 実装・仕組みの具体 / (2) 組織・AI 導入の実例 / (3) 再利用できるフレームワーク・考え方 /
(4) 検証可能な市場ファクト・データ、のいずれか。単なる意見・持論はノイズ。

## 2. 方針

「面白い意見を拾う」から **「学べる具体を拾って、学びを抽出する」** へ転換する。
採点を 1 軸（関心一致度）から 2 軸（関心一致度 + **学べる度=具体性**）に拡張し、
**学べる度は本文を読んでから判定する**。ソースも substance 寄りに再構成する。

### 2.1 Codex レビューで採用した重要判断

- **本文を読む前に learnability を判定しない**（最大の設計欠陥だった）。→ 2 パス化。
- **合成スコアは廃止**し、ハードゲート `relevance >= 6 AND learnability >= 6` にする。
- **証拠ベース**: learnability は数値だけでなく `concrete_types` / 本文中の根拠を返させ、
  本文に具体的根拠が無ければ learnability を低く抑える（Claude の「それっぽい抽象語」捏造対策）。
- **薄い日は Slack を空にしてよい**（ユーザ選択）。基準未満なら無理に highlight を出さない。
- **prescreen は「relevance>=6 は全件、top_k は安全上限」**（固定 top_k で良記事を落とさない）。

## 3. パイプライン（2 パス）

現行: `取得 → 新着抽出 → 採点(スニペット) → 振り分け → highlight のみ深掘り → Notion → Slack`

新:

```
取得 → 新着抽出
  → PASS 1: relevance 事前選別（スニペット・安い・一括）
  → PASS 2: 候補のみ本文取得 → learnability 採点（本文ベース・証拠付き）
  → ハイライト判定（ハードゲート）
  → 深掘り（PASS 2 で取得済みの本文を再利用）
  → Notion 蓄積
  → Slack（highlights のみ）
  → 既読化
```

### PASS 1 — relevance 事前選別（スニペット）
- title + RSS summary で `relevance`(0-10) のみを **一括 1 コール**で採点（現行の採点コールに近い）。
- **候補 = relevance >= `relevance_min`(既定 6) を満たす全件**。ただし本文取得コスト防御として
  `prescreen_cap`(既定 25) を上限に relevance 降順で足切り。上限に当たったら件数をログに出す（暗黙の切り捨て禁止）。

### PASS 2 — 本文取得 + learnability 採点（本文ベース）
- 候補ごとに `fetch_fulltext`（RSS 全文 or trafilatura）で本文取得。
- 本文を渡して 1 記事 1 コールで採点。返す JSON:
  - `learnability`(0-10)
  - `concrete_types`: 本文に含まれる具体の種別（`implementation` / `case_study` /
    `framework` / `market_fact` のうち該当するもの。空なら learnability<=3）
  - `evidence`: 本文中の具体的根拠を短く列挙（数字・アーキ詳細・事例名など）。空なら learnability<=3
  - `jp_title` / `summary`
  - `learning`: **Slack lead 用の 1 行**（本文ベース生成なので snippet 由来の捏造リスクは低い）
- learnability を deepdive コールに畳まない（別パス維持）。highlight 未満に高価な翻訳を走らせないため。
- 本文取得に失敗した候補は learnability を付けず「評価不能」扱い（§6 の状態遷移参照）。

### ハイライト判定（ハードゲート）
- `highlight ⟺ relevance >= relevance_min(6) AND learnability >= learn_min(6)`。
- 並び順: **learnability 降順 → relevance 降順**。`max_highlights`(既定 8) で上限。
- 基準を満たす記事が 0 件なら highlights は空（薄い日は空でよい）。

### 深掘り（learning 抽出）
- 対象は highlights のみ、`deepdive_max`(既定 8) まで。
- **PASS 2 で取得済みの本文を再利用**（再フェッチしない）。
- 分析を学び中心に再構成（現行の `overview/key_points/critique` を置換）:
  - `overview`: 何の記事で結論は何か
  - `learnings`: **この記事から学べる具体 3 点。実装/数字/手法/実例を必ず含める**（本文用の詳細）
  - `try_now`: 明日から自分/チームで試せる 1 つ
  - `critique`: 批判的視点（据え置き）
- 全文翻訳は現行どおり本文用に生成し、ページ末尾へ。

### Slack
- **highlights のみ**を送る。low-learnability（その他）は Slack に出さない。
- 各 highlight の lead 行は `🎓 学び: {ScoredItem.learning}`（従来の `💡 why` を置換）。
- highlights が 0 件の日は **一行だけ**送る（例: `🛰 今朝の Tech Radar — 今日は基準を超える記事なし`）。
  無音にしない（radar が動いた証跡を残し「壊れた」と誤認させない）。

## 4. データモデル変更

- `FeedSpec`: `signal: str = "mixed"`（`substance` / `opinion` / `mixed`）を追加。
  **補助のプロンプトヒント + 診断用**（本文を読む方式になったため load-bearing ではない。後方互換で既定 mixed）。
- `ScoredItem`: `relevance: int` / `learnability: int` / `concrete_types: list[str]` /
  `evidence: list[str]` / `learning: str`（Slack 用 1 行）を追加。
  - 既存 `score` は撤去し、ソートは (learnability, relevance) を直接使う。Notion「Score」プロパティ
    には learnability を書く（§5）。`why` は撤去（`learning` が後継）。
- `DeepDive`: `learnings: str`（詳細 3 点）/ `try_now: str` を追加、`key_points` を撤去。
  - **役割の明確化**（Codex #4）: `ScoredItem.learning` = Slack 用 1 行 /
    `DeepDive.learnings` = Notion 本文用の詳細 3 点。二重生成だが用途が別。

## 5. Notion スキーマ

- 追加プロパティ:
  - `Relevance`(number) / `Score`(number, = learnability を格納)
  - `Concrete Types`(multi-select)  ← evidence 配列は prop 化せず、ページ本文に散文で書く（Codex #5）
- ページ本文: `📖 要約 → 🎓 学べること(3点) → 🧪 明日試すこと → ⚠️ 批判的視点 → 📝 全文翻訳 → 元記事リンク`
- **スキーマ移行の安全化**（Codex #schema）:
  - 新プロパティは **手動で先に Notion DB に追加**する手順を `docs/RADAR.md` に明記。
  - `notion_writer` は **プロパティ欠損に寛容**にする（未作成プロパティはスキップして書き込み継続）。

## 6. 状態管理（seen / partial failure）— Codex #6/#7

現行は「Notion 書き込みに成功した記事だけ既読化（失敗は翌日リトライ）」。2 パス化で
non-highlight や本文取得失敗が増えるため、状態遷移を明文化する。

**既読化の対象**: その run で **retriable な失敗なく処理を終えた記事**。
- **highlight**: Notion 書き込み成功 → 既読化。Notion 失敗 → 既読化しない（翌日リトライ）。
- **non-highlight（基準未満だが評価は完了）**: 既読化する（毎日 re-score しない）。
  - トレードオフ: 後日 threshold を下げても再浮上しない。頻度が低いため許容する（`docs/RADAR.md` に明記）。
    再評価したい場合は `radar-seen.json` から該当 URL を消す運用でカバー。
- **本文取得/採点が失敗した候補**: 既読化しない（翌日リトライ）。
- **PASS 1 で候補に入らなかった記事（relevance 低）**: 評価完了とみなし既読化する。

**部分失敗**:
- Slack はバッチ末尾で 1 回送信（現行どおり）。**Slack 失敗で Notion を再作成しない**。
- 既読化は Notion 書き込み後に行う（現行の順序を維持）。write 成功後・mark_seen 前のクラッシュで
  翌日重複作成が起こりうる点は現行と同じ既知の許容リスク。
- **サーキットブレーカー緩和**（Codex #失敗モード）: 現行「深掘り 1 件失敗で残り全部中止」を
  **該当 1 件をスキップして継続**に変更。失敗記事は既読化せず翌日リトライ。

## 7. 設定（interests.yml に外出し）

```yaml
relevance_min: 6     # PASS1 候補入り & highlight ゲート
learn_min: 6         # highlight ゲート（learnability）
prescreen_cap: 25    # PASS2 本文取得の上限（コスト防御。実測して調整）
max_highlights: 8
deepdive_max: 8
profile: [ ... ]     # 現行どおり
```

- 合成スコアの重みは持たない（ハードゲートのみ）。
- `prescreen_cap` は当初 25 でスタートし、本文取得件数の実測を見て調整（Codex #2）。

## 8. ソース刷新（feeds.yml）

- 各フィードに `signal` タグを付与し、substance 寄りに再構成。
- **具体的な新フィード一覧と RSS 到達性・本文抽出率の検証は実装フェーズで実施**し、
  実装前に候補リストをユーザに提示して選定する（Codex #8: 入力が薄いままだと改善幅が限定的なので、
  到達性と trafilatura 抽出成功率を実測してから確定）。
- 候補カテゴリ: 実エンジニアリング深掘り / ポストモーテム / 研究・データ・レポート系。
  現行の opinion 系は残すか要検討（残す場合も `signal: opinion` を付け、ゲートで自然に沈む）。

## 9. スコープ外（YAGNI）

- PASS 2 の並列化（当面は逐次。レイテンシが問題化したら検討）。
- learnability の機械学習的キャリブレーション。
- `seen_evaluated` / `written` の厳密な 2 テーブル分離（§6 の単純ルールで足りる。将来必要なら分離）。

## 10. テスト方針（TDD）

各ユニットを独立にテスト（既存 `tests/test_radar_*.py` を踏襲）:
- `curator`: PASS1 relevance 採点の JSON パース / 候補足切り（relevance_min, prescreen_cap）。
- `curator`(PASS2): 本文ベース learnability 採点、evidence 空 → learnability<=3 の強制。
- `digest`: ハードゲート判定と (learnability, relevance) ソート、0 件時の Slack 一行。
- `deepdive`: learnings/try_now を含む分析 JSON パース、本文再利用（再フェッチしないこと）。
- `pipeline`: 2 パスのオーケストレーション、状態遷移（highlight/non-highlight/失敗の既読化）。
- `notion_writer`: 新プロパティ書き込み + プロパティ欠損への寛容性。
- `digest`(slack): 🎓 lead レンダリング、highlights のみ送信。
```
