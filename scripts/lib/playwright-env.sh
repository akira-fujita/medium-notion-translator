# shellcheck shell=bash
# Playwright ブラウザの配置先を固定する共有スニペット（source して使う）
#
# なぜ必要か:
#   Playwright の既定の配置先は ~/Library/Caches/ms-playwright だが、
#   ~/Library/Caches は macOS のストレージ最適化（cache_delete）のパージ対象。
#   実際に 2026-08-03、ディレクトリごと削除されて
#     BrowserType.launch: Executable doesn't exist at .../chromium-1208/...
#   で bookmark / translate が全滅した。
#   Caches の外に置けば OS に消されない。
#
# 使い方:
#   ブラウザを起動する処理と `playwright install` の両方が、必ず同じ値を見る必要がある。
#   食い違うとインストール先と参照先がズレて同じ症状が再発するため、
#   ブラウザを扱うスクリプトは本ファイルを source すること。
#   手動実行（ターミナルから medium-notion / playwright を直に叩く場合）向けには
#   ~/.zshrc にも同じ export を入れてある。
#
#   既に環境変数が設定されている場合はそちらを尊重する（CI などで差し替え可能）。

: "${PLAYWRIGHT_BROWSERS_PATH:=${HOME}/.playwright-browsers}"
export PLAYWRIGHT_BROWSERS_PATH
