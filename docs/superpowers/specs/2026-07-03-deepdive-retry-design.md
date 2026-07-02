# DeepDiver 一時エラーリトライ + 取りこぼし防止 設計書

- 日付: 2026-07-03
- 対象: `src/medium_notion/radar/deepdive.py`, `radar/models.py`, `radar/pipeline.py`, `cli.py`
- ステータス: レビュー反映済み（codex レビュー 2026-07-03 の指摘を反映）
- スコープ: 「リトライ + スキップ + 堅牢化」（ユーザ承認）

## 背景 / 問題

radar の深掘り（全文翻訳＋分析）は Claude Code CLI をサブプロセスで呼ぶ。
Claude の瞬断（例: `Connection closed mid-response` による非ゼロ exit）が起きると、
`DeepDiver.analyze()` が例外を握りつぶして**空の `DeepDive`** を返す。
その結果、pipeline は空の深掘りのまま Notion 行を作成し（`append_item` は成功）、記事を
**既読化**する（`mark_seen`）。→ 本文が欠落したまま恒久確定し、次回も拾われない。

## ゴール

- 瞬断由来の深掘り失敗を**リトライで実質的に根絶**する。
- リトライしても失敗した記事は**書き込みも既読化もスキップ**し、次回 radar 実行で
  再挑戦する（既存の「Notion 書き込み失敗 → 未読のまま次回リトライ」思想と一致）。
- **設定エラー（CLI 不在等）は握りつぶさず、run を声高に失敗させる**。
- Claude が全断のとき、無駄な Claude 呼び出しを**サーキットブレーカで抑制**する。

## 非ゴール（今回やらない・別タスク）

- `translator.py` の `_call_claude` は変更しない（別経路・スコープ外）。
- Notion の**部分書き込み**（ページ作成後に本文 append が失敗しても URL を返す既存バグ、
  `notion_writer.py:57,84`）の修正。関連するが独立した既存バグとして別途対応。
- 深掘り失敗を跨実行で永続化して再分類（`others` 落ち・`deepdive_max` 超え）に耐える仕組み。
  現実には翌朝も highlight のままである公算が高くROIが低いため見送り（下記「既知の限界」）。

## エラー分類（設計の要）

Claude 呼び出しの失敗を 3 種に分類する。

| 種別 | 例 | リトライ | run への影響 |
|------|----|:---:|------|
| **致命（run を失敗）** | `FileNotFoundError`（CLI 未インストール） | しない | `analyze()` から**再送出**して run を失敗させる |
| **回復不能・記事単位** | `TimeoutExpired`（10分×3=30分化を回避） | しない | その記事を `failed` 扱い → スキップ → 次回再挑戦 |
| **一時的（transient）** | 非ゼロ exit（接続断含む）/ 空応答 / 分析JSON不正 | する（3回・2s→4s） | 使い切ったら `failed` 扱い → スキップ |

例外型:
- `ClaudeCliNotFound(RuntimeError)` … 致命。`FileNotFoundError` を変換。
- `ClaudeTimeout(RuntimeError)` … 回復不能・記事単位。`TimeoutExpired` を変換。
- それ以外の `RuntimeError` … transient。

## 設計

### A. リトライ（deepdive.py）

リトライを共通ヘルパ `_run_with_retry(fn)` に集約し、サブプロセスの一時失敗と
**分析 JSON の解析失敗**の両方を同じ経路でリトライする（codex 指摘: 不正 JSON の握りつぶし防止）。

```python
import time
RETRY_ATTEMPTS = 3  # 初回 + リトライ2回


class ClaudeCliNotFound(RuntimeError): ...   # 致命: run を失敗させる
class ClaudeTimeout(RuntimeError): ...        # 回復不能・記事単位


def _run_with_retry(self, fn):
    """fn() を実行。transient 失敗はバックオフ再試行。致命/回復不能は即送出。"""
    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except (ClaudeCliNotFound, ClaudeTimeout):
            raise  # リトライしない
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS:
                wait = 2 ** attempt  # 2, 4
                log.warn(f"深掘りリトライ ({attempt}/{RETRY_ATTEMPTS - 1}) — {wait}秒待機: {e}")
                time.sleep(wait)
    raise last_err
```

`_call_claude`（生のサブプロセス呼び出し。リトライは持たない）:

```python
def _call_claude(self, prompt: str) -> str:
    cmd = ["claude", "-p", "--output-format", "text"]
    log.step(f"Claude で深掘り中 (プロンプト {len(prompt)} 文字)...")
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        raise ClaudeCliNotFound("Claude Code CLI が見つかりません。")
    except subprocess.TimeoutExpired:
        raise ClaudeTimeout("Claude Code CLI がタイムアウトしました（10分）")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "出力なし").strip()[:500]
        raise RuntimeError(f"Claude Code CLI エラー (exit {proc.returncode}): {detail}")
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError("Claude Code CLI から空の応答が返されました")
    return output
```

呼び出し側:
- 翻訳: `self._run_with_retry(lambda: self._call_claude(prompt))`
- 分析: 解析まで含めてリトライする。解析不能は transient `RuntimeError` を送出:

```python
def _analyze(self, title: str, content: str) -> dict:
    def once():
        raw = self._call_claude(ANALYZE_PROMPT.format(title=title, content=content[:8000]))
        parsed = self._parse_json(raw)
        if parsed is None:
            raise RuntimeError("分析 JSON を解析できませんでした")
        return parsed
    return self._run_with_retry(once)
```

`analyze()` は致命だけ再送出し、その他は `failed=True` で返す:

```python
def analyze(self, item, fulltext):
    try:
        ...  # 従来通り translate/_analyze を呼ぶ（各々 _run_with_retry 経由）
        return DeepDive(..., fulltext_ok=..., failed=False)
    except ClaudeCliNotFound:
        raise  # 致命 → run を失敗させる（握りつぶさない）
    except Exception as e:
        log.warn(f"深掘りに失敗（今回スキップ・次回再挑戦）: {item.url}: {e}")
        return DeepDive(fulltext_ok=bool(fulltext), failed=True)
```

### B. モデル変更（models.py）

`DeepDive` に `failed: bool = False` を追加。

### C. スキップ + サーキットブレーカ（pipeline.py）

深掘りループ: 1 記事が（リトライ使い切って）失敗したら、**以降の深掘りを打ち切り**、
残りの対象も `failed` 扱いにして次回に持ち越す（codex 指摘: 全断時の N×3 無駄呼び出し抑制）。

```python
circuit_open = False
for s in targets:
    if circuit_open:
        s.deepdive = DeepDive(failed=True)  # 未実施 → スキップ扱い、次回再挑戦
        continue
    fulltext = fulltext_fn(s.item)
    s.deepdive = diver.analyze(s.item, fulltext)
    if s.deepdive.failed:
        circuit_open = True
        log.warn("深掘り失敗を検知。以降の深掘りを中止し次回に持ち越します")
```

書き込みループ: `failed` の記事は **Notion 書き込みも既読化もスキップ**:

```python
written_items = []
for s in digest.highlights + digest.others:
    if s.deepdive is not None and s.deepdive.failed:
        log.warn(f"深掘り失敗のため今回は見送り（次回再挑戦）: {s.item.url}")
        continue
    url = writer.append_item(s, when)
    s.notion_url = url or ""
    if url:
        written_items.append(s.item)
```

- `others` は深掘りされない（`deepdive is None`）→ 影響なし・通常書き込み。
- `fulltext_ok=False`（本文が取れないだけの正常系）は `failed=False` → 通常書き込み。
- 致命エラーは深掘りループ内で送出され、`mark_seen`（step 7）到達前に run が落ちる
  → 何も既読化されず・何も失われない。

### D. CLI 件数の正確化（cli.py）

現状 `Notion {len(highlights)+len(others)}件` は**実書き込み数と乖離**する（スキップ発生時）。
実際に書けた件数を表示する:

```python
written = sum(1 for s in digest.highlights + digest.others if s.notion_url)
console.print(f"\n[bold green]✓ Notion {written}件[/bold green] / {slack_msg}")
```

## テスト（TDD）

### deepdive（A）
- `test_call_claude_retries_on_nonzero_exit_then_succeeds` — 非ゼロexit→成功。`subprocess.run` 2回・`time.sleep` 1回。
- `test_call_claude_retries_on_empty_response_then_succeeds` — 空応答→成功。
- `test_analyze_retries_on_malformed_json_then_succeeds` — 不正JSON→正JSON。`_call_claude` 2回で成功。
- `test_run_with_retry_raises_after_exhausting` — 常に transient 失敗。`RuntimeError`・呼び出し3回・sleep 2回。
- `test_call_claude_maps_file_not_found_to_fatal` — `FileNotFoundError`→`ClaudeCliNotFound`、リトライされない（sleepなし）。
- `test_call_claude_maps_timeout_to_non_retryable` — `TimeoutExpired`→`ClaudeTimeout`、リトライされない。
- `test_analyze_reraises_fatal_cli_not_found` — `ClaudeCliNotFound` は `analyze()` から**再送出**される（握りつぶさない）。
- `test_analyze_sets_failed_on_transient_failure` — transient を使い切ると `dd.failed is True`（翻訳・要約は空）。
- `test_analyze_sets_failed_on_timeout` — `ClaudeTimeout` → `dd.failed is True`（run は落とさない）。

（`time.sleep` は `medium_notion.radar.deepdive.time.sleep` を patch して高速化）

### 既存テスト更新（codex 指摘）
- `test_analyze_returns_empty_on_claude_failure` は意味が陳腐化（旧: 行・Slack 維持 / 新: 書き込みスキップ）。
  → `test_analyze_sets_failed_on_transient_failure` に置換／リネームし、`failed is True` を検証。

### pipeline（C）
- `test_run_radar_skips_write_and_seen_when_deepdive_failed` — highlight の `analyze` が `DeepDive(failed=True)` →
  その記事に `append_item` は呼ばれず、`seen.filter_new` に当該記事が残る（未読）。
- `test_run_radar_circuit_breaker_stops_deepdive_after_failure` — 対象3件で1件目失敗 →
  `diver.analyze` は1回だけ呼ばれ、残り2件も未書き込み・未読のまま。
- `test_run_radar_fatal_cli_error_aborts_without_marking_seen` — `analyze` が `ClaudeCliNotFound` を送出 →
  run は例外送出、`mark_seen` されず（全記事が未読のまま残る）。
- `test_run_radar_writes_normally_when_no_fulltext` — `failed=False, fulltext_ok=False` は通常書き込み（回帰防止）。

### cli（D）
- `test_radar_reports_actual_written_count` — スキップ発生時に表示件数が実書き込み数と一致。

## 既知の限界（spec に明記）

- **次回再挑戦は保証ではない**。`SeenStore` は「今回取得したフィード項目」に対してのみ未読判定する。
  記事がフィードから外れる／`DEFAULT_FEED_LIMIT` を超えると拾えない（`state.py:25`, `pipeline.py:39`）。
  日次実行で翌朝もフィードに残っている前提での best-effort。
- **再分類に非対応**。失敗記事が次回 `others` 落ち／`deepdive_max` 超えになると、深掘りなしで
  書き込まれ得る。永続 pending 管理は今回スコープ外（非ゴール参照）。
- **重複防止は完全ではない**。`mark_seen` は Notion 作成と非アトミック。Notion 成功後に
  `mark_seen` が落ちると次回重複し得る（既存の性質・本タスクでは扱わない）。

## ドキュメント整合

- 実装後、`docs/RADAR.md` の深掘り挙動・トラブルシュート節にリトライ／サーキットブレーカ／
  「失敗時は次回再挑戦」「CLI 不在は run 失敗」を追記。
- `CLAUDE.md` / `SPEC.md` の記述要否も確認。
