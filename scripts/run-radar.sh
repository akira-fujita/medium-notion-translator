#!/bin/bash
# launchd 経由で日次起動される radar ラッパー
#
# 役割:
#   - medium-notion radar を実行（RSS 取得 → Claude 採点 → Slack + Notion）
#   - launchd の最小限の PATH 環境を補正（Claude CLI / venv が見えるように）
#   - ログを logs/radar.log に追記
#   - 終了コードを launchd に渡す
#
# radar はブラウザ・Medium セッションに依存しない（純 HTTP + Claude CLI）。
# 新着ゼロなら何も出力せず exit 0。seen ストア(radar-seen.json)で重複は吸収される。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

LOG_FILE="${PROJECT_DIR}/logs/radar.log"
LOCK_DIR="${PROJECT_DIR}/logs/.run-radar.lock"
mkdir -p "${PROJECT_DIR}/logs"

# ── 排他ロック (mkdir はアトミック) ──
# 偶発的な多重起動（手動 launchctl start / 起動時刻の重なり）を防ぐ。
# 残骸ロックは 12 時間で警告（自動撤去はしない: TOCTOU 回避）。
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    LOCK_MTIME=$(stat -f %m "${LOCK_DIR}" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    LOCK_AGE=$((NOW - LOCK_MTIME))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: 別インスタンス実行中/ロック残留。スキップ (age=${LOCK_AGE}s)" >> "${LOG_FILE}"
    if [ "${LOCK_AGE}" -ge 43200 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: ロックが12時間以上経過。手動で rmdir ${LOCK_DIR} を検討" >> "${LOG_FILE}"
    fi
    exit 0
fi
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "${LOCK_DIR}" 2>/dev/null || true' EXIT

# launchd は最小 PATH なので Claude CLI / Homebrew / venv が見える PATH を構築
export PATH="${HOME}/.local/bin:${HOME}/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

# Claude CLI が nvm 配下にある場合のフォールバック
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

if ! command -v claude >/dev/null 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: 'claude' not in PATH (PATH=${PATH})" >> "${LOG_FILE}"
fi

{
    echo ""
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') radar launchd 起動 ====="
} >> "${LOG_FILE}"

# ネットワーク（DNS）準備待ち — スリープ復帰直後は DNS が未準備で
# Notion/Slack/Claude への接続が全滅することがある（[Errno 8] getaddrinfo 失敗）。
# api.notion.com が解決できるまで最大 120 秒待ってから本処理に入る。
PY_BIN="${PROJECT_DIR}/.venv/bin/python"
for i in $(seq 1 24); do
    if "${PY_BIN}" -c "import socket; socket.gethostbyname('api.notion.com')" 2>/dev/null; then
        break
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: ネットワーク準備待ち (${i}/24)" >> "${LOG_FILE}"
    sleep 5
done

"${VENV_BIN}" radar >> "${LOG_FILE}" 2>&1
EXIT_CODE=$?

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 (exit=${EXIT_CODE}) =====" >> "${LOG_FILE}"

exit "${EXIT_CODE}"
