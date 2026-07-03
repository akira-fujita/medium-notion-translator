"""radar 共通の Claude CLI エラー型

curator / deepdive の双方が同じ分類でエラーを扱えるよう、ここに集約する。
"""


class ClaudeCliNotFound(RuntimeError):
    """Claude CLI 不在等の致命的な設定エラー（リトライせず run を失敗させる）"""


class ClaudeTimeout(RuntimeError):
    """Claude 呼び出しのタイムアウト（リトライせず、記事単位でスキップする）"""
