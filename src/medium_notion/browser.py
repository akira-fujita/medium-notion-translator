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


class BrowserClient:
    """Playwright を使って Medium 記事を取得するクライアント"""

    def __init__(self, config: Config):
        self.config = config
        self.session_path = config.session_path
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

        context_options = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        # 保存済みセッションを読み込み
        if self.session_path.exists():
            try:
                session_data = json.loads(self.session_path.read_text())
                context_options["storage_state"] = session_data
                log.step("保存済みセッションを読み込みました")
            except Exception:
                log.warn("セッションファイルの読み込みに失敗。新規セッションを使用します")

        self._context = await self._browser.new_context(**context_options)

        # bot 検出回避
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        self._page = await self._context.new_page()

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

    async def close(self) -> None:
        """ブラウザを閉じる"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
