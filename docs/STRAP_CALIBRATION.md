# Strap calibration: how to get an accurate 3D figure

The figure on the station page is moved by the bands. Each band only knows how *it* is turned. Calibration teaches
the station how each band sits on your body. If calibration is sloppy, every movement after it is off by the same
mistake, so it is worth doing carefully. It takes about 20 seconds.

## Before you start

| Check | Why |
|---|---|
| Upper-arm band on **bare skin**, firm, outer side of the upper arm | Over a loose sleeve the box twists while the bone does not |
| Forearm band firm on the back of the forearm, battery inside the case | A loose box rocks when the wrist moves |
| Waist band on the belt, firm (optional) | Without it the figure still moves, but trunk lean and rotation are unavailable |
| Phone: Auri app **open on screen**, all bands connected | Phone battery saving freezes the app when the screen is off, and the station then gets nothing |
| Station page: Straps shows each band **connected · 50 Hz** | If a band says searching, the station is not getting its data |
| Station page refreshed with **Ctrl+Shift+R** | An old page has old buttons |

Which way the box faces on the arm does not matter. Calibration works that out.

## The steps (Guided calibration)

1. **Stand still** (3 s). Stand straight, arms hanging fully straight at your sides, palms toward your thighs. Do
   not move at all until the message changes. This sets "down" for every band.
2. **Forward raise** (4 s). Keep the elbow **completely straight** and lift the arm slowly forward, toward the
   camera, from your side to above shoulder height. Straight forward, not out to the side. This sets "forward" for
   each arm band and lines the forearm up with the upper arm.
3. **Lean forward** (only when the waist band is on, 4 s). Arms relaxed, bend slowly forward from the hips toward
   the camera, then come back up. This sets "forward" for the waist band.

## Read the message under the buttons

| Message | Meaning, what to do |
|---|---|
| `forearm matched to the arm within N°` | Good. Under about 8° is accurate. |
| `forearm not matched to the arm (keep the elbow straight)` | The elbow bent during the raise. Do the calibration again. |
| `moving (...)` | You moved during the stand-still step. Do it again and stay still. |
| `the upper-arm band did not move with the forearm` | A band is on the wrong body part, or the bands are swapped in the app. |
| `the waist band did not tip` | The waist band is not on the waist, or is lying on the table. |
| `lean not seen` | Bend a little further forward. |

## When to calibrate again

- Every time the bands are put on, or one slips.
- When the Straps panel says **Not calibrated**. The station clears calibration by itself when a band's sensor
  restarts (power dip, sensor error), because the band's "forward" changes.
- When the figure slowly turns away from where your arm points. The sensors drift a little over minutes.

## Checking accuracy

- With the camera: stand where it sees you from head to hips, then run
  `hub/.venv/Scripts/python.exe tools/compare_straps_camera.py --seconds 30`.
- Without the camera: hold arm down, forward raise level, side raise level and elbow at 90° for about 5 s each while
  running `hub/.venv/Scripts/python.exe tools/strap_pose_test.py --seconds 45`. Expect 0°, 90°, 90° and an elbow of
  90°.
