"""Low-token watcher for the Cursor bridge: prints only when a brief finishes or the bridge stalls.

Use this instead of watch_cursor.py when you only need to know "is it done?". One line per event:
  DONE  <msg>  <STATUS line from Cursor's answer>     a brief finished (full answer in from_cursor/<msg>.md)
  STUCK <msg>  <minutes>m without progress             the brief's log has not grown for a while
  NOANS <msg>                                          the brief closed without an answer file

Usage: python tools/cursor_bridge/watch_done.py [LIVE|LIVE_IMU]   (run under Monitor; Ctrl-C to stop)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

LIVE_NAME = sys.argv[1] if len(sys.argv) > 1 else "LIVE"
FROM = Path(__file__).resolve().parent / LIVE_NAME / "from_cursor"
STUCK_AFTER = 15 * 60  # seconds without log growth
POLL = 5


def status_line(md: Path) -> str:
    try:
        lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if line.strip().startswith("STATUS"):
            return line.strip()[:300]
    return (lines[-1].strip()[:200] if lines else "")


def main() -> None:
    seen_done = {p.stem for p in FROM.glob("*.md")}
    stuck_said: set[str] = set()
    print(f"WATCH {LIVE_NAME}: {len(seen_done)} answers so far", flush=True)
    while True:
        now = time.time()
        for md in sorted(FROM.glob("*.md")):
            if md.stem not in seen_done:
                seen_done.add(md.stem)
                print(f"DONE  {md.stem}  {status_line(md)}", flush=True)
        for w in FROM.glob("*.working"):
            msg = w.stem
            log = FROM / f"{msg}.jsonl"
            last = log.stat().st_mtime if log.exists() else w.stat().st_mtime
            if now - last > STUCK_AFTER and msg not in stuck_said:
                stuck_said.add(msg)
                print(f"STUCK {msg}  {int((now - last) / 60)}m without progress", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
