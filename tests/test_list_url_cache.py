"""カスタムリスト URL のキャッシュ I/O テスト

Cloudflare が /me/lists 経由でカスタムリストにアクセスするフローを scraping として
ブロックするため、一度発見した URL はキャッシュして直接 goto に切り替える。
"""

import json
from pathlib import Path

import pytest

from medium_notion.browser import (
    _load_list_url_cache,
    _save_list_url,
)


class TestLoadListUrlCache:
    def test_returns_empty_when_file_missing(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        assert _load_list_url_cache(cache_path) == {}

    def test_returns_dict_when_file_exists(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        cache_path.write_text(json.dumps({"toNotion": "https://example.com/list/x"}))
        assert _load_list_url_cache(cache_path) == {
            "toNotion": "https://example.com/list/x"
        }

    def test_returns_empty_on_corrupt_json(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        cache_path.write_text("not json {")
        assert _load_list_url_cache(cache_path) == {}


class TestSaveListUrl:
    def test_creates_file_with_first_entry(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        _save_list_url(cache_path, "toNotion", "https://example.com/list/x")
        loaded = json.loads(cache_path.read_text())
        assert loaded == {"toNotion": "https://example.com/list/x"}

    def test_merges_with_existing(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        cache_path.write_text(json.dumps({"existing": "https://example.com/old"}))
        _save_list_url(cache_path, "toNotion", "https://example.com/list/x")
        loaded = json.loads(cache_path.read_text())
        assert loaded == {
            "existing": "https://example.com/old",
            "toNotion": "https://example.com/list/x",
        }

    def test_overwrites_existing_key(self, tmp_path):
        cache_path = tmp_path / ".medium-list-cache.json"
        cache_path.write_text(json.dumps({"toNotion": "old"}))
        _save_list_url(cache_path, "toNotion", "new")
        loaded = json.loads(cache_path.read_text())
        assert loaded == {"toNotion": "new"}

    def test_strips_tracking_query(self, tmp_path):
        """source= や utm_ 等のトラッキングクエリは保存時に除去する"""
        cache_path = tmp_path / ".medium-list-cache.json"
        url_with_tracking = (
            "https://medium.com/@user/list/foo-abc?source=my_lists---------1-------"
        )
        _save_list_url(cache_path, "toNotion", url_with_tracking)
        loaded = json.loads(cache_path.read_text())
        assert loaded["toNotion"] == "https://medium.com/@user/list/foo-abc"
