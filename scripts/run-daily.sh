#!/bin/bash
# launchd 経由で日次起動されるラッパー
#
# 役割:
#   - HEADLESS=true で bookmark コマンドを実行（既存作業を邪魔しない）
#   - launchd の最小限の PATH 環境を補正
#   - ログを logs/launchd-bookmark.log に追記
#   - 終了コードを launchd に渡す（失敗時は plist 側で再試行設定可）

set -u

# プロジェクトルート（このスクリプトの2階層上）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

LOG_FILE="${PROJECT_DIR}/logs/launchd-bookmark.log"
LOCK_DIR="${PROJECT_DIR}/logs/.run-daily.lock"
mkdir -p "${PROJECT_DIR}/logs"

# ── 排他ロック (mkdir はアトミック) ──
# 同一スケジュールが偶発的に重なったり、launchctl start で手動キックされた場合に
# Notion 二重登録 / Reading List 削除レースを防ぐ。
#
# 設計判断: ロックの自動回復はしない (TOCTOU を避けるため)。
# プロセスが SIGKILL 等で残骸ロックを残した場合は、Slack の致命的エラー通知で
# 気づいて手動で `rmdir logs/.run-daily.lock` する運用。
# 1日3回スケジュールなので、1回スキップしても次回で処理は通る。
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    LOCK_MTIME=$(stat -f %m "${LOCK_DIR}" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    LOCK_AGE=$((NOW - LOCK_MTIME))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: 別のインスタンスが実行中またはロック残留。スキップ (age=${LOCK_AGE}s)" >> "${LOG_FILE}"
    if [ "${LOCK_AGE}" -ge 43200 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: ロックが12時間以上経過。手動で rmdir ${LOCK_DIR} を検討してください" >> "${LOG_FILE}"
    fi
    exit 0
fi
# 自プロセスの PID をロックに記録（デバッグ用）
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "${LOCK_DIR}" 2>/dev/null || true' EXIT

# launchd は最小 PATH なので、Claude Code CLI / Homebrew / venv が見える PATH を構築する
# 優先度: ユーザーローカル (~/.local/bin の Claude Code 公式インストーラ既定) → npm-global → Homebrew → 標準
export PATH="${HOME}/.local/bin:${HOME}/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

# Claude Code CLI が nvm 配下にある場合のフォールバック
# nvm.sh をソースしただけでは Node バージョンは選択されないので、default を有効化する
if [ -s "${HOME}/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    \. "${HOME}/.nvm/nvm.sh" >/dev/null 2>&1 || true
    nvm use default >/dev/null 2>&1 || true
fi

VENV_BIN="${PROJECT_DIR}/.venv/bin/medium-notion"
if [ ! -x "${VENV_BIN}" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: medium-notion not found at ${VENV_BIN}" >> "${LOG_FILE}"
    exit 127
fi

# Claude CLI の存在を事前確認（見つからなければ Slack 通知が出るが、ここでもログに残す）
if ! command -v claude >/dev/null 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: 'claude' not in PATH (PATH=${PATH})" >> "${LOG_FILE}"
fi

{
    echo ""
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') launchd 起動 ====="
} >> "${LOG_FILE}"

"${VENV_BIN}" bookmark -l toNotion --run --headless --interval 60 >> "${LOG_FILE}" 2>&1
EXIT_CODE=$?

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 (exit=${EXIT_CODE}) =====" >> "${LOG_FILE}"

exit "${EXIT_CODE}"
