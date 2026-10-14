# Physio Buddy — Frozen Shoulder Rehab (Medha · IIT Bombay showcase 31 Oct 2026)

Wearable IMU straps + a **Clinic Station** (Jetson Orin Nano + RealSense D455f) that measures true shoulder range of
motion, detects compensation, and guides exercise. Read these first:

1. [agenthandoff.md](agenthandoff.md): project context, hardware, maths, safety rules
2. [jetson_realsense_ai_design.md](jetson_realsense_ai_design.md): hub architecture, neural net, RAG, edge/cloud, schedule

| Folder | What | Status |
|---|---|---|
| `hub/` | Python station: RealSense → RTMPose → depth lift → clinical angles → FastAPI/WebSocket | camera pipeline v0 ✅ |
| `web/` | Station UI (Vite + Three.js): clothed Rocketbox patient driven live, **real anatomy** X-ray/Anatomy views (277 bones, 72 muscles with fibre shading, glenohumeral capsule + ligaments), live right/wrong verdict, **voice coach** (speaks, listens, answers), AI vision overlay, rep history | ✅ |
| `hub/.../core/coach.py` | Rep phases, hold timer, per-rep verdict (correct / needs fixing + reasons), wrong-movement rejection | ✅ |
| `tools/blender/` | Asset pipeline: `rocketbox_to_glb.py` (clothed avatars), `build_anatomy.py` (rigged real anatomy) | ✅ |
| `firmware/` | XIAO ESP32-S3 + BNO085 strap firmware | not started (parts ordering) |
| `cloud/` | Railway: sync API, clinician dashboard, LLM proxy (Claude + DeepSeek) | not started |
| `ml/` | Lee 2024 baseline reproduced + LOSO evaluation; PB-MotionNet next | baseline ✅ |

### Reference resources and how they're used
| Resource | Used for |
|---|---|
| [three.js](https://github.com/mrdoob/three.js) r186 | Rendering, GLTFLoader, OrbitControls, RoomEnvironment, CSS2DRenderer; **avatar models from its examples** (Michelle, Ready Player Me, Xbot). Demo-only licence, replace before product |
| [CodePen "Human Anatomy 3d"](https://codepen.io/grzegorz-rogala/pen/dPGKQgr) | *Techniques only* (its GLB/HDR assets are the author's and were not copied): layered skin/muscle/bone views with eased opacity cross-fades, ACES tone mapping + environment lighting, shadow-catcher floor → our **live X-ray** of the shoulder |
| [Lee et al. 2024, JNER 21:42](https://pmc.ncbi.nlm.nih.gov/articles/PMC10967210/) | 11-exercise label set, 24-feature + MLP baseline reproduced in `ml/`, LOSO evaluation added, extension-vs-ER confusion as a known risk |
| `content/` | Physio-approved exercise cards, plans, education | not started |

## Quick start (laptop, Windows)
```bash
cd hub
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[camera,dev]"
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m physiobuddy_hub fetch-models
```
```bash
cd web && npm install && npm run build
```
Then run one of:
```bash
hub/.venv/Scripts/python.exe -m physiobuddy_hub run --sim
```
```bash
hub/.venv/Scripts/python.exe -m physiobuddy_hub run --debug-video --log
```
Open http://localhost:8000. For UI work with hot reload: `cd web && npm run dev` (proxies to the hub on :8000).

Jetson: see [docs/setup_jetson.md](docs/setup_jetson.md).

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
