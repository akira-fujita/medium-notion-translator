#!/bin/bash
# LaunchAgent をインストールして日次実行を有効化する
#
# 実行: bash scripts/launchd/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SRC_PLIST="${SCRIPT_DIR}/com.akira.medium-bookmark.plist"
DST_PLIST="${HOME}/Library/LaunchAgents/com.akira.medium-bookmark.plist"
LABEL="com.akira.medium-bookmark"

if [ ! -f "${SRC_PLIST}" ]; then
    echo "ERROR: plist テンプレートが見つかりません: ${SRC_PLIST}" >&2
    exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${PROJECT_DIR}/logs"

# 既存のものをアンロードしてから上書き（差分だけでも事故らない様に）
if launchctl list | grep -q "${LABEL}"; then
    echo "→ 既存 LaunchAgent をアンロード"
    launchctl unload "${DST_PLIST}" 2>/dev/null || true
fi

# プレースホルダを実パスに置換しながらコピー
sed "s|__PROJECT_DIR__|${PROJECT_DIR}|g" "${SRC_PLIST}" > "${DST_PLIST}"

# 検証
if ! plutil -lint "${DST_PLIST}" >/dev/null; then
    echo "ERROR: plist の構文エラー" >&2
    exit 1
fi

# ロード
launchctl load "${DST_PLIST}"

echo "✅ インストール完了: ${DST_PLIST}"
echo ""
echo "確認:"
echo "  launchctl list | grep ${LABEL}"
echo ""
echo "即時実行（動作確認）:"
echo "  launchctl start ${LABEL}"
echo "  tail -f ${PROJECT_DIR}/logs/launchd-bookmark.log"
echo ""
echo "アンインストール:"
echo "  launchctl unload ${DST_PLIST}"
echo "  rm ${DST_PLIST}"
