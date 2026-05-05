-- Medium Notion Translator - Bookmark Runner
-- Dock にドロップしてワンクリックで翻訳実行
-- プロジェクトパスは Contents/Resources/project-dir.txt から実行時に解決

set appPath to POSIX path of (path to me)
set projectDir to do shell script "cat " & quoted form of (appPath & "Contents/Resources/project-dir.txt")
set venvBin to projectDir & "/.venv/bin/medium-notion"
set logFile to projectDir & "/logs/bookmark-run.log"

tell application "Terminal"
	activate
	set newTab to do script "source ~/.zshrc 2>/dev/null; cd " & quoted form of projectDir & " && " & quoted form of venvBin & " bookmark -l toNotion --run --gui 2>&1 | tee " & quoted form of logFile & "; echo ''; echo '=== 完了 ==='; echo 'このウィンドウは閉じて構いません'"
end tell
