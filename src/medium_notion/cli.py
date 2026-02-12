"""CLI エントリポイント — Click ベース"""

import asyncio
import json
import sys

import click
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import Config, load_config
from .browser import BrowserClient
from .translator import TranslationService
from .notion_client import NotionClient
from . import logger as log

console = Console()

# -h でもヘルプを表示できるようにする
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version="0.1.0")
def cli():
    """Medium → Notion 翻訳パイプライン

    Medium の英語記事を Playwright で取得し、Claude Code CLI で日本語に翻訳して、
    Notion データベースに新規ページとして追加するツールです。

    \b
    ■ できること:
      - Medium 記事（有料記事含む）の全文取得
      - 英語 → 日本語の自動翻訳（見出し・コード・リスト等の構造を保持）
      - カテゴリの自動分類と要約の生成
      - Notion DB への自動登録（タイトル / URL / カテゴリ / スコア / 日付）

    \b
    ■ 必要なもの:
      - Python 3.11+
      - Claude Code CLI（Max プラン）   … 翻訳エンジン
      - Notion API キー & Database ID   … 保存先
      - Medium アカウント（有料会員）    … 記事取得

    \b
    ■ 初回セットアップ（順番に実行）:
      1. medium-notion setup      .env ファイルを対話的に作成
      2. medium-notion login      Medium にブラウザでログイン（セッション保存）
      3. medium-notion test       全接続の状態を確認

    \b
    ■ 記事の翻訳:
      medium-notion translate -u <URL>            記事を翻訳して Notion に追加
      medium-notion translate -u <URL> -s 8       スコア付きで追加
      medium-notion translate -u <URL> --gui      ブラウザを表示して実行

    \b
    ■ 各コマンドの詳細:
      medium-notion <command> -h  でコマンドごとのヘルプを表示
    """
    pass


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--url", "-u",
    required=True,
    help="翻訳する Medium 記事の URL（必須）",
)
@click.option(
    "--score", "-s",
    type=click.IntRange(1, 10),
    default=None,
    help="記事のスコア (1-10)。Notion DB の Score フィールドに設定される",
)
@click.option(
    "--headless/--gui",
    default=None,
    help="ブラウザの表示モード。--headless: バックグラウンド実行（デフォルト）、--gui: ブラウザを表示",
)
def translate(url: str, score: int | None, headless: bool | None):
    """Medium 記事を翻訳して Notion に追加する。

    \b
    事前準備:
      - medium-notion setup  で .env を作成済みであること
      - medium-notion login  で Medium にログイン済みであること

    \b
    例:
      medium-notion translate -u https://medium.com/@user/article-slug-abc123
      medium-notion translate -u https://medium.com/@user/article-slug-abc123 -s 9
      medium-notion translate -u https://medium.com/@user/article-slug-abc123 --gui
    """
    asyncio.run(_translate(url, score, headless))


async def _translate(url: str, score: int | None, headless: bool | None):
    """翻訳パイプラインの実行"""
    console.print(
        Panel(
            f"[bold]Medium → Notion 翻訳パイプライン[/bold]\n{url}",
            style="blue",
        )
    )

    # 1. 設定読み込み
    try:
        config = load_config()
    except ValidationError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        console.print("[dim]→ `medium-notion setup` で設定してください[/dim]")
        sys.exit(1)

    if headless is not None:
        config.headless = headless

    log.setup_logger(config.log_level)

    # 2. Claude Code の確認
    if not Config.check_claude_code():
        console.print(
            "[red]Claude Code CLI が見つかりません[/red]\n"
            "  → npm install -g @anthropic-ai/claude-code\n"
            "  → Max プランでログイン: claude login"
        )
        sys.exit(1)

    # 3. Notion 接続確認
    notion = NotionClient(config)
    if not notion.check_access():
        sys.exit(1)

    # 4. 記事取得
    browser = BrowserClient(config)
    try:
        await browser.initialize()
        article = await browser.fetch_article(url)
    except RuntimeError as e:
        console.print(f"\n[red]✗ 記事取得エラー:[/red] {e}")
        sys.exit(1)
    finally:
        await browser.close()

    if article.is_preview_only:
        console.print(
            "[yellow]⚠ ペイウォールにより記事のプレビューのみ取得しました[/yellow]"
        )

    # 5. 既存記事インデックスの読み込み
    existing_articles = _load_article_index(config)

    # 6. 翻訳
    translator = TranslationService(config)
    result = translator.translate_article(article, existing_articles=existing_articles)

    # 7. Notion に追加
    page = notion.create_page(result, score=score)

    # 8. インデックスに新記事を追加して保存
    _append_to_index(config, result)

    # 9. 結果表示
    _show_result(result, page)


def _show_result(result, page):
    """実行結果を表示"""
    console.print()
    console.print("[bold green]✓ 完了[/bold green]")
    console.print()
    console.print(f"  [bold]タイトル[/bold]  {result.japanese_title}")
    console.print(f"  [bold]カテゴリ[/bold]  {', '.join(result.categories) if result.categories else '-'}")
    if result.summary:
        summary = result.summary[:120] + "..." if len(result.summary) > 120 else result.summary
        console.print(f"  [bold]要約[/bold]    {summary}")
    console.print()
    console.print(f"  [bold]元記事[/bold]   {result.original.url}")
    console.print(f"  [bold]Notion[/bold]   {page.url}")
    console.print()


def _load_article_index(config: Config) -> list[dict]:
    """ローカルのインデックスファイルから既存記事一覧を読み込む"""
    if not config.index_path.exists():
        return []
    try:
        data = json.loads(config.index_path.read_text())
        log.step(f"記事インデックス読み込み: {len(data)} 件")
        return data
    except Exception:
        return []


def _append_to_index(config: Config, result) -> None:
    """翻訳結果をインデックスに追加して保存"""
    articles = _load_article_index(config)

    # 重複チェック（URL ベース）
    existing_urls = {a.get("url") for a in articles}
    if result.original.url not in existing_urls:
        articles.append({
            "title": result.japanese_title,
            "categories": result.categories,
            "url": result.original.url,
        })
        config.index_path.write_text(
            json.dumps(articles, ensure_ascii=False, indent=2)
        )
        log.step(f"インデックス更新: {len(articles)} 件")


@cli.command(context_settings=CONTEXT_SETTINGS)
def index():
    """Notion DB から記事インデックスを構築・更新する。

    Notion DB に登録済みの記事タイトルとカテゴリを取得し、
    ローカルの article-index.json に保存します。
    translate コマンドの「他の記事との関連」分析に使われます。

    \b
    使い方:
      medium-notion index          Notion DB から全記事を取得してインデックス作成
    """
    try:
        config = load_config()
    except ValidationError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        sys.exit(1)

    log.setup_logger(config.log_level)

    console.print(Panel("[bold]記事インデックスの構築[/bold]", style="blue"))

    notion = NotionClient(config)
    if not notion.check_access():
        sys.exit(1)

    articles = notion.list_articles()

    # ファイルに保存
    index_data = [
        {"title": a["title"], "categories": a["categories"]}
        for a in articles
    ]
    config.index_path.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2)
    )

    console.print(f"\n[bold green]✓ インデックス構築完了[/bold green]")
    console.print(f"  {len(index_data)} 件の記事を {config.index_path} に保存")
    console.print(f"  → translate 時に「他の記事との関連」分析に使われます\n")


@cli.command(context_settings=CONTEXT_SETTINGS)
def login():
    """Medium にログインしてセッションを保存する。

    ブラウザが GUI モードで開きます。Medium にログインすると
    セッション情報が medium-session.json に保存され、
    以降の translate コマンドで自動的に使われます。

    \b
    手順:
      1. ブラウザが開いたら「Sign in with email」を選択
      2. メールアドレス / パスワードでログイン
         ※ Google ログインは Playwright 非対応のため使えません
      3. ログイン完了後、自動的にセッションが保存されます

    \b
    注意:
      - セッションの有効期限が切れたら再度実行してください
      - .env ファイルが必要です（未作成なら先に medium-notion setup を実行）
    """
    asyncio.run(_login())


async def _login():
    """Medium ログインフロー"""
    console.print(
        Panel("[bold]Medium ログイン[/bold]\nブラウザが開きます。ログインしてください。", style="blue")
    )

    try:
        config = load_config()
    except ValidationError as e:
        console.print(f"[red]設定エラー:[/red] {e}")
        console.print("[dim]→ `medium-notion setup` で設定してください[/dim]")
        sys.exit(1)

    # ログイン時は必ず GUI モード
    config.headless = False
    log.setup_logger(config.log_level)

    browser = BrowserClient(config)
    try:
        await browser.initialize()
        success = await browser.ensure_login()
        if success:
            console.print("\n[bold green]✓ ログイン成功！セッションを保存しました[/bold green]")
            console.print(f"  セッションファイル: {config.session_path}")
            console.print("  → 以降は --headless モードで翻訳できます\n")
        else:
            console.print("\n[red]✗ ログインに失敗しました[/red]")
            sys.exit(1)
    finally:
        await browser.close()


@cli.command(context_settings=CONTEXT_SETTINGS)
def setup():
    """対話型セットアップウィザード。.env ファイルを作成する。

    Notion API キーと Database ID を入力して .env ファイルを生成します。
    作成後、Notion と Claude Code CLI の接続テストも行います。

    \b
    必要なもの:
      - Notion API キー (https://www.notion.so/profile/integrations で取得)
      - Notion Database ID (DB の URL に含まれる 32 文字の ID)
    """
    console.print(
        Panel("[bold]Medium → Notion セットアップ[/bold]", style="blue")
    )

    from pathlib import Path

    env_path = Path(".env")

    # Notion API キー
    console.print("\n[bold]1. Notion API キー[/bold]")
    console.print("[dim]  取得先: https://www.notion.so/profile/integrations[/dim]")
    notion_key = click.prompt("  Notion API キー", type=str)

    # Notion Database ID
    console.print("\n[bold]2. Notion Database ID[/bold]")
    console.print("[dim]  DB の URL から取得できます[/dim]")
    db_id = click.prompt("  Database ID", type=str)

    # .env ファイル書き込み
    env_content = (
        f"NOTION_API_KEY={notion_key}\n"
        f"NOTION_DATABASE_ID={db_id}\n"
        f"HEADLESS=false\n"
        f"LOG_LEVEL=INFO\n"
        f"CLAUDE_MODEL=sonnet\n"
    )
    env_path.write_text(env_content)
    console.print(f"\n[green]✓ .env ファイルを保存しました: {env_path.absolute()}[/green]")

    # 接続テスト
    console.print("\n[bold]3. 接続テスト[/bold]")
    try:
        config = load_config(str(env_path))
        notion = NotionClient(config)
        if notion.check_access():
            console.print("[green]✓ Notion DB への接続に成功しました[/green]")
        else:
            console.print("[red]✗ Notion DB への接続に失敗しました[/red]")
    except Exception as e:
        console.print(f"[red]✗ 設定エラー: {e}[/red]")

    # Claude Code 確認
    if Config.check_claude_code():
        console.print("[green]✓ Claude Code CLI が利用可能です[/green]")
    else:
        console.print(
            "[yellow]⚠ Claude Code CLI が見つかりません[/yellow]\n"
            "  → npm install -g @anthropic-ai/claude-code\n"
            "  → claude login でログイン"
        )

    console.print(
        "\n[bold green]セットアップ完了![/bold green]\n"
        "  → medium-notion login で Medium にログイン\n"
        "  → medium-notion translate -u '<URL>' で翻訳実行\n"
    )


@cli.command(context_settings=CONTEXT_SETTINGS)
def test():
    """設定と接続の状態をチェックする。

    以下の項目を確認します:

    \b
      - .env ファイルの読み込み
      - Claude Code CLI の利用可否
      - Notion API への接続
      - Medium ログインセッションの有無
    """
    console.print(Panel("[bold]接続テスト[/bold]", style="blue"))

    results = []

    # 1. .env 読み込み
    try:
        config = load_config()
        results.append(("設定ファイル (.env)", True, "読み込み成功"))
    except Exception as e:
        results.append(("設定ファイル (.env)", False, str(e)))
        _show_test_results(results)
        return

    # 2. Claude Code CLI
    has_claude = Config.check_claude_code()
    results.append((
        "Claude Code CLI",
        has_claude,
        "利用可能" if has_claude else "npm install -g @anthropic-ai/claude-code",
    ))

    # 3. Notion API
    try:
        notion = NotionClient(config)
        notion_ok = notion.check_access()
        results.append((
            "Notion API",
            notion_ok,
            "DB 接続成功" if notion_ok else "接続失敗",
        ))
    except Exception as e:
        results.append(("Notion API", False, str(e)))

    # 4. Medium セッション
    session_exists = config.session_path.exists()
    results.append((
        "Medium セッション",
        session_exists,
        "セッションファイルあり" if session_exists else "未ログイン → `medium-notion login` を実行",
    ))

    _show_test_results(results)


def _show_test_results(results: list[tuple[str, bool, str]]):
    """テスト結果をテーブルで表示"""
    table = Table(title="接続テスト結果", border_style="blue")
    table.add_column("項目", style="bold")
    table.add_column("状態")
    table.add_column("詳細")

    for name, ok, detail in results:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(name, status, detail)

    console.print()
    console.print(table)
    console.print()


# __main__.py 用のエントリポイント
def main():
    cli()


if __name__ == "__main__":
    main()
