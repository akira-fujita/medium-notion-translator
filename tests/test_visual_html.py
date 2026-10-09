"""視覚版 HTML（図とクイズ）の生成と Notion への埋め込みのテスト

podcast-summary の手順5b と同じく、要約ページには毎回 notion-visual-primer の
無人モードで作った HTML を埋め込む。HTML は従で、失敗しても記事の登録は成功のまま。
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from medium_notion.visual_html import (
    HtmlGenerationError,
    attach_visual_html,
    build_prompt,
    extract_html,
    local_html_path,
)


VALID_HTML = (
    "<!DOCTYPE html>\n<html lang=\"ja\"><head><title>t</title></head><body>"
    "<div class=\"fig\">図</div><section><h2>理解チェック</h2>"
    + "".join(f"<p>Q{i}</p><details><summary>答え</summary>A{i}</details>" for i in (1, 2, 3))
    + "</section></body></html>"
)


@pytest.fixture
def primer_dir(tmp_path):
    """notion-visual-primer の正本ファイルを模したディレクトリ"""
    d = tmp_path / "notion-visual-primer"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text("SKILL-BODY-MARKER", encoding="utf-8")
    (d / "references" / "html-contract.md").write_text("CONTRACT-MARKER", encoding="utf-8")
    (d / "references" / "unattended-mode.md").write_text("UNATTENDED-MARKER", encoding="utf-8")
    return d


@pytest.fixture
def page():
    p = MagicMock()
    p.page_id = "3ef54f2b-d9f0-81e6-a243-cd59da79560b"
    p.url = "https://www.notion.so/page-3ef54f2bd9f081e6a243cd59da79560b"
    return p


class TestBuildPrompt:
    def test_includes_primer_docs_and_article(self, primer_dir, sample_translation, page):
        """スキルの正本（SKILL・HTML 契約・無人モード）と記事の材料が入ること"""
        prompt = build_prompt(sample_translation, page.url, primer_dir)

        for marker in ("SKILL-BODY-MARKER", "CONTRACT-MARKER", "UNATTENDED-MARKER"):
            assert marker in prompt
        assert sample_translation.japanese_title in prompt
        assert sample_translation.japanese_content in prompt
        assert sample_translation.summary in prompt
        assert sample_translation.original.url in prompt
        assert page.url in prompt

    def test_missing_primer_dir_is_an_error(self, tmp_path, sample_translation, page):
        """正本が無いなら失敗にする（スキルとズレた HTML を作らない）"""
        with pytest.raises(HtmlGenerationError, match="notion-visual-primer"):
            build_prompt(sample_translation, page.url, tmp_path / "nope")


class TestExtractHtml:
    def test_strips_code_fence_and_chatter(self):
        """前置き・コードフェンスが付いても文書だけを取り出す"""
        raw = f"以下が HTML です。\n```html\n{VALID_HTML}\n```\n以上です。"
        assert extract_html(raw) == VALID_HTML

    def test_failed_line_is_reported(self):
        """無人モードの失敗（FAILED: 理由）は理由つきの例外にする"""
        with pytest.raises(HtmlGenerationError, match="学習目標が書けない"):
            extract_html("FAILED: 学習目標が書けない")

    def test_truncated_document(self):
        """</html> が無い = 途中で切れている。中途半端な HTML は埋め込まない"""
        with pytest.raises(HtmlGenerationError, match="</html>"):
            extract_html(VALID_HTML.replace("</html>", ""))

    def test_quiz_section_is_required(self):
        """HTML 契約で 理解チェック 節は必須（無いものは契約違反として失敗にする）"""
        with pytest.raises(HtmlGenerationError, match="理解チェック"):
            extract_html(VALID_HTML.replace("理解チェック", "まとめ"))


class TestLocalHtmlPath:
    def test_uses_page_id_prefix_and_slug(self, tmp_path):
        """podcast と同じ規則: 日付-ページ ID 先頭8桁-英数スラグ。英数にできなければスラグを省く"""
        p = local_html_path(
            "3ef54f2b-d9f0-81e6-a243-cd59da79560b",
            "I Cut My Claude Code API Costs by 40%",
            date(2026, 10, 9),
            root=tmp_path,
        )
        assert p == tmp_path / "2026-10-09-3ef54f2b-i-cut-my-claude-code-api-costs-by-40.html"
        assert local_html_path("3ef54f2bd9f0", "日本語だけ", date(2026, 10, 9), root=tmp_path) == (
            tmp_path / "2026-10-09-3ef54f2b.html"
        )


def _attach(notion, call_claude, sample_translation, page, primer_dir, tmp_path):
    return attach_visual_html(
        notion,
        call_claude,
        sample_translation,
        page,
        primer_dir=primer_dir,
        out_root=tmp_path / "out",
        today=date(2026, 10, 9),
    )


class TestAttachVisualHtml:
    def test_success_marks_generating_then_embeds(
        self, sample_translation, page, primer_dir, tmp_path
    ):
        """⏳生成中 → 生成 → ローカル保存 → アップロード → 埋め込み → ✅"""
        notion = MagicMock()
        notion.upload_html.return_value = "fu-1"
        call_claude = MagicMock(return_value=VALID_HTML)

        outcome = _attach(notion, call_claude, sample_translation, page, primer_dir, tmp_path)

        assert outcome.ok
        assert [c.args for c in notion.mark_html.call_args_list] == [
            (page.page_id, "⏳生成中"),
            (page.page_id, "✅"),
        ]
        # ローカルにも残す（my-knowledge に入れたくなった時に使う）
        assert outcome.path.parent == tmp_path / "out"
        assert outcome.path.read_text(encoding="utf-8") == VALID_HTML
        notion.upload_html.assert_called_once_with(outcome.path.name, VALID_HTML.encode("utf-8"))
        notion.embed_html.assert_called_once_with(page.page_id, "fu-1")

    @pytest.mark.parametrize(
        "claude_effect, reason",
        [
            ({"return_value": "FAILED: 図が1つも作れない"}, "図が1つも作れない"),
            ({"side_effect": RuntimeError("Claude Code CLI がタイムアウトしました")}, "タイムアウト"),
        ],
    )
    def test_failure_marks_failed_and_does_not_raise(
        self, sample_translation, page, primer_dir, tmp_path, claude_effect, reason
    ):
        """HTML は従。生成に失敗しても例外を外に出さず（記事の登録は成功のまま）⚠失敗 を残す"""
        notion = MagicMock()
        call_claude = MagicMock(**claude_effect)

        outcome = _attach(notion, call_claude, sample_translation, page, primer_dir, tmp_path)

        assert not outcome.ok
        assert reason in outcome.reason
        assert notion.mark_html.call_args_list[-1].args == (page.page_id, "⚠失敗")
        notion.embed_html.assert_not_called()

    def test_notion_failures_keep_local_html_and_are_contained(
        self, sample_translation, page, primer_dir, tmp_path
    ):
        """アップロードが落ちてもローカルの HTML は残し、⚠失敗 の書き込み自体が落ちても外に出さない"""
        notion = MagicMock()
        notion.upload_html.side_effect = RuntimeError("Notion API エラー")
        notion.mark_html.side_effect = [None, RuntimeError("Notion 落ちてる")]
        call_claude = MagicMock(return_value=VALID_HTML)

        outcome = _attach(notion, call_claude, sample_translation, page, primer_dir, tmp_path)

        assert not outcome.ok
        assert "Notion API エラー" in outcome.reason
        assert outcome.path is not None and outcome.path.read_text(encoding="utf-8") == VALID_HTML

    def test_local_save_failure_is_contained(
        self, sample_translation, page, primer_dir, tmp_path, monkeypatch
    ):
        """保存先に書けない（権限なし等）。後始末の exists() まで例外を投げても外に出さない（codex P1）"""
        from pathlib import Path

        def deny(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "write_text", deny)
        monkeypatch.setattr(Path, "exists", deny)
        notion = MagicMock()

        outcome = _attach(notion, MagicMock(return_value=VALID_HTML), sample_translation, page, primer_dir, tmp_path)

        assert not outcome.ok and outcome.path is None
        assert notion.mark_html.call_args_list[-1].args == (page.page_id, "⚠失敗")


class TestQuizValidation:
    def test_quiz_needs_at_least_three_folded_answers(self):
        """HTML 契約: 理解チェック は 3〜5 問で、答えを <details> で畳む。見出しだけの空のクイズは失敗（codex P2）"""
        empty_quiz = (
            "<!DOCTYPE html><html><body><h2>理解チェック</h2>"
            "<p>Q1</p><details><summary>答え</summary>A1</details></body></html>"
        )
        with pytest.raises(HtmlGenerationError, match="3"):
            extract_html(empty_quiz)

    def test_counts_answers_only_inside_the_quiz_section(self):
        """目次リンクの「理解チェック」から数えない。見出しの節の中の <details> だけを数える（codex 2巡目 P2）"""
        folded = "".join(f"<details><summary>補足</summary>{i}</details>" for i in range(3))
        html = (
            "<!DOCTYPE html><html><body>"
            "<nav><a href=\"#quiz\">理解チェック</a></nav>"
            f"<h2>本文</h2>{folded}"
            "<h2 id=\"quiz\">理解チェック</h2><p>（問いなし）</p>"
            "<h2>落とした主張</h2></body></html>"
        )
        with pytest.raises(HtmlGenerationError, match="0 個"):
            extract_html(html)

    def test_heading_may_contain_inline_tags(self):
        """<h2><span>🧠</span> 理解チェック</h2> のように見出しの中にタグがあっても見つける"""
        html = VALID_HTML.replace("<h2>理解チェック</h2>", "<h2><span>🧠</span> 理解チェック</h2>")
        assert extract_html(html) == html

    @pytest.mark.parametrize(
        "html, ok",
        [
            # 見出しの文字列がタグで分断されていても見つける
            (VALID_HTML.replace("<h2>理解チェック</h2>", "<h2>理解<span>チェック</span></h2>"), True),
            # コメントアウトされた見出しは見出しではない（codex 3巡目 P2）
            (
                "<!DOCTYPE html><html><body><!-- <h2>理解チェック</h2> -->"
                + "".join(f"<details><summary>補足</summary>{i}</details>" for i in range(3))
                + "<h2>理解チェック</h2><p>（問いなし）</p></body></html>",
                False,
            ),
        ],
    )
    def test_heading_is_found_by_its_text_outside_comments(self, html, ok):
        if ok:
            assert extract_html(html) == html
        else:
            with pytest.raises(HtmlGenerationError):
                extract_html(html)
