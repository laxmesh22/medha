# Auri — frozen-shoulder rehab (Medha · IIT Bombay, 31 Oct 2026)

Auri was called Physio Buddy. Package names stay (`physiobuddy_hub`); the exercise network stays PB-MotionNet.

The clinic station measures shoulder range from a camera and coaches three exercises (forward raise, side raise, outward rotation). The physiotherapist's dashboard is a separate app: a published plan does not reach the station. The arm, forearm and waist straps are not connected. The exercise network is advisory until `ml/validate_real.py` passes that exact model on held-out volunteers; the stand runs with `--motionnet off`.

## Parts

| Part | Where | Run |
|---|---|---|
| Station (hub + web UI) | `hub/`, `web/` | `hub\.venv\Scripts\python.exe -m physiobuddy_hub run --sim --motionnet off` then http://localhost:8000 |
| Movement judging | `ml/` | `hub\.venv\Scripts\python.exe ml\train_motionnet.py --public --folds 5` |
| Clinician dashboard | `clinician/`, live at https://auri-clinician.vercel.app | `$env:VITE_FORCE_DEMO='1'; npm run dev` in `clinician/` then http://localhost:5175 |
| Hardware CAD | `hardware/` | `tools\cad\.venv\Scripts\python.exe hardware\cad\physio_pod.py` |
| Films | `video/` | `npx remotion studio` in `video/` |

Stand steps, including the page build and the camera path: [docs/SHOWCASE.md](docs/SHOWCASE.md).

## Read these

- [docs/SHOWCASE.md](docs/SHOWCASE.md) — what to run on 31 Oct
- [AGENTS.md](AGENTS.md) — rules for agents editing this repo
- [CURSOR.md](CURSOR.md) — rules for the Cursor agent
- [ml/README.md](ml/README.md) — training and the validation gate
- [clinician/README.md](clinician/README.md) — dashboard, sign-in, demo data
- [agenthandoff.md](agenthandoff.md) and [jetson_realsense_ai_design.md](jetson_realsense_ai_design.md) — hardware, maths, architecture
- Jetson: [docs/setup_jetson.md](docs/setup_jetson.md)

First time on a laptop: `cd hub`, `uv venv --python 3.10 .venv`, `uv pip install --python .venv/Scripts/python.exe -e ".[camera,dev]"`, then `cd web; npm install` and `cd clinician; npm install`. Build the station page with `cd web; npm run build` before the run line above. Hot reload for the station UI: `cd web; npm run dev` (proxies to the hub on port 8000).

### Reference resources and how they're used
| Resource | Used for |
|---|---|
| [three.js](https://github.com/mrdoob/three.js) r186 | Rendering, GLTFLoader, OrbitControls, RoomEnvironment, CSS2DRenderer; **avatar models from its examples** (Michelle, Ready Player Me, Xbot). Demo-only licence, replace before product |
| [CodePen "Human Anatomy 3d"](https://codepen.io/grzegorz-rogala/pen/dPGKQgr) | *Techniques only* (its GLB/HDR assets are the author's and were not copied): layered skin/muscle/bone views with eased opacity cross-fades, ACES tone mapping + environment lighting, shadow-catcher floor → our **live X-ray** of the shoulder |
| [Lee et al. 2024, JNER 21:42](https://pmc.ncbi.nlm.nih.gov/articles/PMC10967210/) | 11-exercise label set, 24-feature + MLP baseline reproduced in `ml/`, LOSO evaluation added, extension-vs-ER confusion as a known risk |
| `content/` | Physio-approved exercise cards, plans, education | not started |

### Voice coach
**Speak** = the coach talks: corrections the moment form goes wrong, a right/wrong verdict after every rep, hold prompts.
**Listen** = talk to it: "how am I doing", "how many reps", "my best", "what muscles are working", "next exercise",
"pause" / "resume". Saying the patient is in pain stops the session with a fixed safety message.
Uses the browser's speech engine (Chrome/Edge). The mic works on the station itself (`localhost`); a tablet needs HTTPS.

### Regenerating 3D assets (Blender 5.x)
Raw downloads go in `assets_src/` (git-ignored):
```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup -P tools/blender/rocketbox_to_glb.py -- assets_src/rocketbox/Sports_Female_02 web/public/models/Sports_Female_02.glb
```
```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup -P tools/blender/build_anatomy.py -- assets_src/zanatomy web/public/models/anatomy_upper.glb
```
Licences and attribution: [web/public/models/LICENSES.md](web/public/models/LICENSES.md).
