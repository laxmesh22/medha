"""Live watcher for the Cursor agent: one line per event, for Claude's Monitor (stdout = event stream).

Follows tools/cursor_bridge/LIVE/from_cursor/*.jsonl as the bridge writes them and reports:
  EDIT  <msg> <path>            Cursor wrote or edited a file
  DEL   <msg> <path>            Cursor deleted a file
  RUN   <msg> <command>         Cursor ran a shell command
  FAIL  <msg> <tool> <error>    a tool call failed
  DONE  <msg> <seconds>s        Cursor finished the message (answer in from_cursor/<msg>.md)
  QUIET <msg> <minutes>m        a message is still open but its log has not grown for a while
  GIT   +<path> / ~<path>       the working tree changed outside the bridge (Cursor IDE, Codex, the user)
  BRIDGE <text>                 the bridge produced no result (crash, sign-in, network)

Usage: python tools/cursor_bridge/watch_cursor.py   (Ctrl-C to stop)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROM = Path(__file__).resolve().parent / "LIVE" / "from_cursor"
QUIET_AFTER = 8 * 60  # seconds without log growth before a QUIET line
IGNORE = ("tools/cursor_bridge/LIVE/", ".claude/")


def say(line: str) -> None:
    print(line[:300], flush=True)


def git_dirty() -> dict[str, str]:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "-uall"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    state = {}
    for row in out.splitlines():
        path = row[3:].strip().strip('"')
        if not path.startswith(IGNORE):
            state[path] = row[:2]
    return state


def tool_event(msg: str, e: dict) -> str | None:
    kind, body = next(iter(e["tool_call"].items()))
    args = body.get("args", {})
    name = kind.removesuffix("ToolCall")
    if e.get("subtype") == "started":
        if name in ("edit", "write"):
            return f"EDIT  {msg} {args.get('path', '?')}"
        if name == "delete":
            return f"DEL   {msg} {args.get('path', '?')}"
        if name == "shell":
            return f"RUN   {msg} {' '.join(str(args.get('command', '')).split())}"
        return None
    err = (body.get("result") or {}).get("error")
    if e.get("subtype") == "completed" and err and name not in ("read", "glob", "grep"):
        text = err.get("error", err) if isinstance(err, dict) else err
        return f"FAIL  {msg} {name} {' '.join(str(text).split())}"
    return None


def main() -> None:
    FROM.mkdir(parents=True, exist_ok=True)
    offsets: dict[Path, int] = {p: p.stat().st_size for p in FROM.glob("*.jsonl")}  # only new activity
    answered = {p.stem for p in FROM.glob("*.md")}
    grew: dict[str, float] = {}
    quiet_said: set[str] = set()
    tree = git_dirty()
    say(f"WATCH up: {len(answered)} answers so far, {len(tree)} changed paths in the tree")
    last_git = time.time()
    while True:
        for log in sorted(FROM.glob("*.jsonl")):
            msg = log.stem
            size = log.stat().st_size
            start = offsets.get(log, 0)
            if size > start:
                grew[msg] = time.time()
                quiet_said.discard(msg)
                with log.open("rb") as f:
                    f.seek(start)
                    chunk = f.read()
                cut = chunk.rfind(b"\n") + 1  # keep a half-written last line for the next round
                offsets[log] = start + cut
                for raw in chunk[:cut].decode("utf-8", "replace").splitlines():
                    if raw.startswith("STDERR:"):
                        say(f"BRIDGE {msg} {' '.join(raw.split())}")
                        continue
                    try:
                        e = json.loads(raw)
                    except ValueError:
                        continue
                    if e.get("type") == "tool_call":
                        line = tool_event(msg, e)
                        if line:
                            say(line)
                    elif e.get("type") == "result":
                        say(f"DONE  {msg} {round(e.get('duration_ms', 0) / 1000)}s")
        for ans in FROM.glob("*.md"):
            if ans.stem not in answered:
                answered.add(ans.stem)
                head = ans.read_text(encoding="utf-8", errors="replace")[:200]
                if head.startswith("BRIDGE:"):
                    say(f"BRIDGE {ans.stem} {' '.join(head.split())}")
        for flag in FROM.glob("*.working"):
            msg = flag.stem
            since = grew.get(msg, flag.stat().st_mtime)
            if time.time() - since > QUIET_AFTER and msg not in quiet_said:
                quiet_said.add(msg)
                say(f"QUIET {msg} {round((time.time() - since) / 60)}m")
        if time.time() - last_git > 20:
            last_git = time.time()
            now = git_dirty()
            for path, st in now.items():
                if tree.get(path) != st:
                    say(f"GIT   {'+' if st.strip() == '??' else '~'}{path} [{st.strip()}]")
            for path in tree.keys() - now.keys():
                say(f"GIT   -{path} (clean again: committed or reverted)")
            tree = now
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
