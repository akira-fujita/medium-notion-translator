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
    all_items = []
    for spec in radar_cfg.feeds:
        try:
            all_items.extend(RssSource(spec).fetch(limit))
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
        for s in targets:
            fulltext = fulltext_fn(s.item)
            s.deepdive = diver.analyze(s.item, fulltext)

    # 5. Notion 蓄積（作成ページ URL を各 ScoredItem に記録 → Slack の Notion リンク用）
    writer = notion_writer or RadarNotionWriter(config)
    for s in digest.highlights + digest.others:
        s.notion_url = writer.append_item(s, when) or ""

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

    # 7. 既読化
    seen.mark_seen(new_items)
    return digest
