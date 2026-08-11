"""Playwright ブラウザ配置先の解決 — シェル環境に依存しないためのテスト

`PLAYWRIGHT_BROWSERS_PATH` は ~/.zshrc にのみ書かれていたため、bash / launchd /
cron から起動すると変数が空になり、Playwright が既定の
`~/Library/Caches/ms-playwright`（空）を見て「ブラウザ未インストール」と誤判定していた。
アプリ側で既定の配置先を補うことでシェル依存を外す。
"""

import pytest

from medium_notion import browser as browser_mod
from medium_notion.browser import _ensure_browsers_path


def _make_browsers_dir(tmp_path, name="chromium-1208"):
    """Playwright がブラウザを展開した状態の配置先ディレクトリを作る"""
    d = tmp_path / ".playwright-browsers"
    (d / name).mkdir(parents=True)
    return d


class TestEnsureBrowsersPath:
    """未設定時のみ既定パスを環境変数に補う"""

    def test_sets_env_when_unset_and_dir_has_chromium(self, tmp_path):
        env: dict[str, str] = {}
        candidate = _make_browsers_dir(tmp_path)

        result = _ensure_browsers_path(env=env, candidate=candidate)

        assert result == str(candidate)
        assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(candidate)

    def test_respects_existing_env_value(self, tmp_path):
        # 利用者が明示的に指定した値は上書きしない
        env = {"PLAYWRIGHT_BROWSERS_PATH": "/somewhere/else"}
        candidate = _make_browsers_dir(tmp_path)

        result = _ensure_browsers_path(env=env, candidate=candidate)

        assert result is None
        assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/somewhere/else"

    def test_treats_empty_string_as_unset(self, tmp_path):
        # 実際に踏んだケース: 変数はあるが空文字
        env = {"PLAYWRIGHT_BROWSERS_PATH": ""}
        candidate = _make_browsers_dir(tmp_path)

        result = _ensure_browsers_path(env=env, candidate=candidate)

        assert result == str(candidate)
        assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(candidate)

    def test_leaves_unset_when_candidate_missing(self, tmp_path):
        # 既定パスが無いなら触らない（Playwright 本来のエラーメッセージを尊重する）
        env: dict[str, str] = {}

        result = _ensure_browsers_path(env=env, candidate=tmp_path / "nope")

        assert result is None
        assert "PLAYWRIGHT_BROWSERS_PATH" not in env

    def test_detects_headless_shell_only_install(self, tmp_path):
        # headless shell だけが入っている配置先も有効とみなす
        env: dict[str, str] = {}
        candidate = _make_browsers_dir(tmp_path, name="chromium_headless_shell-1208")

        result = _ensure_browsers_path(env=env, candidate=candidate)

        assert result == str(candidate)

    def test_leaves_unset_when_candidate_has_no_browser(self, tmp_path):
        # ディレクトリはあるが中身が無い場合に設定すると、
        # Playwright のエラーが実在しない場所を指して余計に分かりにくくなる
        env: dict[str, str] = {}
        empty = tmp_path / ".playwright-browsers"
        empty.mkdir()

        result = _ensure_browsers_path(env=env, candidate=empty)

        assert result is None
        assert "PLAYWRIGHT_BROWSERS_PATH" not in env


class TestInitializeWiring:
    """ブラウザ起動前に配置先の解決が走る"""

    async def test_initialize_resolves_browsers_path_before_launch(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []

        monkeypatch.setattr(
            browser_mod,
            "_ensure_browsers_path",
            lambda *a, **kw: calls.append("resolved"),
        )

        def _boom():
            calls.append("launch")
            raise RuntimeError("launch stopped here")

        monkeypatch.setattr(browser_mod, "async_playwright", _boom)

        from medium_notion.config import Config

        client = browser_mod.BrowserClient(
            Config(
                notion_api_key="x",
                notion_database_id="y",
                session_path=tmp_path / "s.json",
            )
        )

        with pytest.raises(RuntimeError, match="launch stopped here"):
            await client.initialize()

        # 起動より前に解決されていること
        assert calls == ["resolved", "launch"]
