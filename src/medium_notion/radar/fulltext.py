"""記事本文の取得 — RSS 全文 or trafilatura 抽出

深掘り（全文翻訳）のために記事本文を取りに行く。RSS に十分な全文があれば
それを使い、無ければ記事 URL から trafilatura で本文抽出する。取得できなければ
None を返し、呼び出し側は要約のみにフォールバックする（無人実行を止めない）。
"""

from .models import FeedItem
from .. import logger as log

# RSS の content_full をそのまま採用する最小長。これ未満は「概要扱い」で抽出に回す。
MIN_FULLTEXT_LEN = 500


def fetch_fulltext(item: FeedItem) -> str | None:
    """記事本文を返す。取得できなければ None。"""
    # 1. RSS に十分長い全文があればそれを使う
    if item.content_full and len(item.content_full) >= MIN_FULLTEXT_LEN:
        return item.content_full

    # 2. URL から trafilatura で本文抽出
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(item.url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if text and len(text) >= MIN_FULLTEXT_LEN:
            return text
        return None
    except Exception as e:
        log.warn(f"本文取得に失敗（要約のみで継続）: {item.url}: {e}")
        return None
