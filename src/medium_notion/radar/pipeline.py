"""radar オーケストレーション — fetch → 採点 → 振り分け → 出力"""

import asyncio
from datetime import date

from ..config import Config
from .config import RadarConfig
from .curator import Curator
from .digest import build_digest
from .models import Digest
from .notion_writer import RadarNotionWriter
from .sources.rss import RssSource
from .state import SeenStore
from .. import logger as log

# --limit 未指定時のフィード当たり取得上限。
# 無制限だと初回（seen 空）に全フィードの全履歴（OpenAI で 1000 件超）を処理してしまい、
# Notion 大量登録・Claude 採点破綻・コスト爆発を招くため、既定で必ず bound する。
DEFAULT_FEED_LIMIT = 12


def run_radar(
    config: Config,
    radar_cfg: RadarConfig,
    seen: SeenStore,
    *,
    dry_run: bool,
    limit: int | None,
    when: date,
    scorer=None,
    notion_writer=None,
    slack_post=None,
    diver=None,
    fulltext_fn=None,
    no_deepdive: bool = False,
) -> Digest:
    """radar パイプラインを実行して Digest を返す"""
    # 1. 全フィード取得（1 件失敗しても継続）
    # --limit 未指定でもデフォルト上限を必ず適用（バックログ全件処理を防ぐ）
    effective_limit = limit if limit is not None else DEFAULT_FEED_LIMIT
    all_items = []
    for spec in radar_cfg.feeds:
        try:
            all_items.extend(RssSource(spec).fetch(effective_limit))
        except Exception as e:
            log.warn(f"フィード取得失敗（スキップ）: {spec.name}: {e}")

    # 2. 新着のみ
    new_items = seen.filter_new(all_items)
    log.step(f"新着 {len(new_items)} 件 / 取得 {len(all_items)} 件")
    if not new_items:
        log.success("新着なし。何も出力しません。")
        return Digest()

    # 3. 採点
    scorer = scorer or Curator(config)
    scored = scorer.score(new_items, radar_cfg)

    # 4. 振り分け
    digest = build_digest(scored, radar_cfg.threshold, radar_cfg.max_highlights)

    if dry_run:
        log.step("dry-run: Notion/Slack へは送信しません")
        digest.slack_status = "dry_run"
        return digest

    # 4.5 刺さる記事を深掘り（本文取得 → 全文翻訳＋分析）。deepdive_max まで。
    if not no_deepdive and digest.highlights:
        from .fulltext import fetch_fulltext
        from .deepdive import DeepDiver

        diver = diver or DeepDiver(config)
        fulltext_fn = fulltext_fn or fetch_fulltext
        targets = digest.highlights[: radar_cfg.deepdive_max]
        skipped = len(digest.highlights) - len(targets)
        log.step(f"深掘り対象 {len(targets)} 件（上限 {radar_cfg.deepdive_max}, 見送り {skipped}）")
        from .models import DeepDive

        circuit_open = False
        for s in targets:
            if circuit_open:
                # 一度深掘りが失敗したら以降は打ち切り、失敗扱いで次回に持ち越す
                s.deepdive = DeepDive(failed=True)
                continue
            fulltext = fulltext_fn(s.item)
            s.deepdive = diver.analyze(s.item, fulltext)
            if s.deepdive.failed:
                circuit_open = True
                log.warn("深掘り失敗を検知。以降の深掘りを中止し次回に持ち越します")

    # 5. Notion 蓄積（作成ページ URL を各 ScoredItem に記録 → Slack の Notion リンク用）
    #    書き込みに成功した記事だけ既読化する（失敗分は未読のまま次回リトライ＝取りこぼし防止）
    writer = notion_writer or RadarNotionWriter(config)
    written_items = []
    for s in digest.highlights + digest.others:
        if s.deepdive is not None and s.deepdive.failed:
            # 深掘りが失敗 → 今回は書き込みも既読化も見送り、次回 radar で再挑戦
            log.warn(f"深掘り失敗のため今回は見送り（次回再挑戦）: {s.item.url}")
            continue
        url = writer.append_item(s, when)
        s.notion_url = url or ""
        if url:
            written_items.append(s.item)

    # 6. Slack プッシュ（送信結果を digest に記録）
    webhook = config.radar_slack_webhook_url or config.slack_webhook_url
    if webhook:
        poster = slack_post
        if poster is None:
            from ..slack import post_digest

            def poster(url, d):
                return asyncio.run(post_digest(url, d))

        sent = poster(webhook, digest)
        digest.slack_status = "sent" if sent else "failed"
    else:
        digest.slack_status = "skipped"

    # 7. 既読化（Notion に書けた記事のみ。失敗分は次回リトライされる）
    seen.mark_seen(written_items)
    return digest
