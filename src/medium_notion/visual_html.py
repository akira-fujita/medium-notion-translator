"""視覚版 HTML（図とクイズ）の生成と Notion への埋め込み

podcast-summary の手順5b と同じ考え方で、要約ページには毎回 notion-visual-primer の
無人モードで作った HTML を埋め込む。違いは呼び方だけで、Notion を読み直させずに
手元の翻訳結果を材料として渡し、`claude -p` の標準出力で HTML を受け取る
（翻訳と同じ呼び方。ツールを使わないので headless で Bash が固まる問題を踏まない）。

HTML は従。生成・埋め込みに失敗しても記事の登録は成功のままにし、
DB の「HTML」プロパティ（⏳生成中 / ✅ / ⚠失敗）に痕跡を残す。
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .models import NotionPage, TranslationResult
from . import logger as log


# notion-visual-primer の正本。スキルを直したらこちらも追従するよう、毎回読み込む
PRIMER_FILES = (
    "SKILL.md",
    "references/html-contract.md",
    "references/unattended-mode.md",
)


# HTML 契約（notion-visual-primer）の確認クイズは 3〜5 問
MIN_QUIZ_QUESTIONS = 3


class HtmlGenerationError(Exception):
    """視覚版 HTML を作れなかった（理由は呼び出し元が ⚠失敗 として記録する）"""


PROMPT_TEMPLATE = textwrap.dedent("""\
    あなたは notion-visual-primer スキルを「無人モード」で実行します。
    以下にスキルの正本（SKILL.md / HTML 契約 / 無人モード）を示します。それに従って、
    Medium 記事の翻訳ページから視覚版 HTML を1枚作ってください。

    ## このモードでの読み替え（正本より優先）

    - 質問はしない。ツールは使わない（ファイル・Notion・Web を読まない、書かない）。
      材料は下の「記事の材料」だけで、Notion のページ本文と同じ内容です
    - 学習目標は**原著者の主張を説明できる**ことに限る
    - 「🛠 活用方法」は上流が生成した AI の応用案。必ず「応用案(AI 生成)」節に置き、
      本人の観点の節は作らない
    - 出力は HTML 文書だけを標準出力に返す（`<!DOCTYPE html>` から `</html>` まで。
      前置き・説明・コードフェンスは付けない）。result.json と MD副は作らない
    - 失敗として返す条件（学習目標が書けない / 図が1つも作れない / 材料が足りない）に
      当たるときは、HTML を書かずに `FAILED: <1行の理由>` の1行だけを返す
    - 出典は「一次情報 = 元記事 URL」「Notion クリップ元 = Notion ページ URL」を使う

    ## 記事の材料

    - 日本語タイトル: {japanese_title}
    - 原題: {original_title}
    - 著者: {author}
    - 元記事 URL: {original_url}
    - Notion ページ URL: {page_url}

    ### 要約（📖 概要 / 💡 学び・新規性 / 🛠 活用方法 / 🔗 他の記事との関連）

    {summary}

    ### 翻訳本文

    {content}

    ---

    # スキルの正本

    {primer}
    """)


def _read_primer(primer_dir: Path) -> str:
    parts = []
    for rel in PRIMER_FILES:
        path = Path(primer_dir) / rel
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as e:
            raise HtmlGenerationError(
                f"notion-visual-primer の正本が読めない: {path}（{type(e).__name__}）"
            ) from e
        parts.append(f"## {rel}\n\n{body}")
    return "\n\n".join(parts)


def build_prompt(result: TranslationResult, page_url: str, primer_dir: Path) -> str:
    """スキルの正本と記事の材料から、HTML 生成用のプロンプトを組み立てる"""
    # 材料を format の引数で渡す（本文中の波括弧をテンプレートとして解釈させない）
    return PROMPT_TEMPLATE.format(
        japanese_title=result.japanese_title,
        original_title=result.original.title,
        author=result.original.author or "（不明）",
        original_url=result.original.url,
        page_url=page_url,
        summary=result.summary or "（要約なし）",
        content=result.japanese_content,
        primer=_read_primer(primer_dir),
    )


def _quiz_section(html: str) -> str:
    """「理解チェック」見出しの節（次の同レベル以上の見出しまで）を返す。

    目次リンクやコメントの中の文字列ではなく、見出しそのものを文字列で探す
    （見出しの中のタグで文字列が分断されていてもよい）。
    """
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    for m in re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", visible, re.IGNORECASE | re.DOTALL):
        if "理解チェック" not in re.sub(r"<[^>]+>", "", m.group(2)):
            continue
        level = int(m.group(1))
        nxt = re.compile(rf"<h[1-{level}]\b", re.IGNORECASE).search(visible, m.end())
        return visible[m.end() : nxt.start() if nxt else len(visible)]
    raise HtmlGenerationError("理解チェック 節が無い（HTML 契約の必須節）")


def extract_html(raw: str) -> str:
    """Claude の応答から HTML 文書（<!DOCTYPE html> 〜 </html>）だけを取り出す"""
    m = re.search(r"^FAILED:\s*(.+)$", raw.strip(), re.MULTILINE)
    if m:
        raise HtmlGenerationError(m.group(1).strip())
    lower = raw.lower()
    start = lower.find("<!doctype html")
    if start == -1:
        raise HtmlGenerationError(f"応答に HTML 文書が無い（先頭: {raw.strip()[:100]}）")
    end = lower.rfind("</html>")
    if end < start:
        raise HtmlGenerationError("</html> が無い（出力が途中で切れている）")
    html = raw[start : end + len("</html>")]
    section = _quiz_section(html)
    # 契約: 3〜5問、答えは <details> で畳む。図は CSS で組むこともあるので印を決めて数えない
    answers = section.lower().count("<details")
    if answers < MIN_QUIZ_QUESTIONS:
        raise HtmlGenerationError(
            f"理解チェック の問いが足りない（畳んだ答えが {answers} 個。{MIN_QUIZ_QUESTIONS} 問以上が必要）"
        )
    return html


DEFAULT_OUT_ROOT = Path("~/.local/state/medium-html")


def local_html_path(page_id: str, title: str, day: date, root: Path = DEFAULT_OUT_ROOT) -> Path:
    """ローカルの保存先（podcast-summary の local_html_path と同じ規則）。

    同一性はページ ID 先頭8桁。スラグは表示用で、英数字にできなければ付けない。
    """
    pid = page_id.replace("-", "")[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    name = f"{day.isoformat()}-{pid}" + (f"-{slug}" if slug else "") + ".html"
    return Path(root).expanduser() / name


DEFAULT_PRIMER_DIR = Path("~/.claude/skills/notion-visual-primer")


@dataclass
class HtmlOutcome:
    """視覚版 HTML の結果（失敗しても例外にせず、これで返す）"""

    ok: bool
    path: Path | None = None
    reason: str = ""


def attach_visual_html(
    notion,
    call_claude: Callable[[str], str],
    result: TranslationResult,
    page: NotionPage,
    primer_dir: Path = DEFAULT_PRIMER_DIR,
    out_root: Path = DEFAULT_OUT_ROOT,
    today: date | None = None,
) -> HtmlOutcome:
    """作成済みの要約ページに視覚版 HTML を作って埋め込む。

    例外は外に出さない（HTML は従。記事の登録・インデックス追加・リスト削除を止めない）。
    失敗したら DB の「HTML」を ⚠失敗 にし、理由を HtmlOutcome で返す。
    """
    # 書けたパスだけを持つ。後始末でファイルシステムに触らない（exists() も例外を投げうる）
    saved: Path | None = None
    try:
        # 痕跡を残せないまま作らない（podcast-summary 手順5b と同じ）。失敗したら except へ
        notion.mark_html(page.page_id, "⏳生成中")
        prompt = build_prompt(result, page.url, Path(primer_dir).expanduser())
        html = extract_html(call_claude(prompt))
        path = local_html_path(
            page.page_id, result.original.title, today or date.today(), root=out_root
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        saved = path
        file_upload_id = notion.upload_html(path.name, html.encode("utf-8"))
        notion.embed_html(page.page_id, file_upload_id)
        notion.mark_html(page.page_id, "✅")
        return HtmlOutcome(ok=True, path=path)
    except Exception as e:
        reason = str(e).splitlines()[0] if str(e) else type(e).__name__
        log.warn(f"視覚版 HTML を作れませんでした（記事の登録は成功済み）: {reason}")
        if saved is not None:
            log.step(f"ローカルの HTML: {saved}")
        try:
            notion.mark_html(page.page_id, "⚠失敗")
        except Exception as mark_error:
            log.warn(f"HTML の状態を ⚠失敗 にできませんでした: {mark_error}")
        # ローカルの HTML は成否に関わらず残す（手で埋め込み直す・my-knowledge に入れる用）
        return HtmlOutcome(ok=False, path=saved, reason=reason)
