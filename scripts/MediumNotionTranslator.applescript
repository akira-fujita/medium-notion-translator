-- Medium Notion Translator - Bookmark Runner
-- Dock にドロップしてワンクリックで翻訳実行

set projectDir to "/Users/akira.fujita/Documents/GitHub/medium-notion-translator"
set venvBin to projectDir & "/.venv/bin/medium-notion"
set logFile to projectDir & "/logs/bookmark-run.log"

tell application "Terminal"
	activate
	set newTab to do script "cd " & quoted form of projectDir & " && " & quoted form of venvBin & " bookmark -l toNotion --run --gui 2>&1 | tee " & quoted form of logFile & "; echo ''; echo '=== 完了 ==='; echo 'このウィンドウは閉じて構いません'"
end tell
