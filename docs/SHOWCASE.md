# Auri at the stand — 31 Oct 2026

Plain steps for whoever is running the table. The station and the doctor dashboard are two separate demos. A plan published on the dashboard does not change the station.

## Before visitors

1. Build the station page, from the repo root:

```
cd web
npm run build
cd ..
```

2. Start the station on the synthetic patient. Do not add `--dataset-dir`. Recording must stay off.

```
hub\.venv\Scripts\python.exe -m physiobuddy_hub run --sim --motionnet off
```

3. Open http://localhost:8000. The header says Auri. The Record control says **Recording off**. Leave it like that.

4. Doctor dashboard **on the fictional demo patients** (the live site has no real patients yet, so signing in there
   shows an empty dashboard). In a second terminal:

```
cd clinician
$env:VITE_FORCE_DEMO = '1'
npm run dev
```

   Open http://localhost:5175. It shows "Demo data · fictional patients" at the top and needs no network except for
   the video call. The live site, https://auri-clinician.vercel.app, is for showing real Google sign-up only.

5. Have these films in a player, ready to press play:

- `hardware/renders/physio_buddy_film_v2.mp4` — the device on a person
- `hardware/renders/physio_buddy_device.mp4` — the pods
- `hardware/renders/auri_dashboard_intro.mp4` — the dashboard
- `hardware/renders/physio_buddy_assembly_guide.mp4` — how the pods go together

## If a RealSense is plugged in

Check first. This machine had no camera when the list was last run (it printed `[]`).

```
hub\.venv\Scripts\python.exe -m physiobuddy_hub devices
```

An empty list means there is no RealSense. Use the laptop webcam next, then `--sim`. If a camera is listed, the same command prints a gravity check. Then stop any sim station and start:

```
hub\.venv\Scripts\python.exe -m physiobuddy_hub run --motionnet off
```

In the log, the `gravity:` line should be a measured direction, not `assumed_level (replay/sim)`. Ask the person to stand about 2 to 2.5 m from the camera, whole body in frame. The page says to step closer or step back when they are outside 1.6–3.0 m.

## If there is no RealSense

The laptop webcam is the next fallback. It uses the teammate's AURI-CV engine, which is not part of this repo. Once, from the repo root:

```
git clone https://github.com/abdulmueez3-14/AURIII external/AURIII
git -C external/AURIII checkout 0011377
uv venv external/AURIII/.venv --python 3.12
uv pip install --native-tls -r external/AURIII/requirements.txt
```

Then:

```
hub\.venv\Scripts\python.exe -m physiobuddy_hub run --webcam 0 --motionnet off
```

The page shows the hub's own angles and, beside them, a Webcam engine card with the other engine's numbers. The coach still counts from the hub's skeleton. Degrees are still geometry. An empty room should say the measurement is unavailable.

## Five minutes with a visitor

The synthetic patient moves on its own, in a loop of about 36 seconds: forward raise, then a side raise with a lean and a shrug, then outward rotation, then a reach behind the back where the wrist disappears. Watch the line under the exercise name (`Seen: …`) and click the matching exercise. You do not need the visitor to copy the motion when you are on `--sim`.

1. The page opens on **Pain check**. Press **2** or **3**. Do not press 6 or higher unless you mean to stop: that pauses the coach and shows “Please stop and rest. Tell your physiotherapist about this pain.” To go on after that, press **Speak** (that also turns the voice on).

2. Leave **Forward raise** selected. When the figure raises the arm forward, the angle is the measured elevation. During the side-raise part of the loop the coach says “Body lean is adding fake range. Move from the shoulder.” That rep is not counted. The summary later says it was a side raise while forward raise was selected.

3. When the line says **Seen: side raise**, click **Side raise**. The coach can say “Keep your trunk upright: you are leaning sideways.”

4. Shrug is the fragile step. Press **Calibrate rest** while the arm is down (`Seen` is rest, or the arm has just lowered). If it says the patient moved, wait for the next time the arm is down and try once more. After that, during the side raise, the coach can say “Relax your shoulder down: avoid shrugging.” If rest calibration never succeeds, skip the shrug line and say so. It does not appear without a saved rest baseline.

5. Click **End session**. The card is titled **This session**. The first line is “Since your pain check at …”. That is why its rep count can be lower than the number in the header: the header is everything since the program started, the card is only since the check-in. Each exercise shows counted reps, rejected reps with the coach’s own sentence, and **Best angle:** or **Best angle: unavailable**. **Close** hides the card. **New session** clears the card’s numbers only. It does not restart the program, and it asks for pain again.

6. On the dashboard: overview first (who needs attention, any video calls). Open **Patients**, then one person. **Progress** shows **Range of motion**. **Care plan**, then **Publish plan** (or **Publish version N**). Say that this is the doctor’s record. The station on the table does not load that plan. **Video calls**, then start a call only if the network is up. It opens in a new tab. Skip the call if the network is poor.

## Say this plainly

- `--sim` is a synthetic patient, not a person and not the straps.
- With the camera, degrees come from the skeleton in the image. The arm, forearm and waist pods are not connected. Nothing on screen is an IMU angle.
- The exercise network is off (`--motionnet off`). There is no auto-detect and no network score.
- The target slider is labelled **Target (demo override)**. In clinic the physiotherapist sets the target. Do not drag it during the pitch unless someone asks.
- Dashboard people are fictional on the built-in demo. The live site shows whoever is actually signed in. Do not describe them as real patients.
- A published plan does not flow to the station.

## If something breaks

Stop the station with Ctrl+C in its window before starting another. Do not pass `--dataset-dir`.

1. RealSense, only if `devices` lists one: `hub\.venv\Scripts\python.exe -m physiobuddy_hub run --motionnet off` then http://localhost:8000
2. No RealSense: `hub\.venv\Scripts\python.exe -m physiobuddy_hub run --webcam 0 --motionnet off` then http://localhost:8000
3. Webcam missing or the page stays on “Step into the camera view”: `hub\.venv\Scripts\python.exe -m physiobuddy_hub run --sim --motionnet off` then http://localhost:8000
4. The page will not load: play `hardware/renders/physio_buddy_film_v2.mp4`, then `hardware/renders/auri_dashboard_intro.mp4`

Dashboard: the demo in step 4 runs offline. Without `$env:VITE_FORCE_DEMO = '1'` the local app uses the live
database (this laptop's `clinician/.env.local`) and needs the network.
