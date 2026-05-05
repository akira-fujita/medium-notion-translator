"""Medium 記事取得 — Playwright ブラウザ自動化"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .config import Config
from .models import MediumArticle
from . import logger as log

# 記事コンテナを見つけるためのセレクタ（優先度順）
ARTICLE_CONTAINER_SELECTORS = [
    "article",
    "[data-testid='story-content']",
    ".postArticle-content",
    "main",
    "[role='main']",
]

# ログイン状態を判定するセレクタ
LOGIN_SELECTORS = [
    "[data-testid='headerUserButton']",
    "[data-testid='write-button']",
    "a[href='/me/stories']",
    "button[aria-label*='user']",
]

# ペイウォール検出キーワード
PAYWALL_INDICATORS = [
    "member-only story",
    "this story is for members only",
    "become a member",
    "sign up to continue",
    "subscribe to read",
]

# Cloudflare チャレンジページの title パターン
# Cloudflare は Accept-Language に応じて文言を翻訳して返すので、日本語版も含める
_CLOUDFLARE_TITLE_PATTERNS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "cloudflare",
    "しばらくお待ちください",
    "お待ちください",
)


def _is_cloudflare_challenge(title: str | None) -> bool:
    """ページ title から Cloudflare のインタースティシャル画面かどうかを判定する"""
    if not title:
        return False
    lowered = title.lower()
    return any(pattern in lowered for pattern in _CLOUDFLARE_TITLE_PATTERNS)


def _strip_tracking_query(url: str) -> str:
    """URL からトラッキング目的のクエリ (`?source=...` 等) を除去する。

    Medium の「ライブラリ → リスト」遷移では `?source=my_lists---...` が付くが、
    リスト本体の同定には不要で、キャッシュとしては正規 URL の方が安定する。
    """
    if "?" not in url:
        return url
    return url.split("?", 1)[0]


def _load_list_url_cache(cache_path: Path) -> dict[str, str]:
    """カスタムリスト名 → 正規 URL のキャッシュを読み込む。

    存在しない / 壊れている場合は空 dict を返す（自己回復）。
    """
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_list_url(cache_path: Path, list_name: str, url: str) -> None:
    """カスタムリスト名 → 正規 URL をキャッシュに保存する（既存 entry はマージ）。

    `/me/lists` を経由して URL を発見するフローは Cloudflare に scraping パターンと
    して検出されることがあるため、一度発見した URL は次回以降に直接 goto する。
    """
    cache = _load_list_url_cache(cache_path)
    cache[list_name] = _strip_tracking_query(url)
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


class BrowserClient:
    """Playwright を使って Medium 記事を取得するクライアント"""

    def __init__(self, config: Config):
        self.config = config
        self.session_path = config.session_path
        self.list_url_cache_path = config.session_path.parent / ".medium-list-cache.json"
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def initialize(self) -> None:
        """ブラウザを起動して初期化"""
        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(
            headless=self.config.headless,
            slow_mo=100 if not self.config.headless else 0,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        # 保存済みセッションを読み込み
        storage_state = None
        if self.session_path.exists():
            try:
                storage_state = json.loads(self.session_path.read_text())
                log.step("保存済みセッションを読み込みました")
            except Exception:
                log.warn("セッションファイルの読み込みに失敗。新規セッションを使用します")

        self._context = await self._browser.new_context(
            **self._build_context_options(storage_state)
        )
        self._page = await self._context.new_page()

    def _build_context_options(self, storage_state: dict | None = None) -> dict:
        """new_context() に渡すオプションを構築する（共通化のため抽出）"""
        opts = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            # Cloudflare は IP の地域とブラウザの locale/timezone の整合性も見ている
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
        }
        if storage_state is not None:
            opts["storage_state"] = storage_state
        return opts

    async def _refresh_context(self) -> None:
        """現在のコンテキストを閉じて、同じオプションで新しいコンテキストを作り直す。

        ヘッドレス時に Medium のリストページを閲覧した後、Cloudflare がそのコンテキスト
        を bot として flag する挙動が観測されたため、リスト取得後に context を一度
        破棄して fresh な状態で記事ページにアクセスする。

        重要: 引き継ぐ storage_state は **ディスクに保存された session.json**
        （ログイン時点の状態）であり、ランタイム中に蓄積した cookies は捨てる。
        Cloudflare が付与する `cf_clearance` 等の flag cookie を引き継ぐと意味がない。
        """
        if not self._browser or not self._context:
            return
        # 元の session.json を再ロード（ランタイム蓄積 cookie は破棄）
        storage_state = None
        if self.session_path.exists():
            try:
                storage_state = json.loads(self.session_path.read_text())
            except Exception:
                pass
        await self._context.close()
        self._context = await self._browser.new_context(
            **self._build_context_options(storage_state)
        )
        self._page = await self._context.new_page()
        log.step("ブラウザコンテキストを再生成しました（Cloudflare 回避）")

    async def ensure_login(self) -> bool:
        """Medium にログインしているか確認。未ログインなら手動ログインを促す（GUIモード専用）"""
        if not self._page:
            raise RuntimeError("ブラウザが初期化されていません")

        # headless モードでは手動ログイン不可
        if self.config.headless:
            log.warn(
                "headless モードではログインできません。\n"
                "  → 初回は --gui モードで実行してセッションを保存してください:\n"
                "    medium-notion translate --url '...' --gui"
            )
            return False

        log.step("Medium のログイン状態を確認中...")
        try:
            await self._page.goto("https://medium.com", timeout=15000)
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.warn("Medium トップページの読み込みがタイムアウトしました。続行します")
            return False

        # ログイン判定
        for selector in LOGIN_SELECTORS:
            try:
                await self._page.wait_for_selector(selector, timeout=3000)
                log.success("Medium にログイン済みです")
                await self._save_session()
                return True
            except Exception:
                continue

        # 未ログイン → 手動ログインを促す
        log.warn("Medium にログインしていません。ブラウザでログインしてください")
        log.step("ログインページを開いています...")
        await self._page.goto("https://medium.com/m/signin")

        print("\n" + "=" * 60)
        print("  Medium ログイン手順:")
        print("  1. 開いたブラウザで「Sign in with email」を選択")
        print("  2. メールアドレス/パスワードでログイン")
        print("     ※ Google ログインは非対応です")
        print("  3. ログイン完了後、自動的に続行します")
        print("  (最大5分間待機します)")
        print("=" * 60 + "\n")

        try:
            await self._page.wait_for_selector(
                ", ".join(LOGIN_SELECTORS), timeout=300_000
            )
            log.success("ログイン成功！セッションを保存します")
            await self._save_session()
            return True
        except Exception:
            log.error("ログインがタイムアウトしました")
            return False

    async def fetch_article(self, url: str) -> MediumArticle:
        """Medium 記事の全文を取得"""
        if not self._page:
            raise RuntimeError("ブラウザが初期化されていません")

        log.step(f"記事を取得中: {url}")

        # セッション必須チェック
        if not self.session_path.exists():
            raise RuntimeError(
                "Medium のログインセッションがありません。\n"
                "  → 先に `medium-notion login` を実行してログインしてください。"
            )
        log.step("保存済みセッションを使用")

        # ヘッドレスでは記事ごとに context をリフレッシュする。
        # 同一 context で複数 Medium ページを叩くと Cloudflare に bot 判定されるため、
        # 各記事を「最初の 1 リクエスト」として扱うのが最も安定する。
        if self.config.headless:
            await self._refresh_context()

        # 記事ページにアクセス
        response = await self._page.goto(url, wait_until="domcontentloaded")

        # --- 早期バリデーション: HTTP ステータスコード ---
        if response and response.status >= 400:
            raise RuntimeError(
                f"ページの取得に失敗しました (HTTP {response.status})。URLが正しいか確認してください。"
            )

        try:
            await self._page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            log.warn("networkidle タイムアウト — 読み込み完了前に続行します")

        # --- 早期バリデーション: 404 / 無効ページ検出 ---
        page_validation = await self._page.evaluate("""
            () => {
                const title = document.title || '';
                const bodyText = (document.body.textContent || '').toLowerCase();
                const url = window.location.href;

                // 404 検出パターン
                const is404 = (
                    title === 'Medium' ||
                    bodyText.includes('page not found') ||
                    bodyText.includes('404') && bodyText.includes('not found') ||
                    bodyText.includes('this page doesn') ||
                    bodyText.includes('out of nothing, something') ||
                    url.includes('/404')
                );

                // 記事ページかどうかの基本チェック
                const hasArticleStructure = !!(
                    document.querySelector('article') ||
                    document.querySelector('[data-testid="storyTitle"]') ||
                    document.querySelector('h1')
                );

                return {
                    title: title,
                    is404: is404,
                    hasArticleStructure: hasArticleStructure,
                    finalUrl: url,
                };
            }
        """)

        if page_validation.get("is404") and not page_validation.get("hasArticleStructure"):
            raise RuntimeError(
                f"記事が見つかりません (404)。URLが正しいか確認してください。\n"
                f"  入力URL: {url}\n"
                f"  最終URL: {page_validation.get('finalUrl')}"
            )

        # 記事コンテナが描画されるまで待機（最大10秒）
        container_found = False
        for selector in ARTICLE_CONTAINER_SELECTORS:
            try:
                await self._page.wait_for_selector(selector, timeout=5000)
                log.step(f"記事コンテナ検出: {selector}")
                container_found = True
                break
            except Exception:
                continue

        if not container_found:
            log.warn("記事コンテナが見つかりません — ページ構造が想定と異なる可能性があります")

        # 遅延ロードされるコンテンツのため追加待機
        await self._page.wait_for_timeout(3000)

        # スクロールして遅延読み込みコンテンツをトリガー
        await self._page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                for (let i = 0; i < 5; i++) {
                    window.scrollBy(0, window.innerHeight);
                    await delay(500);
                }
                window.scrollTo(0, 0);
            }
        """)

        # タイトル取得
        title = await self._extract_title()

        # 著者取得
        author = await self._extract_author()

        # 本文取得
        content, is_preview = await self._extract_content()

        if not content:
            raise RuntimeError(
                "記事の本文を取得できませんでした。ペイウォールの可能性があります。\n"
                "  ヒント: --headless を外してブラウザ表示モードで試してください。"
            )

        article = MediumArticle(
            url=url,
            title=title,
            content=content,
            author=author,
            is_preview_only=is_preview,
        )

        log.success(
            f"記事取得完了: 「{title}」({article.char_count}文字)"
            + (" [プレビューのみ]" if is_preview else "")
        )

        return article

    async def _check_login_quick(self) -> bool:
        """素早くログイン状態を確認（タイムアウト付き）"""
        if not self.session_path.exists():
            return False
        try:
            await self._page.goto("https://medium.com", timeout=15000)
            await self._page.wait_for_load_state("networkidle", timeout=10000)
            for selector in LOGIN_SELECTORS[:2]:
                try:
                    await self._page.wait_for_selector(selector, timeout=2000)
                    return True
                except Exception:
                    continue
        except Exception:
            log.warn("ログイン状態の確認がタイムアウトしました")
        return False

    async def _extract_title(self) -> str:
        """記事タイトルを抽出"""
        selectors = [
            "article h1",
            "h1[data-testid='storyTitle']",
            ".graf--title",
            "h1",
        ]
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=2000)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return "Untitled"

    async def _extract_author(self) -> str:
        """記事の著者を抽出"""
        selectors = [
            "[data-testid='authorName']",
            "a[rel='author']",
            ".pw-author-name",
        ]
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=2000)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    async def _extract_content(self) -> tuple[str, bool]:
        """
        記事本文を抽出。DOM を走査してマークダウン形式に変換する。
        戻り値: (マークダウンテキスト, プレビューのみかどうか)
        """
        # JavaScript で DOM を走査し、マークダウン形式で抽出
        extract_js = """
        (containerSelectors) => {
            // コンテナを探す
            let container = null;
            for (const sel of containerSelectors) {
                container = document.querySelector(sel);
                if (container) break;
            }
            if (!container) return { markdown: '', selector: '', debug: 'No container found' };

            const usedSelector = containerSelectors.find(s => document.querySelector(s));

            // 抽出対象の要素を再帰的に走査
            const lines = [];
            const seen = new Set();

            function processNode(node) {
                if (!node) return;

                // テキストノード
                if (node.nodeType === 3) {
                    const text = node.textContent?.trim();
                    if (text) lines.push({ type: 'text', content: text });
                    return;
                }

                if (node.nodeType !== 1) return;  // Element ノード以外スキップ

                const tag = node.tagName?.toLowerCase();
                const text = node.textContent?.trim() || '';

                // ナビゲーション、ボタン、フッターなどスキップ
                if (['nav', 'footer', 'header', 'button', 'aside', 'script',
                     'style', 'noscript', 'iframe', 'svg'].includes(tag)) return;

                // data-testid で非コンテンツ要素をスキップ
                const testId = node.getAttribute('data-testid') || '';
                if (['headerNav', 'postMetaLockup', 'storyFooter',
                     'publicationHeader'].includes(testId)) return;

                // 重複防止
                const key = tag + ':' + text.substring(0, 80);
                if (seen.has(key) && text.length < 200) return;
                seen.add(key);

                // 見出し
                if (['h1', 'h2', 'h3', 'h4'].includes(tag) && text.length > 0) {
                    const level = '#'.repeat(parseInt(tag[1]));
                    lines.push({ type: 'heading', content: level + ' ' + text });
                    return;
                }

                // コードブロック (pre > code)
                if (tag === 'pre') {
                    const code = node.querySelector('code');
                    const codeText = code ? code.textContent : text;
                    if (codeText?.trim()) {
                        lines.push({ type: 'code', content: '```\\n' + codeText.trim() + '\\n```' });
                    }
                    return;
                }

                // インラインコード
                if (tag === 'code' && node.parentElement?.tagName?.toLowerCase() !== 'pre') {
                    // インラインコードは親要素の処理に含まれる
                    return;
                }

                // ブロック引用
                if (tag === 'blockquote') {
                    if (text) {
                        const quoted = text.split('\\n').map(l => '> ' + l.trim()).join('\\n');
                        lines.push({ type: 'blockquote', content: quoted });
                    }
                    return;
                }

                // リスト
                if (tag === 'ul' || tag === 'ol') {
                    const items = node.querySelectorAll(':scope > li');
                    items.forEach((li, i) => {
                        const prefix = tag === 'ol' ? (i + 1) + '. ' : '- ';
                        const liText = li.textContent?.trim();
                        if (liText) {
                            lines.push({ type: 'list', content: prefix + liText });
                        }
                    });
                    return;
                }

                // 画像（alt テキスト / figcaption）
                if (tag === 'figure') {
                    const img = node.querySelector('img');
                    const caption = node.querySelector('figcaption');
                    const alt = img?.getAttribute('alt') || '';
                    const capText = caption?.textContent?.trim() || '';
                    if (alt || capText) {
                        lines.push({ type: 'image', content: '[画像: ' + (capText || alt) + ']' });
                    }
                    return;
                }

                // 段落
                if (tag === 'p') {
                    if (text && text.length > 5) {
                        // インラインコードを `` で囲む
                        let md = '';
                        node.childNodes.forEach(child => {
                            if (child.nodeType === 3) {
                                md += child.textContent;
                            } else if (child.tagName?.toLowerCase() === 'code') {
                                md += '`' + child.textContent + '`';
                            } else if (child.tagName?.toLowerCase() === 'strong' ||
                                       child.tagName?.toLowerCase() === 'b') {
                                md += '**' + child.textContent + '**';
                            } else if (child.tagName?.toLowerCase() === 'em' ||
                                       child.tagName?.toLowerCase() === 'i') {
                                md += '*' + child.textContent + '*';
                            } else if (child.tagName?.toLowerCase() === 'a') {
                                const href = child.getAttribute('href') || '';
                                md += '[' + child.textContent + '](' + href + ')';
                            } else {
                                md += child.textContent || '';
                            }
                        });
                        lines.push({ type: 'paragraph', content: md.trim() });
                    }
                    return;
                }

                // div / section: 再帰的に子要素を処理
                if (['div', 'section', 'main', 'article', 'span'].includes(tag)) {
                    node.childNodes.forEach(child => processNode(child));
                    return;
                }
            }

            processNode(container);

            // マークダウンに変換
            const markdown = lines
                .filter(l => l.content.trim().length > 0)
                .map(l => l.content)
                .join('\\n\\n');

            return {
                markdown: markdown,
                selector: usedSelector || 'none',
                lineCount: lines.length,
                debug: 'OK'
            };
        }
        """

        result = await self._page.evaluate(
            extract_js,
            ARTICLE_CONTAINER_SELECTORS,
        )

        if not result or not result.get("markdown"):
            # デバッグ情報を出力
            log.warn(f"コンテンツ抽出失敗 — debug: {result.get('debug', 'N/A')}")
            # ページのHTMLの一部をログに出力してデバッグ
            debug_info = await self._page.evaluate("""
                () => {
                    const body = document.body;
                    const tags = {};
                    body.querySelectorAll('*').forEach(el => {
                        const tag = el.tagName.toLowerCase();
                        tags[tag] = (tags[tag] || 0) + 1;
                    });
                    // 上位10タグを返す
                    const sorted = Object.entries(tags)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 15);
                    return {
                        url: window.location.href,
                        title: document.title,
                        topTags: sorted,
                        articleExists: !!document.querySelector('article'),
                        mainExists: !!document.querySelector('main'),
                        bodyTextLen: body.textContent?.length || 0,
                    };
                }
            """)
            log.warn(f"ページ情報: URL={debug_info.get('url')}, title={debug_info.get('title')}")
            log.warn(f"  article要素: {debug_info.get('articleExists')}, main要素: {debug_info.get('mainExists')}")
            log.warn(f"  bodyテキスト長: {debug_info.get('bodyTextLen')}")
            log.warn(f"  上位タグ: {debug_info.get('topTags')}")

            # フォールバック: body 全体からテキスト抽出を試みる
            fallback_text = await self._page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        { acceptNode: (node) => {
                            const parent = node.parentElement;
                            if (!parent) return NodeFilter.FILTER_REJECT;
                            const tag = parent.tagName.toLowerCase();
                            if (['script','style','nav','footer','button','noscript'].includes(tag))
                                return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }}
                    );
                    const texts = [];
                    let node;
                    while (node = walker.nextNode()) {
                        const t = node.textContent?.trim();
                        if (t && t.length > 10) texts.push(t);
                    }
                    return texts.join('\\n\\n');
                }
            """)

            if fallback_text and len(fallback_text) > 200:
                log.warn(f"フォールバック抽出を使用（{len(fallback_text)}文字）")
                is_preview = await self._check_paywall()
                return fallback_text[:15000], True

            return "", False

        content = result["markdown"]
        log.step(
            f"セレクタ「{result.get('selector')}」で {result.get('lineCount', 0)} ブロックを抽出"
            f"（{len(content)}文字）"
        )
        is_preview = await self._check_paywall()
        return content, is_preview

    async def _check_paywall(self) -> bool:
        """ペイウォールが表示されているか確認"""
        page_text = await self._page.evaluate(
            "document.body.textContent?.toLowerCase() || ''"
        )
        for indicator in PAYWALL_INDICATORS:
            if indicator in page_text:
                log.warn(f"ペイウォール検出: {indicator}")
                return True
        return False

    async def _save_session(self) -> None:
        """ブラウザセッションをファイルに保存"""
        if not self._context:
            return
        try:
            state = await self._context.storage_state()
            self.session_path.write_text(json.dumps(state, indent=2))
            log.step("セッションを保存しました")
        except Exception as e:
            log.warn(f"セッション保存に失敗: {e}")

    async def _wait_past_cloudflare(self, timeout_ms: int = 30_000) -> bool:
        """Cloudflare のインタースティシャル画面が出ていたら通過するまで待つ

        Returns:
            通過できた場合 True、タイムアウト時は False（呼び出し側は処理を継続）
        """
        if not self._page:
            return False

        title = await self._page.title()
        if not _is_cloudflare_challenge(title):
            return True

        log.warn(
            f"Cloudflare チャレンジを検出: title='{title}' — 通過待ち（最大 {timeout_ms // 1000} 秒）"
        )

        # title が変わるか、タイムアウトするまでポーリング
        elapsed = 0
        poll_ms = 1000
        while elapsed < timeout_ms:
            await self._page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
            try:
                current_title = await self._page.title()
            except Exception:
                continue
            if not _is_cloudflare_challenge(current_title):
                log.success(
                    f"Cloudflare 通過: title='{current_title}' (経過 {elapsed // 1000}s)"
                )
                return True

        log.warn(
            f"Cloudflare チャレンジが {timeout_ms // 1000} 秒以内に通過しませんでした。"
            "—\n  → セッション切れか、IP/UA がブロックされている可能性があります。"
            " GUI モード (--gui) で再試行してください。"
        )
        return False

    async def fetch_reading_list(self, list_name: str = "Reading list") -> list[str]:
        """Medium のリストから記事 URL 一覧を取得

        Args:
            list_name: 取得対象のリスト名。
                       "Reading list" の場合は直接 URL でアクセス。
                       それ以外のカスタムリストの場合はライブラリページから探す。
        """
        if not self._page:
            raise RuntimeError("ブラウザが初期化されていません")

        # セッション必須チェック
        if not self.session_path.exists():
            raise RuntimeError(
                "Medium のログインセッションがありません。\n"
                "  → 先に `medium-notion login` を実行してログインしてください。"
            )

        log.step(f"Medium のリスト「{list_name}」を取得中...")

        # キャッシュ済みのカスタムリスト URL があれば直接 goto する。
        # /me/lists 経由は Cloudflare に scraping パターンとして検出されることがあり、
        # 一度発見した URL を直接叩く方が安定する。
        cached_url: str | None = None
        if list_name.lower() != "reading list":
            cache = _load_list_url_cache(self.list_url_cache_path)
            cached_url = cache.get(list_name)
            if cached_url:
                log.step(f"キャッシュ済みリスト URL を使用: {cached_url}")

        # リストページへの遷移
        if list_name.lower() == "reading list":
            response = await self._page.goto(
                "https://medium.com/me/list/reading-list",
                wait_until="domcontentloaded",
            )
        elif cached_url:
            # 直接 goto。これで /me/lists を経由しない
            response = await self._page.goto(
                cached_url,
                wait_until="domcontentloaded",
            )
        else:
            # キャッシュなし: ライブラリページから探す
            response = await self._page.goto(
                "https://medium.com/me/lists",
                wait_until="domcontentloaded",
            )

        if response and response.status >= 400:
            raise RuntimeError(
                f"ページの取得に失敗しました (HTTP {response.status})。\n"
                "  → ログインセッションが期限切れの可能性があります。\n"
                "  → `medium-notion login` で再ログインしてください。"
            )

        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.warn("networkidle タイムアウト — 読み込み完了前に続行します")

        # Cloudflare チャレンジを検出したら通過するまで待つ
        # JS チャレンジは通常 5〜10 秒で完了するので、最大 30 秒見る
        await self._wait_past_cloudflare(timeout_ms=30_000)

        # ページ検証: ログイン済みか
        page_check = await self._page.evaluate("""
            () => {
                const url = window.location.href;
                return {
                    finalUrl: url,
                    isLoginPage: url.includes('/signin') || url.includes('/login'),
                };
            }
        """)

        if page_check.get("isLoginPage"):
            raise RuntimeError(
                "ログインページにリダイレクトされました。セッションが期限切れです。\n"
                "  → `medium-notion login` で再ログインしてください。"
            )

        # キャッシュ未使用のカスタムリストはライブラリページから探してクリック
        if list_name.lower() != "reading list" and not cached_url:
            await self._navigate_to_custom_list(list_name)
            # ライブラリ経由で見つけた URL を次回以降のためキャッシュに保存
            try:
                discovered_url = await self._page.evaluate("window.location.href")
                if discovered_url and "/list/" in discovered_url:
                    _save_list_url(
                        self.list_url_cache_path, list_name, discovered_url
                    )
                    log.step(
                        f"次回用にリスト URL をキャッシュ: {_strip_tracking_query(discovered_url)}"
                    )
            except Exception as e:
                log.warn(f"リスト URL のキャッシュ保存に失敗: {e}")
            await self._wait_past_cloudflare(timeout_ms=30_000)

        # NOTE: 以前は無限スクロールで全記事をロードしていたが、ヘッドレス時に
        # スクロール操作が Cloudflare の bot 検出に引っかかり、その後の記事ページ
        # アクセスが 403 になる問題が判明。短いリスト（処理対象が常に少数）の
        # ユースケースでは初期 DOM に全件含まれるため、スクロールは省略する。
        # 大量のアイテムを抱えるリストは複数回の実行で順次処理する運用とする。
        if self.config.headless:
            log.step("ヘッドレスではスクロールを省略（Cloudflare 回避）")
        else:
            # GUI モードのみ従来どおりスクロールで lazy-load を吸収
            prev_height = 0
            scroll_attempts = 0
            max_scroll_attempts = 50
            while scroll_attempts < max_scroll_attempts:
                current_height = await self._page.evaluate(
                    "document.body.scrollHeight"
                )
                if current_height == prev_height:
                    break
                prev_height = current_height
                await self._page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await self._page.wait_for_timeout(1500)
                scroll_attempts += 1
            if scroll_attempts > 0:
                log.step(f"スクロール完了（{scroll_attempts} 回）")

        # ページトップに戻る
        await self._page.evaluate("window.scrollTo(0, 0)")

        # JavaScript で DOM から記事 URL を抽出
        urls = await self._page.evaluate("""
            () => {
                const links = [...document.querySelectorAll('a[href]')]
                    .map(a => {
                        try {
                            const url = new URL(a.href);
                            // クエリパラメータとフラグメントを除去
                            return url.origin + url.pathname;
                        } catch {
                            return null;
                        }
                    })
                    .filter(href => {
                        if (!href) return false;
                        try {
                            const url = new URL(href);
                            // Medium ドメインのみ
                            if (url.hostname !== 'medium.com'
                                && !url.hostname.endsWith('.medium.com')) return false;
                            const path = url.pathname;
                            // 明らかに記事でないパスを除外
                            if (path === '/' || path === '/me' || path.startsWith('/me/')
                                || path.startsWith('/m/') || path === '/new-story'
                                || path.startsWith('/plans') || path.startsWith('/membership')
                                || path.startsWith('/tag/') || path.startsWith('/search')
                                || path.startsWith('/creators')
                                || path.includes('/list/')
                                || path.includes('/sitemap')
                                || path.includes('/about')) return false;
                            // /@user/article-slug-hash 形式
                            if (/^\\/@[^/]+\\/[^/]+-[a-f0-9]{8,}/.test(path)) return true;
                            // /publication/article-slug-hash 形式
                            if (/^\\/[^@][^/]*\\/[^/]+-[a-f0-9]{8,}/.test(path)) return true;
                            // /p/hash 形式（短縮URL）
                            if (/^\\/p\\/[a-f0-9]+/.test(path)) return true;
                            return false;
                        } catch {
                            return false;
                        }
                    });
                return [...new Set(links)]; // 重複除去
            }
        """)

        if not urls:
            # フォールバック: より緩いフィルタリングで再試行
            log.warn("厳密なパターンで記事が見つかりません。緩い条件で再試行します...")
            urls = await self._page.evaluate("""
                () => {
                    const links = [...document.querySelectorAll('a[href]')]
                        .map(a => {
                            try {
                                const url = new URL(a.href);
                                return url.origin + url.pathname;
                            } catch {
                                return null;
                            }
                        })
                        .filter(href => {
                            if (!href) return false;
                            try {
                                const url = new URL(href);
                                if (url.hostname !== 'medium.com'
                                    && !url.hostname.endsWith('.medium.com')) return false;
                                const path = url.pathname;
                                // 短いパスや明らかなナビリンクを除外
                                if (path === '/' || path.split('/').length < 3) return false;
                                if (path.startsWith('/me/') || path.startsWith('/m/')
                                    || path.startsWith('/tag/') || path.startsWith('/search')
                                    || path.startsWith('/plans') || path.startsWith('/membership')
                                    || path === '/new-story'
                                    || path.includes('/list/')
                                    || path.includes('/sitemap')
                                    || path.includes('/about')) return false;
                                return true;
                            } catch {
                                return false;
                            }
                        });
                    return [...new Set(links)];
                }
            """)

            if not urls:
                # デバッグ情報を出力
                debug_info = await self._page.evaluate("""
                    () => {
                        const allLinks = [...document.querySelectorAll('a[href]')]
                            .map(a => a.href)
                            .slice(0, 30);
                        return {
                            url: window.location.href,
                            title: document.title,
                            totalLinks: document.querySelectorAll('a[href]').length,
                            sampleLinks: allLinks,
                            bodyTextLen: document.body.textContent?.length || 0,
                        };
                    }
                """)
                log.warn(f"ページ情報: URL={debug_info.get('url')}")
                log.warn(f"  title: {debug_info.get('title')}")
                log.warn(f"  リンク総数: {debug_info.get('totalLinks')}")
                log.warn(f"  サンプルリンク: {debug_info.get('sampleLinks', [])[:10]}")

        log.success(f"リスト「{list_name}」から {len(urls)} 件の記事 URL を取得しました")

        # ヘッドレスでリストページを閲覧した後、Cloudflare がコンテキストを flag して
        # 後続の記事ページアクセスが 403 になるため、URL 取得が完了したら context を
        # 破棄して fresh な状態に戻す（記事ページ取得が成功するように）
        if self.config.headless and urls:
            await self._refresh_context()

        return urls

    async def _navigate_to_custom_list(self, list_name: str) -> None:
        """ライブラリページからカスタムリストを探してクリック遷移する"""
        log.step(f"ライブラリからリスト「{list_name}」を検索中...")

        # 方法1: ページ内の全 <a> タグから /list/ を含む href を探し、
        #        その周辺テキストにリスト名が含まれるものを見つける
        result = await self._page.evaluate("""
            (targetName) => {
                const targetLower = targetName.toLowerCase();

                // 全リンクからリスト URL を収集
                const listLinks = [...document.querySelectorAll('a[href]')]
                    .filter(a => {
                        const href = a.href || '';
                        return href.includes('/list/');
                    })
                    .map(a => ({
                        href: a.href,
                        text: a.textContent?.trim() || '',
                        // リスト名がリンク自体か、その親要素に含まれるか
                        parentText: a.closest('div, section, article')?.textContent?.trim() || '',
                    }));

                // リスト名に完全一致するリンクを探す
                for (const link of listLinks) {
                    if (link.text === targetName
                        || link.parentText.includes(targetName)) {
                        // /list/reading-list は除外
                        if (link.href.includes('/list/reading-list')) continue;
                        return { found: true, href: link.href };
                    }
                }

                // href にリスト名（小文字）を含むリンクを探す
                for (const link of listLinks) {
                    if (link.href.toLowerCase().includes(targetLower)) {
                        return { found: true, href: link.href };
                    }
                }

                // 利用可能なリスト名を収集（エラーメッセージ用）
                const listNames = [];
                const headings = document.querySelectorAll('h2, h3, h4');
                headings.forEach(el => {
                    const t = el.textContent?.trim();
                    if (t && t.length > 0 && t.length < 100) listNames.push(t);
                });
                // リンクテキストからも収集
                listLinks.forEach(link => {
                    if (link.text && !listNames.includes(link.text)) {
                        listNames.push(link.text);
                    }
                });

                return {
                    found: false,
                    availableLists: listNames,
                    debugLinks: listLinks.map(l => l.href).slice(0, 10),
                };
            }
        """, list_name)

        if not result.get("found"):
            available = result.get("availableLists", [])
            available_str = "、".join(f"「{n}」" for n in available) if available else "（不明）"
            debug_links = result.get("debugLinks", [])
            log.warn(f"検出された /list/ リンク: {debug_links}")
            raise RuntimeError(
                f"リスト「{list_name}」が見つかりません。\n"
                f"  利用可能なリスト: {available_str}\n"
                f"  → リスト名を確認して --list オプションで指定してください。"
            )

        # 見つかった URL に直接遷移
        href = result["href"]
        log.step(f"リスト「{list_name}」に遷移中: {href}")
        await self._page.goto(href, wait_until="domcontentloaded")

        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.warn("networkidle タイムアウト — 続行します")

        # 遷移後の URL を確認
        current_url = await self._page.evaluate("window.location.href")
        log.step(f"遷移先: {current_url}")

        # 遷移確認: /list/ を含む URL に遷移できたか
        if "/list/" not in current_url and list_name.lower() not in current_url.lower():
            log.warn(f"リストページへの遷移に失敗した可能性があります（URL: {current_url}）")

    async def remove_articles_from_list(
        self,
        list_name: str,
        urls_to_remove: list[str],
    ) -> tuple[list[str], list[str]]:
        """Medium のリストから指定した記事を削除する

        Args:
            list_name: 対象リスト名
            urls_to_remove: 削除する記事の URL リスト

        Returns:
            (成功した URL リスト, 失敗した URL リスト)
        """
        if not self._page:
            raise RuntimeError("ブラウザが初期化されていません")

        if not urls_to_remove:
            return [], []

        log.step(f"リスト「{list_name}」から {len(urls_to_remove)} 件の記事を削除中...")

        # ヘッドレスでは直前の記事取得で蓄積した Cloudflare flag をリセットしてから
        # ライブラリページに遷移する（フレッシュなコンテキストで開始）
        if self.config.headless:
            await self._refresh_context()

        # リスト名を保持（_remove_single_article で参照）
        self._current_list_name = list_name

        succeeded: list[str] = []
        failed: list[str] = []

        for i, url in enumerate(urls_to_remove):
            # ヘッドレスでは前回のクリック試行で生まれた popover/Cloudflare 状態が
            # 次の iteration に持ち越されることがあるので、毎回 context をリフレッシュ
            if self.config.headless:
                await self._refresh_context()
            # 毎回リストページに遷移して DOM を最新にする
            # （前の記事の削除で DOM が変わるため）
            await self._navigate_to_list_page(list_name)

            # スクロールして全記事を読み込み
            await self._scroll_to_load_all()
            await self._page.evaluate("window.scrollTo(0, 0)")
            await self._page.wait_for_timeout(1000)

            try:
                removed = await self._remove_single_article(url)
                if removed:
                    succeeded.append(url)
                    log.step(f"  ✓ 削除: {url[:60]}...")
                else:
                    failed.append(url)
                    log.warn(f"  ✗ 見つからず: {url[:60]}...")
            except Exception as e:
                failed.append(url)
                log.warn(f"  ✗ 削除失敗: {url[:60]}... ({e})")

            # 操作間のインターバル
            if i < len(urls_to_remove) - 1:
                await self._page.wait_for_timeout(1500)

        log.success(
            f"リスト削除完了: 成功 {len(succeeded)} 件, 失敗 {len(failed)} 件"
        )
        return succeeded, failed

    async def _navigate_to_list_page(self, list_name: str) -> None:
        """リストページに遷移する（共通処理）"""
        if list_name.lower() == "reading list":
            await self._page.goto(
                "https://medium.com/me/list/reading-list",
                wait_until="domcontentloaded",
            )
        else:
            # キャッシュ済みなら /me/lists を経由せず直接 goto
            # （Cloudflare の scraping 検出を避けるため）
            cache = _load_list_url_cache(self.list_url_cache_path)
            cached_url = cache.get(list_name)
            if cached_url:
                await self._page.goto(cached_url, wait_until="domcontentloaded")
            else:
                await self._page.goto(
                    "https://medium.com/me/lists",
                    wait_until="domcontentloaded",
                )
                try:
                    await self._page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await self._navigate_to_custom_list(list_name)

        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    async def _scroll_to_load_all(self) -> None:
        """無限スクロールで全コンテンツを読み込む

        ヘッドレス時はスクロール操作が Cloudflare の bot 検出を引き起こすため省略する
        （短いリスト前提）。
        """
        if self.config.headless:
            return
        prev_height = 0
        for _ in range(50):
            current_height = await self._page.evaluate("document.body.scrollHeight")
            if current_height == prev_height:
                break
            prev_height = current_height
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._page.wait_for_timeout(1500)

    async def _remove_single_article(self, url: str) -> bool:
        """リストページから1件の記事を削除する

        方式: ブックマークボタンをクリック → リストピッカーで対象リストのチェックを解除
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        url_path = parsed.path

        # Step 1: 記事リンクを見つけてカードをスクロール表示
        card_info = await self._page.evaluate("""
            (urlPath) => {
                const links = [...document.querySelectorAll('a[href]')];
                for (const link of links) {
                    try {
                        const linkUrl = new URL(link.href);
                        if (linkUrl.pathname !== urlPath) continue;

                        // 記事カードのコンテナを見つける
                        let card = link;
                        for (let i = 0; i < 15; i++) {
                            if (!card.parentElement) break;
                            card = card.parentElement;
                            const hasMultipleLinks = card.querySelectorAll('a[href]').length >= 2;
                            const hasButton = card.querySelector('button');
                            if (hasMultipleLinks && hasButton
                                && card.offsetHeight > 80
                                && card.offsetHeight < 600) {
                                break;
                            }
                        }

                        // カードをビューポート中央にスクロール
                        card.scrollIntoView({ behavior: 'instant', block: 'center' });

                        const rect = card.getBoundingClientRect();
                        return {
                            found: true,
                            x: Math.round(rect.x + rect.width / 2),
                            y: Math.round(rect.y + rect.height / 2),
                        };
                    } catch {}
                }
                return { found: false };
            }
        """, url_path)

        if not card_info.get("found"):
            log.warn("記事カードが見つかりません")
            return False

        # Step 2: ブックマークボタンを見つけてクリック
        bookmark_btn = await self._page.evaluate("""
            (urlPath) => {
                const links = [...document.querySelectorAll('a[href]')];
                for (const link of links) {
                    try {
                        const linkUrl = new URL(link.href);
                        if (linkUrl.pathname !== urlPath) continue;

                        let card = link;
                        for (let i = 0; i < 15; i++) {
                            if (!card.parentElement) break;
                            card = card.parentElement;
                            const hasMultipleLinks = card.querySelectorAll('a[href]').length >= 2;
                            const hasButton = card.querySelector('button');
                            if (hasMultipleLinks && hasButton
                                && card.offsetHeight > 80
                                && card.offsetHeight < 600) {
                                break;
                            }
                        }

                        const buttons = [...card.querySelectorAll('button')];
                        for (const btn of buttons) {
                            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                            if (label.includes('bookmark') || label.includes('save')
                                || label.includes('list')) {
                                // 座標取得前にボタン自体もビューポート内に入れる
                                btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                const rect = btn.getBoundingClientRect();
                                return {
                                    found: true,
                                    x: Math.round(rect.x + rect.width / 2),
                                    y: Math.round(rect.y + rect.height / 2),
                                    label: label,
                                };
                            }
                        }
                        // aria-label なしでも SVG を含む小さいボタンを試す
                        for (const btn of buttons) {
                            const hasSvg = btn.querySelector('svg');
                            const rect = btn.getBoundingClientRect();
                            if (hasSvg && rect.width > 0 && rect.width < 60
                                && rect.height > 0 && rect.height < 60) {
                                btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                const r2 = btn.getBoundingClientRect();
                                return {
                                    found: true,
                                    x: Math.round(r2.x + r2.width / 2),
                                    y: Math.round(r2.y + r2.height / 2),
                                    label: btn.getAttribute('aria-label') || '(svg-button)',
                                };
                            }
                        }
                        return { found: false, debug: buttons.map(b =>
                            b.getAttribute('aria-label') || b.textContent?.trim()?.substring(0, 20) || '?'
                        ) };
                    } catch {}
                }
                return { found: false };
            }
        """, url_path)

        if not bookmark_btn or not bookmark_btn.get("found"):
            log.warn(f"ブックマークボタンが見つかりません: {bookmark_btn.get('debug', [])}")
            return False

        log.step(f"ブックマークボタンをクリック: {bookmark_btn.get('label', '')}")
        # Playwright の Locator.click() は CDP を経由して isTrusted=true なクリックを生成する。
        # JS 内の dispatchEvent / element.click() は isTrusted=false で
        # Medium の popover 表示ロジックを通らないことがあるため、ここは
        # ElementHandle 経由で .click() を呼ぶのが筋。
        clicked_via_handle = False
        try:
            handle = await self._page.evaluate_handle(
                """
                (urlPath) => {
                    const links = [...document.querySelectorAll('a[href]')];
                    for (const link of links) {
                        try {
                            const linkUrl = new URL(link.href);
                            if (linkUrl.pathname !== urlPath) continue;
                            let card = link;
                            for (let i = 0; i < 15; i++) {
                                if (!card.parentElement) break;
                                card = card.parentElement;
                                const hasMultipleLinks =
                                    card.querySelectorAll('a[href]').length >= 2;
                                const hasButton = card.querySelector('button');
                                if (hasMultipleLinks && hasButton
                                    && card.offsetHeight > 80
                                    && card.offsetHeight < 600) break;
                            }
                            const buttons = [...card.querySelectorAll('button')];
                            const labelMatch = buttons.find(b => {
                                const lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                                return lbl.includes('bookmark') || lbl.includes('save')
                                    || lbl.includes('list');
                            });
                            const svgMatch = buttons.find(b => {
                                const r = b.getBoundingClientRect();
                                return b.querySelector('svg')
                                    && r.width > 0 && r.width < 60
                                    && r.height > 0 && r.height < 60;
                            });
                            return labelMatch || svgMatch || null;
                        } catch {}
                    }
                    return null;
                }
                """,
                url_path,
            )
            element = handle.as_element()
            if element:
                await element.scroll_into_view_if_needed()
                await element.click(timeout=5000)
                clicked_via_handle = True
                await handle.dispose()
            else:
                await handle.dispose()
        except Exception as e:
            log.warn(f"ElementHandle クリックに失敗、座標クリックにフォールバック: {e}")

        if not clicked_via_handle:
            # フォールバック: 座標ベースのクリック（trusted ではない）
            await self._page.mouse.move(bookmark_btn["x"], bookmark_btn["y"])
            await self._page.wait_for_timeout(150)
            await self._page.mouse.click(bookmark_btn["x"], bookmark_btn["y"])

        # ヘッドレスでは popover アニメーション完了に時間がかかるため長めに待つ
        wait_ms = 5000 if self.config.headless else 2000
        await self._page.wait_for_timeout(wait_ms)

        # Step 3: リストピッカー内でチェック済みの対象リストをクリックしてトグル OFF
        toggled = await self._page.evaluate("""
            (listName) => {
                const targetLower = listName.toLowerCase();

                // 「リスト名と完全一致するテキストの可視要素」を popover 内で探す。
                // 注意: 「リストページにいるとき」はページの H1 等にも同じテキストが
                // 存在するため、単純な textContent 一致だと H1 をクリックしてしまい
                // 削除されない。popover らしさ (positioned ancestor + 小サイズ + 非見出し)
                // をフィルタとして付ける。
                const isHeadingTag = (el) => {
                    const t = (el.tagName || '').toLowerCase();
                    return t === 'h1' || t === 'h2' || t === 'h3' || t === 'h4';
                };
                const hasPositionedAncestor = (el) => {
                    let cur = el.parentElement;
                    let depth = 0;
                    while (cur && depth < 20) {
                        const s = window.getComputedStyle(cur);
                        if (s.position === 'fixed' || s.position === 'absolute') {
                            const z = parseInt(s.zIndex) || 0;
                            // popover は通常それなり以上の stacking context を持つ
                            if (z >= 1 || s.position === 'fixed') return true;
                        }
                        cur = cur.parentElement;
                        depth += 1;
                    }
                    return false;
                };

                // 候補を集めてスコアを付ける（popover エントリらしさ）
                const candidates = [];
                const allEls = [...document.querySelectorAll('div, li, label, span, button')];
                for (const el of allEls) {
                    const t = (el.textContent || '').trim();
                    if (t !== listName && t.toLowerCase() !== targetLower) continue;
                    if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
                    if (isHeadingTag(el)) continue;
                    // 親に H1/H2/H3 があるなら除外（見出しの内側の span 等）
                    if (el.closest && el.closest('h1,h2,h3,h4')) continue;
                    const r = el.getBoundingClientRect();
                    // popover エントリは小さい矩形 (高さ ~ 24-80 px、幅 ~ 100-500 px)
                    if (r.height > 100 || r.width > 600) continue;
                    if (!hasPositionedAncestor(el)) continue;
                    candidates.push({ el, area: r.width * r.height });
                }

                // 最も小さい矩形 = popover の row 候補
                candidates.sort((a, b) => a.area - b.area);
                if (candidates.length > 0) {
                    let row = candidates[0].el;
                    // 4 階層上までクリック可能な行を探す
                    for (let i = 0; i < 5; i++) {
                        if (!row.parentElement) break;
                        const r = row.getBoundingClientRect();
                        if (r.height >= 24 && r.height <= 80
                            && r.width >= 80 && r.width <= 500) break;
                        row = row.parentElement;
                    }
                    row.click();
                    return { clicked: true, via: 'popover-scoped', text: candidates[0].el.textContent?.trim() };
                }

                // 従来ロジック: オーバーレイから探す（後方互換）
                const overlays = [...document.querySelectorAll('*')].filter(el => {
                    const style = window.getComputedStyle(el);
                    const zIndex = parseInt(style.zIndex) || 0;
                    const pos = style.position;
                    const rect = el.getBoundingClientRect();
                    return (zIndex > 10 || pos === 'fixed' || pos === 'absolute')
                        && rect.width > 100 && rect.width < 500
                        && rect.height > 50 && rect.height < 600
                        && rect.top >= 0 && rect.top < window.innerHeight;
                });

                for (const overlay of overlays) {
                    const overlayText = (overlay.textContent || '').toLowerCase();
                    if (!overlayText.includes(targetLower)) continue;

                    // オーバーレイ内のすべての要素をフラットに取得
                    const allChildren = [...overlay.querySelectorAll('*')];

                    // 方法1: チェックボックスを探す
                    for (const el of allChildren) {
                        if (el.tagName.toLowerCase() === 'input'
                            && el.type === 'checkbox') {
                            const parent = el.closest('div, label, li');
                            if (parent) {
                                const pText = (parent.textContent || '').toLowerCase();
                                if (pText.includes(targetLower)) {
                                    el.click();
                                    return { clicked: true, via: 'checkbox', text: pText.trim() };
                                }
                            }
                        }
                    }

                    // 方法2: リスト名テキストに完全一致する要素の行をクリック
                    for (const el of allChildren) {
                        const text = (el.textContent || '').trim();
                        const elLower = text.toLowerCase();
                        if (elLower === targetLower || text === listName) {
                            const row = el.closest('div, li, label')
                                || el.parentElement;
                            if (row) {
                                row.click();
                                return { clicked: true, via: 'text-row', text: text };
                            }
                            el.click();
                            return { clicked: true, via: 'text-direct', text: text };
                        }
                    }

                    // 方法3: リスト名で始まるリーフ要素をクリック
                    for (const el of allChildren) {
                        const text = (el.textContent || '').trim();
                        const elLower = text.toLowerCase();
                        if (elLower.startsWith(targetLower) && text.length < 30
                            && el.children.length === 0) {
                            const row = el.closest('div[role], li, label')
                                || el.parentElement;
                            if (row) {
                                row.click();
                                return { clicked: true, via: 'leaf-row', text: text };
                            }
                        }
                    }

                    // 方法4: "Locked" 等が付いたリスト名を含む要素を探す
                    for (const el of allChildren) {
                        const text = (el.textContent || '').trim();
                        const elLower = text.toLowerCase();
                        if (elLower.includes(targetLower) && text.length < 50) {
                            // リスト行を見つける: クリック可能な親を探す
                            const clickable = el.closest(
                                'div[role="option"], div[role="button"], li, label'
                            ) || el.closest('div');
                            if (clickable && clickable.offsetHeight > 20
                                && clickable.offsetHeight < 100) {
                                clickable.click();
                                return { clicked: true, via: 'contains-match', text: text };
                            }
                        }
                    }

                    // デバッグ: オーバーレイの中身を出力
                    const debugTexts = allChildren
                        .map(el => {
                            const t = el.textContent?.trim();
                            const tag = el.tagName?.toLowerCase();
                            return t && t.length < 50 && t.length > 0
                                ? tag + ':' + t : null;
                        })
                        .filter(Boolean);
                    const unique = [...new Set(debugTexts)];
                    return { clicked: false, debug: unique.slice(0, 20) };
                }
                return { clicked: false, debug: ['no overlay with list name found'] };
            }
        """, self._current_list_name)

        if not toggled.get("clicked"):
            await self._page.keyboard.press("Escape")
            log.warn(
                f"リストピッカーでのトグルに失敗。"
                f"表示項目: {toggled.get('debug', [])}"
            )
            return False

        log.step(f"リストのチェックを解除: {toggled.get('text', '')} (via {toggled.get('via', '')})")

        # ピッカーを閉じる
        await self._page.wait_for_timeout(800)
        await self._page.keyboard.press("Escape")
        await self._page.wait_for_timeout(1000)
        return True

    async def close(self) -> None:
        """ブラウザを閉じる"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
