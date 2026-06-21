# Tech Radar — 運用ガイド（フロー・挙動・トラブルシュート）

> radar は「毎朝のレーダー」。複数の RSS を巡回し、Claude が関心プロファイルで採点して
> **刺さる記事を深掘り（全文翻訳＋分析）→ Slack プッシュ＋Notion 蓄積**する。
>
> - 使い方・セットアップ: `README.md` の「Tech Radar」節
> - 設計判断（なぜこう作ったか）: `docs/superpowers/specs/2026-06-19-radar-rss-digest-design.md` / `2026-06-20-radar-deepdive-design.md`
> - 本書: **実際にどう動くか・失敗時どうなるか・どう調べ直すか**

---

## 1. 全体フロー

```
毎朝 7:00  launchd (com.akira.tech-radar)
   │
   ▼
run-radar.sh  ── 排他ロック → PATH 整備 → DNS 準備待ち(最大120s) ──▶ medium-notion radar
                                                                          │
   ┌──────────────────────────────────────────────────────────────────┘
   ▼
① 設定読込   .env / feeds.yml / interests.yml / radar-seen.json
② 取得       各フィードを httpx 取得（タイムアウト付・1フィード DEFAULT_FEED_LIMIT=12件）
③ 新着抽出   SeenStore で既読除外 ─── 新着ゼロなら静かに終了（何も出さない）
④ 採点       Curator → Claude が 0-10 採点＋日本語要約＋「仕事への影響」
⑤ 振り分け   score≥threshold=「刺さる」(最大 max_highlights) / 未満=「その他」
⑥ 深掘り     刺さる記事のみ・最大 deepdive_max:
                fetch_fulltext（RSS全文 or trafilatura）→ DeepDiver（全文翻訳＋3分析）
⑦ Notion     1記事=1行。刺さる記事はページ本文に深掘りを追記（100ブロックずつ）
⑧ Slack      ダイジェスト送信（3000字超は複数ブロック分割。各ハイライトに 📝Notion リンク）
⑨ 既読化     Notion 書き込みに成功した記事だけ既読登録（失敗分は翌日リトライ）
```

## 2. コンポーネント対応表

| 段階 | モジュール | 役割 |
|---|---|---|
| 起動 | `scripts/run-radar.sh` + `scripts/launchd/com.akira.tech-radar.plist` | 毎朝の無人実行・ロック・DNS待ち・ログ集約 |
| 設定 | `radar/config.py` | feeds.yml / interests.yml ローダ |
| 取得 | `radar/sources/rss.py` | RSS/Atom を httpx 取得→`FeedItem` |
| 既読 | `radar/state.py` | `radar-seen.json` で重複排除 |
| 採点 | `radar/curator.py` | Claude で関心プロファイル採点 |
| 振り分け/Slack | `radar/digest.py` | highlights/others 分割・Slack レンダリング |
| 深掘り | `radar/fulltext.py` + `radar/deepdive.py` | 本文取得＋全文翻訳＋分析 |
| 本文変換 | `radar/notion_blocks.py` | マークダウン→Notion ブロック |
| 書き込み | `radar/notion_writer.py` | DB 行＋ページ本文 |
| 統合 | `radar/pipeline.py` | 上記をオーケストレーション |
| CLI | `cli.py` の `radar` | エントリポイント |

## 3. Notion「tech news」DB の構造

| プロパティ | 型 | 内容 |
|---|---|---|
| 名前 | title | 日本語タイトル（無ければ原題）|
| URL | url | 元記事 URL |
| Date | date | 取得日 |
| Source | select | フィード名 |
| Layer | select | 一次情報 / Substack / VC |
| Summary | rich_text | 日本語1〜2行要約 |
| Why | rich_text | 関心への刺さり方 |
| Score | number | 0〜10 |

**刺さる記事（Score≥閾値）はページ本文**に：📖要約 → 📝全文翻訳 → 🎯立場として押さえるポイント → ⚠️批判的視点 → 元記事リンク。

## 4. 設定（チューニング）

`interests.yml`:
```yaml
threshold: 7        # この score 以上を「刺さる」に
max_highlights: 8   # Slack 前面に出す最大件数
deepdive_max: 8     # 1 実行で深掘りする最大件数（コスト防御）
profile:            # 採点の関心軸（自由記述）
  - "AI 時代の EM / manager layer 設計"
  - ...
```
`feeds.yml`: 取得元（`name` / `url` / `layer`）。URL は到達性を検証してから追加。

`.env`: `RADAR_NOTION_DATABASE_ID`（必須）, `RADAR_SLACK_WEBHOOK_URL`（任意・未設定なら `SLACK_WEBHOOK_URL`）。

CLI: `medium-notion radar` / `--dry-run`（送信せず確認）/ `--limit N`（フィード当たり上限）/ `--no-deepdive`。

## 5. 失敗時の挙動（設計された安全策）

| 事象 | 挙動 |
|---|---|
| 1フィード取得失敗 | ログしてスキップ、他は継続 |
| 新着ゼロ | Slack/Notion へ何も出さず終了 |
| Claude 採点失敗 | 素の新着を流す（score 0 扱い）|
| 深掘り失敗（本文取れない / Claude エラー）| その記事は要約のみ・行は保持 |
| Notion 書き込み失敗 | **その記事は既読化しない → 翌日リトライ**（取りこぼし防止）|
| Slack 送信失敗 | ログのみ（Notion 保存は維持）。CLI は「送信失敗」と正直に表示 |
| スリープ復帰直後で DNS 未準備 | run-radar.sh が最大120秒 DNS を待ってから実行 |
| Slack 3000字超 | 複数 section ブロックに自動分割 |
| 初回 seen 空 | DEFAULT_FEED_LIMIT=12/feed で全件処理（flood）を防止 |

**重要な不変条件**: 「Notion に保存できた記事だけ既読になる」。だから障害が起きても記事は失われず、次回必ず拾い直される。

## 6. トラブルシュート（"動いてる?" の調べ方）

```bash
# launchd 登録確認
launchctl list | grep com.akira.tech-radar

# 直近の実行ログ（タイムスタンプ・各記事の成否・致命的エラー）
tail -40 logs/radar.log

# 既読ストアの件数
python3 -c "import json; print(len(json.load(open('radar-seen.json'))))"

# 手動で即実行（動作確認。送信せず内容だけ見るなら --dry-run）
.venv/bin/medium-notion radar --dry-run
launchctl start com.akira.tech-radar   # launchd 経由で即実行
```

ログの見方:
- `✓ Notion N件 / Slack 投稿完了` … 正常
- `Slack 送信失敗（logs/radar.log 参照）` … Slack だけ失敗（Notion は保存済みのことが多い）
- `⚠ Notion 追加に失敗: ... [Errno 8] ...` … DNS/ネットワーク不通。**該当記事は既読化されないので翌日リトライされる**

### 取りこぼした記事を回収する
DNS 障害等で配信できなかった記事は既読化されないため通常は翌日自動で拾われる。
すぐ回収したい場合は手動で `medium-notion radar` を再実行（ネット復活後）。
誤って既読化された記事を戻すには、`radar-seen.json` から該当キー（guid/URL 断片）を削除して再実行。

### DB をリセットしたい（検証データの一掃）
Notion の全行をアーカイブ（Notion 上で手動、または API スクリプト）し、必要なら `radar-seen.json` を削除。
seen を消すと次回は新着が増えるため、静かに始めたい場合は「現在の記事を既読として先行シード」しておく。

## 7. 自動化（launchd）

```bash
bash scripts/launchd/install-radar.sh        # 毎朝7:00を有効化
launchctl unload ~/Library/LaunchAgents/com.akira.tech-radar.plist  # 停止
```
- 実行は `run-radar.sh`（ロック `logs/.run-radar.lock`、ログ `logs/radar.log`）
- radar は seen ストアで冪等なので、スリープ復帰の再発火や手動キックでも二重投稿しない
- 完全シャットダウンからも動かすなら: `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00`

## 8. 動線（使い方の意図）

```
朝、Slack を5分流し見
  └─ 刺さる記事の 📝 をタップ → Notion の深掘りページ（全文翻訳＋立場ポイント＋批判的視点）
      └─ あとから Score / Layer / Source で検索・振り返り
```

## 9. 既知の限界 / 将来

- 本文取得は任意サイト相手のため、JS依存・paywall は取れず要約のみになる
- Curator は新着を1プロンプトで採点（DEFAULT_FEED_LIMIT により最大~120件で頭打ち）。さらに増やすならチャンク分割が必要
- ソースは RSS のみ。GitHub Trending / Reddit は `Source` プロトコルで追加可能（X / Podcast は当面スコープ外）
