# Physio Buddy device film (Remotion)

The 35 s device film: Blender footage of the CAD units and the patient wearing them, edited in Remotion with tracked
callouts, a live angle HUD, transitions and a synthesized soundtrack.

| Step | Command (from the repo root) | Output |
|---|---|---|
| 1. Shots | `"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup -P tools/blender/device_film.py -- all --samples 96` | `hardware/renders/frames/v2/<shot>/` + `video/public/data/<shot>.json` |
| 2. Encode | `hub/.venv/Scripts/python.exe video/scripts/encode_footage.py` | `video/public/footage/<shot>.mp4` (git-ignored) |
| 3. Music | `hub/.venv/Scripts/python.exe tools/audio/make_soundtrack.py` | `video/public/audio/*.wav` |
| 4. Render | `cd video && npx remotion render PhysioBuddyFilm ../hardware/renders/physio_buddy_film_v2.mp4` | the film |

`npx remotion studio` previews it. Scene lengths live in `src/timeline.ts` and must match `LENGTHS` in
`tools/blender/device_film.py`; the music is 120 BPM (one beat = 15 frames) with the drop on the reveal (12 s).

- The angle HUD reads the arm angles that `device_film.py` measures from the posed skeleton each frame (geometry, the
  same rule as the station). Nothing is typed in by hand.
- Callouts are pinned to screen positions projected from the Blender cameras.
- Fonts are Windows system faces (Bahnschrift, Cascadia Mono): render on Windows, or change `src/theme.ts`.
- Cycles uses the OptiX denoiser: OpenImageDenoise took ~35 s a frame on this laptop (it picked the wrong device).
- All audio is synthesized by `make_soundtrack.py`: no samples, no licences to track.
