#!/usr/bin/env bash
# Medium Notion Translator - セットアップスクリプト
# 使い方: ./scripts/setup.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Medium Notion Translator"
APP_PATH="/Applications/${APP_NAME}.app"

# ── 色付き出力 ──────────────────────────────────────
green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m%s\033[0m\n' "$*"; }
step()   { printf '\n\033[1;36m[%s]\033[0m %s\n' "$1" "$2"; }

# ── 前提チェック ────────────────────────────────────
step "0/6" "前提条件チェック"

if ! command -v python3 &>/dev/null; then
    red "Python3 が見つかりません。brew install python@3.12 でインストールしてください"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    red "Python 3.10+ が必要です（現在: $PY_VERSION）"
    exit 1
fi
green "✓ Python $PY_VERSION"

if ! command -v claude &>/dev/null; then
    yellow "⚠ Claude Code CLI が見つかりません"
    read -rp "  npm install -g @anthropic-ai/claude-code を実行しますか？ [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        npm install -g @anthropic-ai/claude-code
        claude login
    else
        red "Claude Code CLI は後で手動インストールしてください"
    fi
else
    green "✓ Claude Code CLI"
fi

# ── Step 1: Python 環境構築 ─────────────────────────
step "1/6" "Python 仮想環境を構築"

cd "$PROJECT_DIR"

if [ ! -d .venv ]; then
    python3 -m venv .venv
    green "✓ .venv を作成しました"
else
    yellow "✓ .venv は既に存在します"
fi

source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -e . --quiet
green "✓ 依存パッケージをインストールしました"

# ── Step 2: Playwright ──────────────────────────────
step "2/6" "Playwright (Chromium) をインストール"

if .venv/bin/playwright install --dry-run chromium &>/dev/null 2>&1; then
    .venv/bin/playwright install chromium
else
    # --dry-run 非対応バージョン
    .venv/bin/playwright install chromium
fi
green "✓ Chromium をインストールしました"

# ── Step 3: ログディレクトリ ────────────────────────
step "3/6" "ログディレクトリを作成"

mkdir -p "$PROJECT_DIR/logs"
green "✓ logs/"

# ── Step 4: Dock アプリをビルド ─────────────────────
step "4/6" "Dock アプリをビルド"

# AppleScript を現在のパスで生成
APPLESCRIPT_TMP=$(mktemp /tmp/mnt-XXXXXX.applescript)
cat > "$APPLESCRIPT_TMP" <<APPLESCRIPT
-- Medium Notion Translator - Bookmark Runner
-- Dock にドロップしてワンクリックで翻訳実行

set projectDir to "$PROJECT_DIR"
set venvBin to projectDir & "/.venv/bin/medium-notion"
set logFile to projectDir & "/logs/bookmark-run.log"

tell application "Terminal"
	activate
	set newTab to do script "cd " & quoted form of projectDir & " && " & quoted form of venvBin & " bookmark -l toNotion --run --gui 2>&1 | tee " & quoted form of logFile & "; echo ''; echo '=== 完了 ==='; echo 'このウィンドウは閉じて構いません'"
end tell
APPLESCRIPT

osacompile -o "$APP_PATH" "$APPLESCRIPT_TMP"
rm -f "$APPLESCRIPT_TMP"

# カスタムアイコンを設定
ICON_PATH="$PROJECT_DIR/scripts/AppIcon.icns"
if [ -f "$ICON_PATH" ]; then
    cp "$ICON_PATH" "$APP_PATH/Contents/Resources/applet.icns"
    green "✓ カスタムアイコンを設定しました"
fi

green "✓ ${APP_PATH} を作成しました"

# ── Step 5: Dock に追加 ─────────────────────────────
step "5/6" "Dock に追加"

# 既に Dock にあるかチェック
if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "$APP_NAME"; then
    yellow "✓ 既に Dock に追加されています"
else
    read -rp "  Dock に追加しますか？ [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn]$ ]]; then
        defaults write com.apple.dock persistent-apps -array-add \
            "<dict>
                <key>tile-data</key>
                <dict>
                    <key>file-data</key>
                    <dict>
                        <key>_CFURLString</key>
                        <string>${APP_PATH}</string>
                        <key>_CFURLStringType</key>
                        <integer>0</integer>
                    </dict>
                </dict>
            </dict>"
        killall Dock
        green "✓ Dock に追加しました"
    else
        yellow "  スキップ（後で手動で追加できます）"
    fi
fi

# ── Step 6: アプリ設定 ──────────────────────────────
step "6/6" "アプリケーション設定"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    green "セットアップウィザードを起動します..."
    .venv/bin/medium-notion setup
else
    yellow "✓ .env は既に存在します"
fi

# Medium ログイン
if [ ! -f "$PROJECT_DIR/medium-session.json" ]; then
    green "Medium にログインします..."
    .venv/bin/medium-notion login
else
    yellow "✓ Medium セッションは既に存在します"
fi

# ── 完了 ────────────────────────────────────────────
echo ""
green "=========================================="
green "  セットアップ完了!"
green "=========================================="
echo ""
echo "  Dock の「${APP_NAME}」をクリックすると"
echo "  bookmark -l toNotion --run --gui が実行されます"
echo ""
echo "  手動で翻訳する場合:"
echo "    source .venv/bin/activate"
echo "    medium-notion translate -u '<URL>'"
echo ""
