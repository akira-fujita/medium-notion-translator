"""ヘッドレスでの Cloudflare 検出 / ステルス施策のテスト"""

from medium_notion.browser import (
    _is_cloudflare_challenge,
    _is_retryable_challenge_status,
)


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


class TestRetryableChallengeStatus:
    """Cloudflare がチャレンジ配信時に返すステータスは即エラーにしない

    Cloudflare の JS チャレンジは 403 を返してから JS で解決する。
    status >= 400 で即 raise すると通過待ちのロジックに一度も到達しない。
    """

    def test_403_is_retryable(self):
        assert _is_retryable_challenge_status(403) is True

    def test_404_is_not_retryable(self):
        # 存在しないページは待っても通らない
        assert _is_retryable_challenge_status(404) is False

    def test_other_statuses(self):
        assert _is_retryable_challenge_status(429) is True
        assert _is_retryable_challenge_status(503) is True
        assert _is_retryable_challenge_status(401) is False
        assert _is_retryable_challenge_status(500) is False
