# How we made the Auri videos (and the tools and skills we used)

This is for the person continuing the project and their Claude agent. Everything below was checked against the scripts
in this repo. Anything we could not find in the repo is marked **[not found in repo: ask the user]**.

The three finished videos, all in `hardware/renders/`:

| Video | Length | Composition | What it shows |
|---|---|---|---|
| `physio_buddy_film_v2.mp4` | 35 s, 1080p | `PhysioBuddyFilm` | the CAD units, the patient wearing them, exercises with a live angle HUD |
| `physio_buddy_assembly_guide.mp4` (+ `_mobile.mp4`, 14 MB) | 2:29, 19 steps | `AssemblyGuide` | building one strap unit, step by step |
| `auri_dashboard_intro.mp4` | 54 s, 1080p | `AuriIntro` | walkthrough of the clinician dashboard |

An older 19 s film, `physio_buddy_device.mp4`, came from `tools/blender/device_on_avatar.py` alone.

---

## 0. The pipeline and the tools

```
CAD (CadQuery) -> STEP/STL/GLB -> Blender (Cycles shots + per-frame tracking JSON)
   -> encode PNG frames to MP4 -> synthesized soundtrack -> Remotion edit (callouts, HUD, titles) -> MP4
Dashboard intro: running web app -> headless Chrome screenshots + element rectangles -> Remotion
```

| Tool | Version used | Where |
|---|---|---|
| Blender | 5.2 (`C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`) | always `-b --factory-startup -P <script> -- <args>` |
| CadQuery | in `tools/cad/.venv` | `hardware/cad/physio_pod.py` |
| SolidWorks | the user's licensed install (optional) | `tools/cad/solidworks_convert.py` via COM |
| Python | `hub/.venv` (3.10) for encode and music scripts | |
| ffmpeg | on PATH (used by `encode_footage.py`) | |
| Node + Remotion | `video/` (`npx remotion …`) | compositions in `video/src/Root.tsx` |
| chrome-headless-shell | Playwright install, e.g. `%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-*\chrome-headless-shell-win64\chrome-headless-shell.exe` | dashboard capture |

All commands below run from the repo root (`D:\medha`) unless they start with `cd`.

## 1. CAD -> STL, STEP, GLB (and SolidWorks)

1. Build and fit-check every part, then export them all:
   `tools/cad/.venv/Scripts/python.exe hardware/cad/physio_pod.py`
   - It makes the upper-arm, forearm and trunk pods and the curved strap bases. Every pod slides onto every base on
     the same dovetail "PB-rail" with a click latch.
   - Output goes to `hardware/cad/out/`: STEP, STL and GLB.
   - Vendor STEP models dropped in `hardware/cad/vendor/` are used automatically for the fit check: BNO085 (Adafruit
     4754), DRV2605L (2305), XIAO ESP32-S3. They are git-ignored; see that folder's README for the names.
2. Optional, native SolidWorks parts:
   `tools/cad/.venv/Scripts/python.exe tools/cad/solidworks_convert.py hardware/cad/out/step hardware/cad/out/solidworks`
3. Checking someone else's STL:
   - `tools/cad/stl_report.py`: size, bodies, watertight, volume, grams of PLA.
   - `tools/cad/render_stl.py`: Blender 4-view render on a 10 mm grid.
   - `tools/cad/stl_section.py`: scaled cross-section.
4. Product stills (hero and exploded view of each unit, EEVEE):
   `blender -b --factory-startup -P tools/blender/render_units.py -- hardware/cad/out/glb hardware/renders [samples]`

## 2. Blender shots

### Assets
- **Patient avatar:** Microsoft Rocketbox, MIT licence.
  `blender -b --factory-startup -P tools/blender/rocketbox_to_glb.py -- <avatar_dir> <out.glb> [tex_size]`
  produces `web/public/models/Sports_Male_04.glb`. The station uses the same GLB.
- **Anatomy (the station's X-ray view):** Z-Anatomy / BodyParts3D, CC BY-SA.
  `blender -b --factory-startup -P tools/blender/build_anatomy.py -- <zanatomy_dir> <out.glb>`
  Keep the attribution line.

### Device on the avatar
`tools/blender/device_on_avatar.py` builds the scene. Placement is computed, not hand-tuned:
- The units are raycast onto the skin: the upper-arm unit 45 % down the humerus, the forearm unit 75 % toward the
  wrist.
- The straps are rings shrink-wrapped onto the skin.
- Everything is parented to the bones, so it follows the exercise.

Modes:
- `still`: renders `avatar_still.png`, the placement check.
- `video`: renders the shots.

Options: `--avatar … --side right --samples 32 --res 1920x1080`.

### The film shots
`tools/blender/device_film.py` reuses the device_on_avatar helpers.

| Shot | Frames | Content |
|---|---|---|
| product | 135 | unit explodes and reassembles |
| rail | 90 | pod slides onto the base and latches |
| family | 75 | the three units side by side |
| reveal | 150 | the patient wearing all three, camera arc |
| flexion | 180 | forward raise |
| abduction | 150 | side raise |
| rotation | 120 | outward rotation |

- Render everything:
  `"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup -P tools/blender/device_film.py -- all --samples 96`
- Frames: `hardware/renders/frames/v2/<shot>/####.png`.
- Tracking: `video/public/data/<shot>.json` (§3).
- Test one frame per shot: `-- test`, or `-- <shot> --still [--at 0.55]`. Output is `hardware/renders/test_v2_<shot>.png`.
- Re-render part of a shot: `-- <shot> --frames a b`. The frames already rendered are kept.

### The assembly guide clips
- `tools/blender/assembly_guide.py`, one clip per build step: `-- <clip>`, or `-- test` / `--still`.
- It is CAD-accurate: the design has no screws, wiring follows agenthandoff.md §6, and the Qwiic colours are
  black GND, red 3V3, blue SDA, yellow SCL.
- Frames: `hardware/renders/frames/guide/<clip>/`. Tracking: `video/public/guide/<clip>.json`.
- Clip lengths must match `video/src/guide/steps.ts`.

### Gotchas we hit
- **Use the OptiX denoiser in Cycles.** OpenImageDenoise picked the Intel iGPU and took about 35 s a frame.
- **Blender 5.x video output:** set `scene.render.image_settings.media_type = "VIDEO"` before
  `file_format = "FFMPEG"`, or the call fails.
- **Avatar shots keep their timeline frame numbers.** The encoder passes ffmpeg `-start_number`; do not renumber.
- **Shot lengths in three places:** `LENGTHS` in `device_film.py` and `src/timeline.ts` in Remotion must match.
- **Always run with `--factory-startup`,** so the user's Blender add-ons and preferences cannot change the output.

## 3. Tracking and overlays (why the callouts stick)
- For every frame, Blender projects the 3D positions of parts and features to screen pixels with
  `world_to_camera_view` and writes them to the shot's JSON.
- For the exercise shots it also writes the **arm angles measured from the posed skeleton**. This is the same
  geometry rule as the station, and nothing is typed in by hand.
- Remotion reads the JSON (`video/src/track.ts`, `guide/gtrack.ts`). Callouts (`components/Callout.tsx`) are
  pinned to those pixels, and the angle HUD (`components/AngleHud.tsx`) shows the measured angles.

## 4. Dashboard screen capture (intro video)
1. Start the clinician dashboard in demo mode: `npm --prefix clinician run dev` (port 5175).
2. `node video/scripts/capture_dashboard.mjs <path-to-chrome-headless-shell.exe> [video/public/intro]`
   - Takes 2× screenshots of each screen at 1440×810.
   - Records the on-screen rectangles of the controls the video points at.
   - Uses the Chrome DevTools protocol on port 9334.
3. Remotion's `video/src/intro/` (`AuriIntro.tsx`, `Screen.tsx`, `brand.ts`) animates over those stills with the brand
   colours: Deep Teal #0A4A4F, Off-White #F5F2EA.

## 5. Soundtrack (synthesized, no licences)
`hub/.venv/Scripts/python.exe tools/audio/make_soundtrack.py` writes `video/public/audio/*.wav`. It uses no samples
and no third-party audio.

| Option | Writes |
|---|---|
| default (`--seconds 35`) | film music: 120 BPM (one beat = 15 frames at 30 fps), drop on the reveal at 12 s |
| `--guide 151` | `guide_bgm.wav` (calm bed) + `chime.wav` (new step) |
| `--intro 58` | `intro_bgm.wav` |

**Voice:** `video/out/voice.wav` (28 Oct, 5.4 MB) is the only narration file. No script in the repo generates it,
and no TTS engine is referenced. **[not found in repo: ask the user which tool and voice made it]**. The station's
voice coach should switch to that voice (see AGENT_HANDOFF_DEVICE_CV.md §0).

## 6. Remotion edit and render
- Preview: `cd video && npx remotion studio`
- Film: `cd video && npx remotion render PhysioBuddyFilm ../hardware/renders/physio_buddy_film_v2.mp4`
- Guide: `cd video && npx remotion render AssemblyGuide ../hardware/renders/physio_buddy_assembly_guide.mp4`
- Intro: `cd video && npx remotion render AuriIntro ../hardware/renders/auri_dashboard_intro.mp4`
- Fonts are Windows system faces (Bahnschrift, Cascadia Mono). Render on Windows, or change `src/theme.ts`.

## 7. Encoding frames, and the mobile copy
- Film footage: `hub/.venv/Scripts/python.exe video/scripts/encode_footage.py`, from `frames/v2` to
  `video/public/footage/<shot>.mp4`.
- Guide footage: `… encode_footage.py --guide [clip …]`. It also copies each clip's last frame as a still, held while
  the step text is read.
- Footage, guide stills and the long music bed are git-ignored, so regenerate them on a new machine.
- `physio_buddy_assembly_guide_mobile.mp4` is a smaller copy (14 MB) for phones. The exact ffmpeg settings used are
  **[not found in repo]**. A typical command is
  `ffmpeg -i in.mp4 -vf scale=-2:720 -c:v libx264 -crf 28 -preset slow -c:a aac -b:a 96k out_mobile.mp4`.

## 8. The DODO method (what we know)
- DODO was an earlier **movie project** made the same way: Claude planned and reviewed, and the Cursor agent rendered
  and measured. It ran as **10 phases over one Cursor chat**. Sources: the `cursor-bridge` skill
  (`~/.claude/skills/cursor-bridge/SKILL.md`) and the memory note `cursor-bridge-medha.md`.
- What carried over to Medha:
  - one persistent Cursor chat;
  - one phase per brief;
  - Claude reviews the real outputs itself (frames, contact sheets, logs, numbers) before the next phase;
  - Cursor pushes back with measurements.
- DODO's own files, its scenes and tools, and where the project lives are **[not found in repo: ask the user]**.

## 9. Unity
No Unity project, scene or script exists in this repo, the memory notes or the bridge skill. All 3D work here is
Blender (offline video) and three.js (the station page, `web/`). If Unity was used for DODO or anything else: **[not
found in repo: ask the user]**. Unity skills are installed in Claude Code (`unity:*`) but were not used here.

## 10. Skills, bridges and watchers we use

| Skill / tool | Used for |
|---|---|
| `cursor-bridge` | the Claude -> Cursor link: Claude plans, briefs and reviews; Cursor executes (§9 of the device handoff) |
| `remotion:*` (best-practices, render, studio, …) | composing and rendering the three videos |
| Blender via Python scripts (`tools/blender/`) | all 3D shots and assets; no Blender add-on is needed |
| `dataviz` | the dashboard's progress charts (validated palette) |
| `artifact-design` / Artifact | the shared demo of the clinician dashboard (`npm run artifact` build) |
| Monitor + `watch_cursor.py` | full live feed of Cursor's edits, commands, answers and git changes |
| Monitor + `watch_done.py` | **low-token** watcher: one `DONE <msg> <STATUS>` line per finished brief, or `STUCK` after 15 min |

Bridge commands, one terminal tab each:
```
& 'D:\medha\tools\cursor_bridge\LIVE\cursor_bridge.ps1' -Model grok-4.7-high -Workspace D:\medha
& 'D:\medha\tools\cursor_bridge\LIVE_IMU\cursor_bridge.ps1' -Model grok-4.7-high -Workspace D:\medha
```
- The skill's own example uses `-Model grok-4.7-xhigh`, the extra-high Grok. Run `agent models` to see what the
  account offers, and use the strongest one the user asks for.
- Watchers:
  - `hub/.venv/Scripts/python.exe tools/cursor_bridge/watch_done.py LIVE` (default);
  - `… watch_cursor.py LIVE` (when debugging).
- Re-arm a watcher whenever it expires.

## 11. Checklist for a new video
1. Write the storyboard as shots with lengths in frames at 30 fps, and keep it in one place: `timeline.ts`, or
   `steps.ts` for a guide.
2. Build or update the CAD and export GLB (§1). For a person, use the Rocketbox GLB.
3. Write or extend a Blender script that renders `test` stills first. Check them before rendering everything.
4. Render with OptiX and `--factory-startup`, and export tracking JSON from the same script.
5. Encode the frames (§7), keeping `-start_number`.
6. Make the music to the exact length (§5). Add narration only once the voice tool is known.
7. Edit in Remotion. Pin callouts to the tracking JSON, and never type in angles by hand.
8. Render, check it, then make a mobile copy if it will be shared on phones.
9. Brief Cursor with one phase per message, and review the frames yourself before the next phase.
