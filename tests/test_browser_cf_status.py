"""HTTP 4xx/5xx が Cloudflare チャレンジだった場合の扱い

Cloudflare の JS チャレンジは 403 を返してから JS で解決する。
`status >= 400` で即 raise していたため、直後にある `_wait_past_cloudflare()`
（最大30秒の通過待ち）に一度も到達せず、cf_clearance が切れるたびに落ちていた。
"""

import pytest

from medium_notion.browser import BrowserClient
from medium_notion.config import Config


class FakePage:
    """title() が呼ばれるたびに与えた並びを順に返すページ（最後の値は残り続ける）"""

    def __init__(self, titles: list[str]):
        self._titles = titles
        self._i = 0
        self.waits = 0

    async def title(self) -> str:
        t = self._titles[min(self._i, len(self._titles) - 1)]
        self._i += 1
        return t

    async def wait_for_timeout(self, ms: int) -> None:
        self.waits += 1


class FakeResponse:
    def __init__(self, status: int):
        self.status = status


def make_client(tmp_path, titles: list[str]) -> BrowserClient:
    client = BrowserClient(
        Config(
            notion_api_key="x",
            notion_database_id="y",
            session_path=tmp_path / "s.json",
        )
    )
    client._page = FakePage(titles)
    return client


class TestVerifyResponseStatus:
    async def test_403_cloudflare_challenge_that_passes_does_not_raise(self, tmp_path):
        # 403 でチャレンジ title、待っている間に通過 → 続行できる
        client = make_client(
            tmp_path, ["Just a moment...", "Just a moment...", "toNotion - Medium"]
        )

        await client._verify_response_status(FakeResponse(403), "失敗 (HTTP {status})")

        assert client._page.waits > 0

    async def test_403_without_challenge_title_raises_immediately(self, tmp_path):
        # 本物の 403（権限切れ・ブロック）は待たずに即エラー
        client = make_client(tmp_path, ["Forbidden"])

        with pytest.raises(RuntimeError, match="HTTP 403"):
            await client._verify_response_status(
                FakeResponse(403), "失敗 (HTTP {status})"
            )

        assert client._page.waits == 0

    async def test_challenge_that_never_passes_raises(self, tmp_path):
        # チャレンジが通らないまま timeout → 従来どおりエラー
        client = make_client(tmp_path, ["Just a moment..."])

        with pytest.raises(RuntimeError, match="HTTP 403"):
            await client._verify_response_status(
                FakeResponse(403), "失敗 (HTTP {status})", timeout_ms=3_000
            )

        assert client._page.waits == 3

    async def test_404_never_waits(self, tmp_path):
        # チャレンジ title が出ていても 404 は待たない
        client = make_client(tmp_path, ["Just a moment..."])

        with pytest.raises(RuntimeError, match="HTTP 404"):
            await client._verify_response_status(
                FakeResponse(404), "失敗 (HTTP {status})"
            )

        assert client._page.waits == 0

    async def test_success_and_none_response_pass_through(self, tmp_path):
        # 200 と、response が None (playwright が返さないケース) は素通り
        client = make_client(tmp_path, ["toNotion - Medium"])

        await client._verify_response_status(FakeResponse(200), "失敗 (HTTP {status})")
        await client._verify_response_status(None, "失敗 (HTTP {status})")

        assert client._page.waits == 0


class Sentinel(RuntimeError):
    """配線確認用 — _verify_response_status が呼ばれたことを示す"""


class GotoPage(FakePage):
    """goto() が指定ステータスを返すページ"""

    def __init__(self, status: int):
        super().__init__(["Just a moment..."])
        self.url = "https://medium.com/me/lists"

    async def goto(self, url, **kwargs):
        return FakeResponse(403)


class TestCallSitesDelegate:
    """403 の判定は各呼び出し側で直書きせず _verify_response_status に集約する"""

    async def test_fetch_reading_list_delegates(self, tmp_path, monkeypatch):
        session = tmp_path / "s.json"
        session.write_text("{}")
        client = BrowserClient(
            Config(
                notion_api_key="x",
                notion_database_id="y",
                session_path=session,
                headless=False,
            )
        )
        client._page = GotoPage(403)

        async def _raise(*a, **kw):
            raise Sentinel("delegated")

        monkeypatch.setattr(client, "_verify_response_status", _raise)

        with pytest.raises(Sentinel):
            await client.fetch_reading_list("toNotion")

    async def test_fetch_article_delegates(self, tmp_path, monkeypatch):
        session = tmp_path / "s.json"
        session.write_text("{}")
        client = BrowserClient(
            Config(
                notion_api_key="x",
                notion_database_id="y",
                session_path=session,
                headless=False,
            )
        )
        client._page = GotoPage(403)

        async def _raise(*a, **kw):
            raise Sentinel("delegated")

        monkeypatch.setattr(client, "_verify_response_status", _raise)

        with pytest.raises(Sentinel):
            await client.fetch_article("https://medium.com/@x/y")
