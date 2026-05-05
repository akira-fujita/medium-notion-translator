"""ヘッドレスでの Cloudflare 検出 / ステルス施策のテスト"""

from medium_notion.browser import _is_cloudflare_challenge


class TestIsCloudflareChallenge:
    """Cloudflare のインタースティシャルページを title から判定する"""

    def test_just_a_moment(self):
        assert _is_cloudflare_challenge("Just a moment...") is True

    def test_attention_required(self):
        assert _is_cloudflare_challenge("Attention Required! | Cloudflare") is True

    def test_japanese_shibaraku(self):
        # Cloudflare は Accept-Language に応じて翻訳した title を返すため、日本語版も検出する
        assert _is_cloudflare_challenge("しばらくお待ちください...") is True

    def test_normal_medium_page_not_challenge(self):
        assert (
            _is_cloudflare_challenge("toNotion - Akira Fujita - Medium") is False
        )

    def test_empty_title_not_challenge(self):
        assert _is_cloudflare_challenge("") is False

    def test_none_safe(self):
        assert _is_cloudflare_challenge(None) is False


