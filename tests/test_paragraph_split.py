"""コードフェンスを意識したパラグラフ分割のテスト

問題: `content.split("\\n\\n")` ではコードブロック内の空行で
分断され、コードブロックの中身が「普通の段落」として
処理されてしまう。これにより:
- 目次にコード行が混入
- 太字 `**...**` が code 内なのに描画される
- ``` がリテラルでテキストに残る

修正: フェンス (` ``` `) の開閉を line-by-line で追跡し、
コードブロック内の空行は段落区切りとして扱わない。
"""

from medium_notion.notion_client import _split_paragraphs


class TestSplitParagraphs:
    def test_simple_paragraphs(self):
        text = "段落1\n\n段落2\n\n段落3"
        assert _split_paragraphs(text) == ["段落1", "段落2", "段落3"]

    def test_single_paragraph(self):
        assert _split_paragraphs("段落のみ") == ["段落のみ"]

    def test_empty(self):
        assert _split_paragraphs("") == []

    def test_code_block_with_blank_lines_kept_intact(self):
        """コードブロック内の空行で分断されないこと"""
        text = (
            "前文の段落\n"
            "\n"
            "```python\n"
            "def foo():\n"
            "    pass\n"
            "\n"  # コードブロック内の空行
            "def bar():\n"
            "    pass\n"
            "```\n"
            "\n"
            "後文の段落"
        )
        result = _split_paragraphs(text)
        assert len(result) == 3
        assert result[0] == "前文の段落"
        assert result[1].startswith("```python")
        assert result[1].endswith("```")
        assert "def foo()" in result[1]
        assert "def bar()" in result[1]
        assert result[2] == "後文の段落"

    def test_multiple_code_blocks(self):
        text = (
            "```\nA\n```\n"
            "\n"
            "段落\n"
            "\n"
            "```\nB\n\nC\n```"
        )
        result = _split_paragraphs(text)
        assert len(result) == 3
        assert result[0] == "```\nA\n```"
        assert result[1] == "段落"
        assert result[2] == "```\nB\n\nC\n```"

    def test_code_block_at_start(self):
        text = "```\nfoo\n```\n\n段落"
        result = _split_paragraphs(text)
        assert result == ["```\nfoo\n```", "段落"]

    def test_code_block_at_end_with_no_trailing_newline(self):
        text = "段落\n\n```\nfoo\n```"
        result = _split_paragraphs(text)
        assert result == ["段落", "```\nfoo\n```"]

    def test_unclosed_code_block_treated_as_code_until_end(self):
        """閉じ忘れの ``` があっても無限に飲み込まずに最後まで読む"""
        text = "段落\n\n```python\nfoo\n\nbar"
        result = _split_paragraphs(text)
        # 閉じてないコードブロックは EOF まで一塊として扱う
        assert len(result) == 2
        assert result[0] == "段落"
        assert result[1].startswith("```python")
        assert "foo" in result[1] and "bar" in result[1]

    def test_consecutive_blank_lines_collapsed(self):
        """通常段落の連続空行は1つの区切りとして扱う"""
        text = "A\n\n\n\nB"
        assert _split_paragraphs(text) == ["A", "B"]
