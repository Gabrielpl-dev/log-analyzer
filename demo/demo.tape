# VHS tape for the terminal demo (https://github.com/charmbracelet/vhs).
# Regenerate with:  vhs demo/demo.tape
Output docs/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1100
Set Height 700
Set Padding 24
Set TypingSpeed 40ms

Type "./app --version"
Enter
Sleep 500ms

Type "./app summary tests/fixtures/ac1.jsonl"
Enter
Sleep 1200ms

Type "./app summary --json tests/fixtures/ac1.jsonl | python3 -m json.tool"
Enter
Sleep 1500ms

Type "./app anomalies --window 60s --k 2 tests/fixtures/ac8.jsonl"
Enter
Sleep 1500ms

Type "./app report --out report.md --now 2026-10-06T12:00:00Z tests/fixtures/ac1.jsonl"
Enter
Sleep 800ms

Type "cat report.md"
Enter
Sleep 2000ms
