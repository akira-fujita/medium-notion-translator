import subprocess
from unittest.mock import patch, MagicMock

import pytest

from medium_notion.config import Config
from medium_notion.radar.models import FeedItem
from medium_notion.radar.deepdive import DeepDiver, ClaudeCliNotFound, ClaudeTimeout


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _cfg():
    return Config(notion_api_key="ntn_real_key", notion_database_id="a" * 32)


def _item():
    return FeedItem(url="https://x/a", title="AI org change", source="a16z",
                    layer="VC", summary_raw="短い概要")


def test_analyze_with_fulltext_translates_and_analyzes():
    diver = DeepDiver(_cfg())
    analysis = ('```json\n{"overview":"概要文","key_points":"押さえる点",'
                '"critique":"批判的視点"}\n```')
    with patch.object(diver, "_call_claude", side_effect=["日本語の全文訳", analysis]):
        dd = diver.analyze(_item(), fulltext="This is the full article body. " * 50)

    assert dd.fulltext_ok is True
    assert dd.translation == "日本語の全文訳"
    assert dd.overview == "概要文"
    assert dd.key_points == "押さえる点"
    assert dd.critique == "批判的視点"


def test_analyze_without_fulltext_skips_translation():
    diver = DeepDiver(_cfg())
    analysis = '{"overview":"概要","key_points":"点","critique":"批判"}'
    with patch.object(diver, "_call_claude", return_value=analysis) as m:
        dd = diver.analyze(_item(), fulltext=None)

    assert dd.fulltext_ok is False
    assert dd.translation == ""        # 翻訳は省略
    assert dd.overview == "概要"
    assert m.call_count == 1           # 分析のみ（翻訳しない）


def test_call_claude_maps_file_not_found_to_fatal():
    diver = DeepDiver(_cfg())
    with patch("medium_notion.radar.deepdive.subprocess.run",
               side_effect=FileNotFoundError()):
        with pytest.raises(ClaudeCliNotFound):
            diver._call_claude("p")


def test_call_claude_maps_timeout_to_non_retryable():
    diver = DeepDiver(_cfg())
    with patch("medium_notion.radar.deepdive.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600)):
        with pytest.raises(ClaudeTimeout):
            diver._call_claude("p")


def test_run_with_retry_retries_transient_then_succeeds():
    diver = DeepDiver(_cfg())
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    with patch("medium_notion.radar.deepdive.time.sleep") as sleep:
        assert diver._run_with_retry(fn) == "ok"
    assert calls["n"] == 2
    assert sleep.call_count == 1


def test_analyze_sets_failed_on_transient_failure():
    diver = DeepDiver(_cfg())
    with patch.object(diver, "_call_claude", side_effect=RuntimeError("boom")), \
            patch("medium_notion.radar.deepdive.time.sleep"):
        dd = diver.analyze(_item(), fulltext="body " * 50)
    assert dd.failed is True
    assert dd.translation == ""
    assert dd.overview == ""


def test_analyze_retries_on_malformed_json_then_succeeds():
    diver = DeepDiver(_cfg())
    good = '{"overview":"o","key_points":"k","critique":"c"}'
    with patch.object(diver, "_call_claude",
                      side_effect=["訳文", "not json", good]) as m, \
            patch("medium_notion.radar.deepdive.time.sleep"):
        dd = diver.analyze(_item(), fulltext="body " * 50)
    assert dd.failed is False
    assert dd.overview == "o"
    assert m.call_count == 3        # 翻訳1 + 分析(不正→正)2


def test_analyze_retries_on_empty_json_object_then_succeeds():
    diver = DeepDiver(_cfg())
    good = '{"overview":"o","key_points":"k","critique":"c"}'
    with patch.object(diver, "_call_claude",
                      side_effect=["訳文", "{}", good]) as m, \
            patch("medium_notion.radar.deepdive.time.sleep"):
        dd = diver.analyze(_item(), fulltext="body " * 50)
    assert dd.failed is False
    assert dd.overview == "o"
    assert m.call_count == 3        # 翻訳1 + 分析(空dict→正)2


def test_analyze_reraises_fatal_cli_not_found():
    diver = DeepDiver(_cfg())
    with patch.object(diver, "_call_claude", side_effect=ClaudeCliNotFound("no cli")):
        with pytest.raises(ClaudeCliNotFound):
            diver.analyze(_item(), fulltext="body " * 50)


def test_analyze_sets_failed_on_timeout():
    diver = DeepDiver(_cfg())
    with patch.object(diver, "_call_claude", side_effect=ClaudeTimeout("timeout")), \
            patch("medium_notion.radar.deepdive.time.sleep"):
        dd = diver.analyze(_item(), fulltext="body " * 50)
    assert dd.failed is True
