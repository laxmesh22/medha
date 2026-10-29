# Claude <-> Cursor bridge (Auri)

Claude plans, briefs and reviews; the Cursor agent (Cursor CLI, Grok 4.7 High) executes. Same set-up as the DODO
project, from the `cursor-bridge` skill.

| Path | What |
|---|---|
| `LIVE/` (git-ignored) | the bridge: `cursor_bridge.ps1`, `watch.sh`, `to_cursor/NNN.md` (Claude), `from_cursor/NNN.md` + `.jsonl` (Cursor), `logs/`, `STATUS.md`, `TO_AGENT.md`, `chat_id.txt` |
| `watch_cursor.py` | edit-level watcher: one line per Cursor edit, delete, command, failure, finish, and per working-tree change |
| `reports/` | write-ups Cursor produces that are worth keeping (committed after Claude reviews them) |
| `../../CURSOR.md`, `../../.cursor/rules/` | the rules Cursor reads on every message |

Start the bridge in a real terminal tab (signed in to Cursor), and leave it running:

```powershell
& 'D:\medha\tools\cursor_bridge\LIVE\cursor_bridge.ps1' -Model grok-4.7-high -Workspace D:\medha
```

Recreate `LIVE/` on another machine: `& "$HOME\.claude\skills\cursor-bridge\scripts\new_bridge.ps1" -Project D:\medha -Live D:\medha\tools\cursor_bridge\LIVE`.
