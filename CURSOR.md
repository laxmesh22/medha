# CURSOR.md: rules for the Cursor agent in the Auri repo

Read this whole file before you touch anything, then `AGENTS.md`. Cursor does not remember earlier chats, so the
bridge chat history, `AGENTS.md` and `tools/cursor_bridge/reports/` are your memory.

## 0. What this repo is

**Auri** (formerly "Physio Buddy"; old names in code such as `physiobuddy_hub` stay) is a frozen-shoulder rehab system,
shown at IIT Bombay on **31 Oct 2026**:

| Folder | What |
|---|---|
| `hub/` | Python station software (`physiobuddy_hub`): Jetson + RealSense D455f skeleton, strap IMUs (BNO085), the coach, the recorder, the API the web UI talks to |
| `web/` | the station's web UI (Vite) |
| `ml/` | PB-MotionNet training, datasets, validation (`ml/README.md`) |
| `clinician/` | the doctor dashboard (Vite + React + TS, Supabase data, Auth0 sign-in), live at https://auri-clinician.vercel.app |
| `hardware/` | CAD (CadQuery), renders, wiring |
| `video/` | Remotion films and the dashboard intro |
| `tools/` | Blender, CAD, audio helpers, and this bridge |

Read `agenthandoff.md` (rules, hardware, maths) and `jetson_realsense_ai_design.md` (architecture) when a task touches
the station or the ML.

## 1. How you work with Claude (the bridge)

- Claude sends you numbered messages (`tools/cursor_bridge/LIVE/to_cursor/NNN.md`). Do exactly what the message asks,
  no more. If something is unclear or looks wrong, say so in your answer instead of guessing.
- Claude watches every edit and command you make while you work and reviews the diff afterwards.
- **Do not commit, push, deploy or open PRs.** Leave your changes in the working tree; Claude reviews and commits them.
- End every answer with these sections:
  1. **Done**: what you did, in a few sentences.
  2. **Files changed**: every path you created, edited or deleted.
  3. **Checks**: each command you ran to verify, and its result (pass/fail counts, build OK, errors).
  4. **Open**: anything unfinished, risky, or that you want Claude to decide.
- Long jobs (training, renders, big builds): follow `.cursor/rules/claude-bridge.mdc` (detached with
  `Invoke-CimMethod Win32_Process`, log in `tools/cursor_bridge/LIVE/logs/<name>.out`), report the PID and log path,
  and end your turn. Do not sit waiting.
- Append one line per step to `tools/cursor_bridge/LIVE/STATUS.md`.

## 2. Other agents share this working tree

A Codex agent also edits this repo. Before editing a file, run `git status` / `git diff <file>`; if it has uncommitted
changes you did not make, do not touch it and tell Claude.

- **Codex owns** `ml/` and `hub/physiobuddy_hub/recorder.py`. Do not edit them unless the message says so.
- Never touch `.claude/` (including `.claude/worktrees/`, a separate checkout of the `design-language` branch).
- Never switch branches, stash, reset, or rewrite history.

## 3. Non-negotiable project rules (handoff section 0)

- Degrees come from geometry only. The network judges; it never outputs angles and is never consulted for safety.
- Missing data is "unavailable", never 0.
- A trained model is advisory until `ml/validate_real.py` passes that exact `model_version` on held-out volunteers.
- Exercise targets and progression are clinician-defined. Nothing auto-increases.
- Test recordings go to a scratch `--dataset-dir`, never `ml/data/real` (training data).
- Do not `git clone` datasets into `ml/data/public`.

## 4. Secrets and data

- Never print, copy or commit the contents of any `.env`, `.env.local` or key file. Refer to variables by name.
- `clinician/` talks to a real Supabase project: do not write to it, run SQL against it or create accounts.
- Demo patients are fictional; keep it that way.

## 5. Checks before you report

| Changed | Run |
|---|---|
| `hub/` or `ml/` | `hub/.venv/Scripts/python.exe -m pytest hub/tests ml/tests -q` |
| `web/` | `cd web; npm run build` |
| `clinician/` | `cd clinician; npx tsc -b; npx vite build` |
| `video/` | `cd video; npx tsc --noEmit -p .` |

Report real results. A failing check you did not cause is still reported, with the first error line.

## 6. Style

Match the surrounding code: comment density, naming, idiom. Small, focused changes. Plain words in anything a user
reads.
