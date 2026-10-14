# Physio Buddy — Agent Handoff (Frozen Shoulder Rehab Wearable)

> **Read this whole file before doing anything.** It is the single source of truth for the project state as of
> **13 October 2026**. It covers context, decisions already made (and why), hardware, wiring, firmware spec, maths,
> web-app spec, CV/AI, validation, safety/standards, build plan, pitfalls and open questions.

---

## ⚠ Update 14 Oct 2026: read `jetson_realsense_ai_design.md` next

The project now lives in `D:\medha\` (paths in §1 are from the old machine). The CV/AI direction changed:
- **Portable edge hub:** Jetson Orin Nano Super + RealSense D455/D435i on a tripod. It receives both BLE straps, runs
  depth-based 3D pose and the neural nets, and serves the UI to any browser over Wi-Fi. The browser becomes UI-only and
  Web Bluetooth is dropped from the main path. The hub code is one Python codebase that also runs on a laptop (dev + fallback).
- **PB-MotionNet:** a small causal multimodal TCN (IMU + depth-skeleton) for exercise recognition + "unknown" rejection,
  rep phases, and compensation flags. It **never outputs the ROM angle** (geometry does that).
- **Exercise suggestion:** safety rules → clinician plan filter → transparent ranking → RAG/LLM for explanation only.
  RAG retrieves; it is not trained on sensor data.
- **Hardware owned:** Jetson Orin Nano + **RealSense D455f** (budget conflict resolved; MyoWare + webcam dropped).
- **Showcase: 31 Oct 2026 at IIT Bombay as a Clinic Station.** Code freeze 28 Oct. Day plan + demo script in the design doc §17.
- **Hybrid edge + cloud:** everything real-time and safety-related on the Jetson (works offline). The cloud handles the LLM
  (via a proxy; Claude, with on-device llama.cpp + template fallback), de-identified sync, the clinician dashboard, and training (§16).
- Firmware gains `COMMAND 0x06` time-sync ping. All core design rules in §0 still apply.
- **Team of 3** (A hardware/firmware, B vision/Jetson/ML, C app/cloud/AI). Cloud = **Railway**. LLMs = **Claude + DeepSeek**
  (+ on-device + templates). Strap parts to be ordered by 15 Oct.
- **Code state 14 Oct:** `hub/` camera pipeline v0 (RealSense D455f → RTMPose → depth lift → clinical angles → FastAPI WS,
  32 tests, `--sim` mode) + `web/` Three.js UI. See `README.md` and `docs/setup_jetson.md`.

---

## 0. TL;DR for the next agent

- **What:** "Physio Buddy" — a wearable strap system + browser app that **measures true shoulder range of motion
  (ROM)** for **frozen shoulder (adhesive capsulitis)** patients, guides home exercises with a **Three.js 3D avatar**,
  cross-checks with **OpenCV/MediaPipe** camera pose, and uses an **AI coach** for rep counting, hold timing,
  exercise recognition and compensation detection.
- **Event:** **Medha Hackathon** (student team; user = laxmeshankola@gmail.com / GitHub `SKULLNIN`; a senior,
  *Aditya Singh*, suggested BNO055 + LiPo + charging module + velcro band).
- **State:** Research + hardware BOM **done** (PDF exists). **No code written yet. No hardware ordered yet**
  (unless the user tells you otherwise — ask).
- **Core hardware decision:** 3 × **BNO085/BNO086** IMUs (upper arm, forearm, sternum) + 2 × **Seeed XIAO
  ESP32-S3** (on-board LiPo charging) + 500 mAh protected LiPos + haptic motor; optional **MyoWare 2.0 EMG**.
  Full kit ≈ **₹27,229**, minimum kit ≈ **₹12,475** (budget cap ₹30,000).
- **Core design rules (from the team's own standards document — do not violate):**
  1. Shoulder angle = **relative orientation of upper arm vs torso**, not a single sensor's world angle.
  2. **Never blindly average** IMU and camera angles — use explicit fusion states (§9.4).
  3. **Never output 0°** when data is missing — output "measurement unavailable" + retry.
  4. Every measurement carries a **quality flag**; low quality ⇒ ask to recalibrate/repeat.
  5. **Exercise progression is clinician-defined** — never auto-increase difficulty from ROM trend alone.
  6. No diagnosis, no medication advice, no "medical-grade / ISO-certified / clinically validated" claims.
- **Next step:** ask the user what they want first (likely: ESP32 firmware for 2×BNO085 → BLE, then the Web
  Bluetooth + Three.js page). Follow the build plan in §13.

---

## 1. Files & locations

| What | Path |
|---|---|
| This handoff | `C:\Users\guutu\OneDrive\ドキュメント\PhysioBuddy\agenthandoff.md` |
| Hardware + research PDF (7 pages, BOM with buy links, wiring, evidence, references) | `PhysioBuddy\docs\Medha_FrozenShoulder_Hardware_Research.pdf` (copy also in `ドキュメント\future plan\`) |
| Python (reportlab) script that regenerates that PDF | `PhysioBuddy\docs\make_research_pdf.py` — run `python make_research_pdf.py <out.pdf>` (needs `reportlab`; Python 3.11 is installed). Use `PYTHONIOENCODING=utf-8` on Windows because the path contains Japanese characters. |
| **Team's product/standards document** (authoritative on product rules) | `C:\Users\guutu\OneDrive\ドキュメント\Physio_Buddy_Product_Engineering_and_Standards_Discussion_Document.docx` (dated 11 Oct 2026). Read with `python-docx`. Summary in §11. |
| Key paper the user shared | Lee K. et al. 2024, *J NeuroEng Rehabil* 21:42 — https://pmc.ncbi.nlm.nih.gov/articles/PMC10967210/ (summary in §3.3) |

**Important:** `ドキュメント\future plan\` is a **different project** (SkyShield C-UAS trainer, SIH PS 26247) with
its own `AGENT_HANDOFF.md`, `PLAN.md`, `backend/`, `frontend/`, `ros2_ws/`. **Do not put Physio Buddy code there and
do not overwrite its files.** Physio Buddy lives in `ドキュメント\PhysioBuddy\`. It is not a git repo yet — offer
`git init` when code starts.

Environment: Windows 10, PowerShell + Git Bash, Python 3.11.9, reportlab 5, pypdfium2, python-docx available.

---

## 2. Problem statement & product definition

**Problem statement (hackathon):** build a rehabilitation device for frozen shoulder. Team idea: (1) a connected
strap that tracks body movement; (2) a Three.js human model driven by the strap + an OpenCV model + an AI model that
tracks movement and helps patients exercise.

**Working product definition (from team doc):** *"Physio Buddy is a clinician-supported wearable and software
platform that assesses defined shoulder movements, tracks changes in movement and symptoms over time, and supports
appropriate home exercise guidance. It provides an initial assessment and referral pathway for people with shoulder
pain or restricted movement, alongside recovery monitoring for patients with an established clinical care plan. It
does not replace professional diagnosis or treatment decisions."*

Two pathways, one platform:
- **A. Initial assessment / referral:** symptom intake + standardized movement measurement + flag for clinician review.
- **B. Recovery monitoring:** clinician-approved exercise plan, guided sessions, ROM + symptom trends, adherence,
  escalation.

**Version 1 / hackathon scope (recommended):** pathway B core loop —
`symptom check-in → calibrate → measure defined movements → quality check → guided exercise → progress report → escalation flag`.
Movements first: **flexion, abduction, external rotation** (+ internal rotation if time).

---

## 3. Clinical & research background (verified via web research, 13 Oct 2026)

### 3.1 The condition
- Adhesive capsulitis = capsular inflammation → fibrosis; painful loss of **active and passive** motion.
- Prevalence ~**2–5%** general population; **~10–30% in diabetics** (3–10× risk) → very relevant for India.
- Stages: **freezing** (painful, ~2–9 mo) → **frozen** (stiff, ~4–14 mo) → **thawing** (~5–24 mo); self-limiting
  over 1–3 years but exercise helps.
- **Capsular pattern:** external rotation (ER) most limited > abduction > internal rotation (IR). ⇒ the device
  **must measure rotation**, hence the forearm IMU (ER/IR measured with elbow at 90°).
- Normal reference ROM for progress bars: flexion ~180°, abduction ~180°, ER ~90°, IR ~70°, extension ~60°.
  Patient targets come from the physiotherapist.

### 3.2 Why the product matters
- **Adherence is poor:** shoulder home-exercise adherence ~40–55%; a wearable-tracked cohort exercised on only 41%
  of assigned days and declined over time; only 29% of shoulder RCTs even report adherence.
- **Compensation:** patients shrug (upper-trapezius overactivity / scapular hiking) and lean the trunk to fake ROM;
  EMG shows higher upper/lower trapezius ratio in frozen shoulder; neck muscles (scalenes, levator scapulae)
  over-recruited.
- **No objective home measurement** — goniometer only at clinic visits.

### 3.3 Evidence for our tech (use in pitch)
| Source | Finding | Use |
|---|---|---|
| 2024 systematic review/meta-analysis (15 studies, 372 ppl) | Digital ROM devices vs goniometer pooled bias −0.25°; no diff sensor vs camera | Digital measurement valid |
| Rigoni 2019, *Sensors* | IMU vs goniometer ICC > 0.90, LoA < ±5° (same tester) | IMU accuracy acceptable |
| Ajčević 2020 (arXiv 2010.16169) | 2 Xsens IMUs (scapula + humerus) in 6 frozen-shoulder pts; tracked ROM + scapulohumeral rhythm, detected improvement | 2-sensor approach precedent |
| Chen 2020, *JMIR* 22(7):e17032 | Wearable IMU kit + apps for adhesive capsulitis home exercise, feasible | Closest prior art; we add avatar, CV, AI, compensation |
| **Lee 2024, *JNER* 21:42 (user-shared)** | One wrist MPU9250 @100 Hz, 58 pts (adhesive capsulitis + rotator cuff), 11 exercises; 24 features (min/max/mean/var of accel+gyro per axis) → DNN (hidden 8-16-32-64-128, ReLU, softmax) → **92.5% test accuracy**; banded extension vs banded ER confused (similar wrist path); only 80:20 split, no external validation | Template for our exercise classifier; multi-IMU fixes its confusion |
| MediaPipe studies (*Sensors* 2024; *Measurement* 2023) | Shoulder ROM MAPE 14.9–25%; fails with occlusion/depth | Camera alone insufficient ⇒ IMU primary |
| SWORD Health RCT (*JMIR*, 82 pts) + 296-pt study | Sensor-based digital PT = in-person PT for shoulder function; 79% completion | Market/clinical proof |
| Zhu 2023 *IEEE TNSRE*; Bonfiglio 2025 | Sensor-to-segment misalignment dominates shoulder-angle error; static **N-pose** calibration recommended | Calibration design |
| BNO085 spec (SparkFun/Adafruit) | Rotation vector 2.0° static / 3.5° dynamic; **game rotation vector 1.5° static / 2.5° dynamic, 0.5°/min yaw drift**; geomagnetic RV 3.0°/4.5° | Why BNO085, why game RV |

Full reference list with URLs: PDF §5 and §16 below.

---

## 4. System architecture

```
 ┌──────────── Unit A: UPPER ARM (neoprene armband) ────────────┐      ┌──── Unit B: STERNUM (chest strap) ────┐
 │ XIAO ESP32-S3 ── I2C ── BNO085 #1 (upper arm, 0x4A)          │      │ XIAO ESP32-S3 ── I2C ── BNO085 (0x4A) │
 │        │        └─ I2C ── BNO085 #2 (forearm, 0x4B, 30cm cbl) │      │ LiPo 500mAh + switch                   │
 │        ├─ I2C ── DRV2605L (0x5A) ── coin vibration motor     │      └───────────────┬───────────────────────┘
 │        ├─ A0  ── MyoWare 2.0 ENV (optional, upper trapezius) │                      │ BLE notify
 │        └─ LiPo 500mAh + slide switch (charge via USB-C)      │                      │
 └──────────────────────────────┬───────────────────────────────┘                      │
                                │ BLE notify (quaternions, 50–100 Hz)                  │
                                ▼                                                      ▼
 ┌──────────────────────── Laptop: Chrome/Edge (Web Bluetooth, HTTPS or localhost) ────────────────────────┐
 │ ble.js → calib.js (N-pose + functional) → kinematics.js (relative orientation → clinical angles)         │
 │ cv.js (MediaPipe PoseLandmarker on webcam) → fusion.js (explicit state machine, quality flags)           │
 │ coach.js (rep/hold state machines, exercise classifier, haptic/voice cues) → avatar.js (Three.js GLB)    │
 │ store.js (IndexedDB sessions) → dashboard.js (trends, adherence) → report.js (PDF for physio)            │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Responsibility split (team doc): wearable measures → firmware timestamps/streams → software estimates orientation
and quality → app explains results → clinician defines care → escalation logic flags concerns.

**Open alternative:** wire the chest IMU to Unit A by a cable over the shoulder (one MCU, one BLE link, shared clock)
instead of two BLE units. Two units = cleaner to wear; one unit = simpler sync. Not yet decided (§15).

---

## 5. Hardware — final BOM (≈ ₹27,229, cap ₹30,000)

Prices seen 13 Oct 2026 — **re-check before ordering**. Robu.in blocked direct fetch; some Robu URLs were inferred
from mirror domains (st./stg./aws.robu.in) → verify they open. "search" = no exact product page found.

| # | Item | Qty | Unit ₹ | Total ₹ | Link |
|---|---|---|---|---|---|
| 1 | 7Semi **BNO085** 9-DOF Qwiic breakout | 3 | 2,393 | 7,179 | https://robocraze.com/products/bno085-imu-9-dof-orientation-qwiic-fusion-breakout-7semi |
| 2 | BNO085 Nano breakout (spare) | 1 | 2,089 | 2,089 | https://robocraze.com/products/bno085-9-dof-orientation-imu-sensor-fusion-nano-breakout-board |
| 3 | **Seeed XIAO ESP32-S3** | 2 | 1,089 | 2,178 | https://robocraze.com/products/seeed-studio-xiao-esp32-s3-development-board-supports-wi-fi-bluetooth-5-0 |
| 4 | Seeed XIAO ESP32-C3 (spare MCU) | 1 | 734 | 734 | https://robocraze.com/products/seeed-studio-xiao-esp32c3 |
| 5 | LiPo 3.7 V 500 mAh PCM-protected (WLY752530) | 3 | 199 | 597 | https://robu.in/product/500mah-pcm-protected-micro-li-po-battery |
| 6 | TP4056 Type-C w/ protection (only for non-XIAO boards) | 3 | 21 | 63 | https://robu.in/?p=835842 |
| 7 | DRV2605L haptic driver (SmartElex) | 2 | 399 | 798 | https://robu.in/product/smartelex-haptic-motor-driver-drv2605l |
| 8 | ERM coin vibration motor 10 mm | 5 | 53 | 265 | https://robu.in/?p=1358106 |
| 9 | Qwiic/STEMMA QT cable 150 mm, female sockets | 4 | 159 | 636 | https://robu.in/product/4-pin-cable |
| 10 | Qwiic/STEMMA QT cable 100 mm, JST-SH both ends | 2 | 129 | 258 | https://robu.in/product/adafruit-stemma-qt-qwiic-jst-sh-4-pin-cable-100mm-long |
| 11 | Mini slide switch SS-12D00 (listing inconsistent — verify) | 10 | ~2 | 20 | https://robu.in/?p=1883688 |
| 12 | **MyoWare 2.0** EMG (optional) | 1 | 6,015 | 6,015 | https://www.tanotis.com/products/myoware-2-muscle-sensor |
| 13 | 3M ECG/EMG gel electrodes ×100 | 1 | 999 | 999 | https://robu.in/product/ecg-gel-electrode-3m-pack-of-100 |
| 14 | Neoprene velcro armband (11–15 in) | 2 | 299 | 598 | https://shop.globalbees.com/products/protect-x-strauss-mobile-arm-band-black (alt: https://www.amazon.in/s?k=neoprene+sports+armband+velcro) |
| 15 | Elastic chest strap / harness mount | 1 | ~500 | 500 | search: https://www.amazon.in/s?k=chest+strap+harness+mount+elastic |
| 16 | Velcro strap roll 25 mm | 1 | ~200 | 200 | search: https://www.amazon.in/s?k=velcro+strap+roll+25mm |
| 17 | 12-inch plastic goniometer (validation) | 1 | ~300 | 300 | search: https://www.amazon.in/s?k=goniometer+12+inch+physiotherapy |
| 18 | Logitech C270 webcam (optional) | 1 | ~1,300 | 1,300 | search: https://www.amazon.in/s?k=logitech+c270+webcam |
| 19 | Misc: perfboard, silicone wire, heat-shrink, JST-PH 2-pin leads, headers, **2×100 kΩ resistors for battery divider**, 3D-printed PLA cases | lot | – | 1,500 | https://robu.in/?s=perfboard |
| 20 | Shipping buffer | – | – | 1,000 | – |
| | **Total** | | | **≈ 27,229** | |

**Minimum kit (≈ ₹12,475):** 3× BNO085 Qwiic, 2× XIAO ESP32-S3, 2× LiPo, 2 coin motors + 2N2222 (no DRV2605L),
4 Qwiic cables, armband + chest strap + velcro, goniometer, misc.

### 5.1 Why these parts (decisions + rejected alternatives)
- **BNO085/086 over BNO055:** same Bosch silicon but CEVA/Hillcrest SH-2 firmware; published accuracy figures;
  **game rotation vector** ignores the magnetometer (indoor metal/laptops distort mag). BNO055 has no published
  fusion heading accuracy, users report heading drift at rest, needs calibration routine, and has ESP32 I2C
  clock-stretching issues; breakouts are hard to buy in India (Hubtronics sells only the bare chip). Keep BNO055
  only as a fallback if the senior already owns one.
- **BNO086 (7Semi VR Qwiic, ₹2,449)** is an equal/better substitute: https://robocraze.com/products/bno086-vr-imu-9-dof-orientation-qwiic-fusion-breakout-7semi
  (I2C/SPI/UART, solder-jumper addresses **0x4B default / 0x4A alt** — note default differs from Adafruit's 0x4A).
- **Adafruit BNO085** (genuine, ₹2,599 on Robu): https://robu.in/product/adafruit-9-dof-orientation-fusion-bno080-stemma-qt
- **ICM-42688-P + magnetometer:** team doc's research option — full control of fusion (Madgwick/Mahony/Kalman), more
  work. Not for the hackathon.
- **Rejected:** MPU6050/MPU9250 (no on-chip fusion, yaw drift, inconsistent modules); Arduino Nano/Uno (no BLE, no
  charging).
- **XIAO ESP32-S3:** 21×17.5 mm, dual-core 240 MHz, BLE 5, Wi-Fi, 8 MB PSRAM/flash, **built-in LiPo charger
  (~100 mA)** via BAT pads on the underside. **No built-in battery-voltage pin** → add 100k/100k divider to an ADC pin.
- **Two IMUs minimum, three ideal:** sternum IMU cancels trunk lean; forearm IMU gives ER/IR. Team doc says "define
  minimum sensor count through experiments" — the forearm IMU is justified by the capsular pattern.

---

## 6. Wiring

### 6.1 XIAO ESP32-S3 pin map (verify against Seeed wiki before soldering)
| XIAO pin | GPIO | Use |
|---|---|---|
| D4 | GPIO5 | **I2C SDA** |
| D5 | GPIO6 | **I2C SCL** |
| D0/A0 | GPIO1 | MyoWare ENV (analog) |
| D1/A1 | GPIO2 | Battery voltage via 100k/100k divider (reads Vbat/2) |
| D2 | GPIO3 | BNO085 INT (optional, recommended) |
| D3 | GPIO4 | BNO085 RST (optional, recommended — lets firmware hard-reset a hung IMU) |
| 3V3 / GND | – | Power to IMUs, DRV2605L, MyoWare (MyoWare 2.0 runs at 3.3 V) |
| BAT+/BAT− pads (underside) | – | LiPo through slide switch on BAT+ |

### 6.2 I2C bus per unit
| Device | Address | Notes |
|---|---|---|
| BNO085 upper arm | 0x4A | Check board default (7Semi BNO086 defaults 0x4B) |
| BNO085 forearm | 0x4B | Set via solder jumper / DI/ADR pin; 30 cm thin 4-core cable |
| DRV2605L | 0x5A | Default firmware set for ERM motors (our coin motor is ERM) |

- I2C at **100–400 kHz**; drop to 100 kHz if flaky. Keep the 30 cm forearm run twisted/short. If I2C remains
  unreliable with BNO08x on ESP32 (known pain point), switch that IMU to **SPI** or **UART-RVC** mode.
- Without DRV2605L: GPIO → 1 kΩ → 2N2222 base; motor between 3V3 and collector; **flyback diode** across motor.

### 6.3 Mechanical
- IMU must be **rigid relative to the segment**: 3D-printed base + neoprene + velcro; sensor on **lateral upper arm**
  (mid-humerus, avoid deltoid bulge), **dorsal distal forearm** (near wrist), **flat on sternum**.
- Mark orientation arrows on cases; same placement every session (team doc: standardize location, orientation,
  strap tension).
- LiPo: only PCM-protected cells, enclosed; **never charge while worn**.

---

## 7. Firmware spec (not yet written)

**Toolchain:** Arduino IDE 2 or PlatformIO; board package "esp32 by Espressif", board `XIAO_ESP32S3`.
**Libraries:** `SparkFun BNO08x Arduino Library` (handles INT/RST well) or `Adafruit BNO08x`; `NimBLE-Arduino`
(lighter than stock BLE); `Adafruit DRV2605` (haptics).

**IMU config:** enable **`SH2_GAME_ROTATION_VECTOR`** at 100 Hz (10 000 µs) — no magnetometer. Optionally enable
`SH2_ACCELEROMETER` + `SH2_GYROSCOPE_CALIBRATED` at 50–100 Hz for the exercise classifier/raw logging (team doc wants
raw data logged). Note: game RV yaw is relative to each sensor's power-on heading → sensors do **not** share yaw;
the calibration step (§8.2) aligns them; recalibrate every session / ~10 min (0.5°/min drift).

**BLE GATT (custom; generate real 128-bit UUIDs once and keep them fixed):**
| Characteristic | Props | Content |
|---|---|---|
| `IMU_DATA` | notify | one packet per sensor sample (below) |
| `RAW_DATA` (optional) | notify | accel+gyro int16 ×6 + seq |
| `COMMAND` | write | 0x01 tare/re-init, 0x02 haptic pattern `<id>`, 0x03 set rate `<Hz>`, 0x04 start/stop stream, 0x05 IMU hard reset |
| `STATUS` | read/notify | battery mV, firmware version, per-IMU OK/fault, I2C error count |
| Standard Battery Service 0x180F | read/notify | % |

**IMU_DATA packet — 17 bytes, little-endian (fits the default 20-byte ATT payload, no MTU negotiation needed):**
```
offset size  field
0      1     unit_id(4 bits) | sensor_id(4 bits)   // A=1,B=2 ; 0=upper arm,1=forearm,2=chest
1      1     flags: bit0 valid, bit1 calib_ok, bits2-3 BNO accuracy(0-3), bit4 reset_occurred
2      2     seq (uint16, wraps) → detect dropped samples
4      4     t_ms (uint32, device millis at sample)
8      8     qw,qx,qy,qz int16, Q14 (value/16384.0)
16     1     emg_env (uint8, 0-255) or 0
```
- Stream at **50 Hz default** (2 sensors × 50 = 100 notifies/s); 100 Hz if the link holds.
- Device names: `PB-ARM`, `PB-CHEST`. Haptic patterns: 1 = target reached, 2 = hold complete, 3 = warning/compensation,
  4 = stop.
- Firmware must: detect IMU silence > 200 ms → set valid=0 and try reset; never fabricate samples.

---

## 8. Maths — from quaternions to clinical angles

### 8.1 Conventions
- Firmware sends sensor orientation `q_s` (sensor frame → BNO world frame), Hamilton, (w,x,y,z).
- **Three.js `Quaternion.set(x, y, z, w)` order** — reorder!
- Anatomical frame (ISB-like): **Y up** (superior), **X anterior**, **Z right-lateral**. Thorax frame T, humerus frame H
  (Y along long axis toward shoulder), forearm frame F.

### 8.2 Calibration (sensor-to-segment)
1. **Static N-pose, 3 s** (standing, arms at sides, palms facing thighs, looking forward). Average each sensor's
   quaternion → `q_s0`. Gravity in each sensor frame gives that segment's **vertical (Y) axis**.
2. **Functional step:** slow forward flexion of the affected arm to ~60° (or as tolerated) and back. Integrate the arm
   sensor's rotation → rotation axis ≈ **mediolateral (Z)** axis of humerus. Forearm: elbow flexion 0→90° gives its
   Z axis. Thorax Z assumed parallel to humerus Z at N-pose (or use a short trunk-rotation/bow movement).
3. Build each segment's anatomical axes in sensor coordinates (Y from gravity, Z from functional axis, X = Y×Z,
   re-orthogonalize) → constant mounting rotation `R_mount_i` (segment→sensor).
4. Segment orientation at time t: `q_seg_i(t) = q_s_i(t) ⊗ R_mount_i`.
5. **Relative (joint) orientation:** `q_TH = conj(q_seg_T) ⊗ q_seg_H` (humerus in thorax), `q_HF = conj(q_seg_H) ⊗ q_seg_F`.
   Because both are relative, the different per-sensor yaw references cancel **only through the shared N-pose
   instant** — so step 1 must happen with all sensors simultaneously, and re-run when drift accumulates.
6. Quality gates for calibration: sensors stationary (gyro norm < ~3°/s) during N-pose; functional axis consistency;
   else reject and repeat.

(Fallback for the earliest prototype: N-pose only, assume `R_mount` = identity-to-N-pose; good enough for a demo
avatar, not for angle claims.)

### 8.3 Clinical angles
- Humerus long-axis direction in thorax frame: `u = rotate(q_TH, (0,-1,0))` (pointing down the arm).
- **Elevation** = `acos(dot(u, (0,-1,0)))` → 0° arm at side, 180° overhead.
- **Plane of elevation** = `atan2(u.z, u.x)` of the projection on the transverse plane → ~0° = forward (flexion),
  ~90° = side (abduction). Report "flexion" when plane within ±30° of anterior, "abduction" when within ±30° of lateral
  (scapular plane ~30–40° in between).
- ISB-recommended full decomposition for humerothoracic: **Y-X-Y Euler** (plane of elevation, elevation, axial
  rotation). Beware gimbal lock near 0° elevation.
- **External/internal rotation** (protocol: elbow at side, flexed 90°): forearm direction `f = rotate(q_seg_F, (1,0,0))`
  expressed in thorax frame, projected on transverse plane; angle from anterior axis X toward lateral = **ER**, toward
  medial = **IR**.
- **Compensation metrics:**
  - Trunk lean = angle between thorax Y axis and world vertical (from sternum IMU gravity) — sagittal and frontal.
  - "Apparent vs true" = arm elevation relative to **world vertical** (single sensor) vs relative to **thorax** →
    the gap is trunk compensation; show both on screen (strong demo).
  - **Shrug / scapular hiking cannot be measured by a sternum IMU.** Use (a) MyoWare EMG on upper trapezius (rise above
    baseline envelope), and/or (b) MediaPipe: shoulder-landmark height relative to ear landmark, normalized by
    shoulder width, vs baseline. Say this honestly.
- Smoothing: light low-pass on angles (e.g., 1€ filter) for display only; **raw values** go to metrics/log.

---

## 9. Web app spec (not yet written)

### 9.1 Stack
- **Vite + vanilla JS/TypeScript** (or React if the team prefers), **Three.js** (pin an exact version, e.g. `three@0.16x`),
  **@mediapipe/tasks-vision** `PoseLandmarker` (in-browser, WASM/GPU), **Web Bluetooth** (Chrome/Edge on
  Windows/Android/macOS; **not iOS Safari**; requires HTTPS or `localhost`; `requestDevice` needs a user click,
  once per unit), IndexedDB for sessions, jsPDF for reports, Chart.js/uPlot for trends.
- Optional Python side (FastAPI) only if needed for an ML model or clinician dashboard backend; keep the measurement
  engine in the browser for the demo.

### 9.2 Proposed structure
```
PhysioBuddy/
  firmware/pb_unit/            # Arduino/PlatformIO sketch, unit role via #define UNIT_ARM / UNIT_CHEST
  web/
    index.html
    src/ble.js                 # connect PB-ARM, PB-CHEST; parse 17-byte packets; seq-gap + timeout detection
    src/calib.js               # N-pose + functional calibration, quality gates
    src/kinematics.js          # quaternion maths, relative orientation, clinical angles
    src/cv.js                  # webcam + PoseLandmarker; landmark visibility; shrug metric
    src/fusion.js              # explicit state machine (§9.4)
    src/coach.js               # exercise state machines, rep/hold, cues, classifier hook
    src/exercises/*.json       # clinician-approved exercise definitions (§10)
    src/avatar.js              # Three.js scene, GLB humanoid, bone retargeting, ghost target pose
    src/store.js               # IndexedDB: sessions, raw logs, versions
    src/dashboard.js / report.js
    public/models/humanoid.glb # rigged model (e.g., Mixamo "Y Bot" or three.js examples Xbot.glb)
  ml/                          # exercise classifier training (Python), exported to ONNX/TF.js
  docs/                        # PDF + generator + test logs
```

### 9.3 Three.js avatar
- Load rigged GLB with `GLTFLoader`; Mixamo bone names: `mixamorigSpine2` (chest), `mixamorigRightArm` (upper arm),
  `mixamorigRightForeArm`, `mixamorigLeftArm`… Make side (left/right affected shoulder) configurable.
- Drive bones with **relative** rotations: `bone.quaternion = bindLocal ⊗ q_delta`, where `q_delta` is the segment's
  rotation since N-pose expressed in the bone's local frame (convert via parent's bind world rotation). The N-pose
  must match the model's rest pose (Mixamo rest is T-pose → apply a fixed arm-down offset).
- Show a translucent **ghost arm** at the target angle, an angle arc, and colour feedback (green in target zone,
  amber approaching limit, red = compensation/unsafe).
- `slerp` toward the latest sample each frame for smoothness (display only).

### 9.4 IMU + camera fusion — explicit states (team-doc mandated)
| IMU | CV | Action |
|---|---|---|
| valid | valid & consistent (within a validated tolerance) | use validated fusion rule (IMU primary; CV as check) |
| valid | valid but disagree | flag, ask to repeat; do not average |
| valid | invalid (occluded/low visibility) | use IMU **only if validated for that exercise** |
| invalid | valid | use CV only if validated for that exercise (e.g., not behind-back IR) |
| invalid | invalid | **"Measurement unavailable"** — never 0° |

- CV validity: landmark `visibility` ≥ ~0.6 for shoulder/elbow/wrist/hip; body fully in frame; plausibility checks
  (segment length ratios stable).
- MediaPipe landmark indices: 0 nose, 7/8 ears, **11/12 shoulders, 13/14 elbows, 15/16 wrists, 23/24 hips**. Use
  `worldLandmarks` (metres, hip-centred) for 3D angles.
- Camera guidance UI: distance, framing, lighting, start pose, movement direction.

### 9.5 AI coach
- **Rule-based core (must work first):** per-exercise state machine `IDLE → MOVING_UP → HOLD → RETURN → REST` with
  hysteresis thresholds; rep counted on full cycle; hold timer; peak angle per rep; cues (voice via
  `speechSynthesis`, haptic via COMMAND).
- **Exercise classifier (stretch goal):** follow Lee 2024 — windowed features (min/max/mean/var of accel+gyro per
  axis, per sensor; add angle features) → small MLP or random forest; train on team-recorded data; evaluate with
  **leave-one-subject-out**, not just a random split (Lee's limitation).
- **LLM/voice (optional):** only for symptom check-in phrasing and explanations; **must not** diagnose, prescribe,
  or change the plan; urgent symptoms (e.g., severe pain, numbness, chest pain) → fixed safety message + clinician
  contact.
- Pain slider 0–10 after each set; clinician-defined stop rules (e.g., pain ≥ threshold or sharp pain ⇒ stop
  and flag).

---

## 10. Exercises (content must be approved by a physiotherapist)

Each exercise definition (JSON) needs: purpose, start position, steps, reps/holds, common compensations,
precautions, stop conditions, when to seek help, measured metric, validity requirements (IMU/CV).

| Exercise | Measured | Feedback / compensation check |
|---|---|---|
| Pendulum (Codman) | circle size, trunk flexion angle, duration | count circles each direction |
| Wall climb / finger walk (flexion) | peak flexion, hold 15–30 s | buzz at personal best; shrug (EMG/CV) & trunk-lean warning |
| Towel stretch behind back (IR) | forearm IR angle | hold timer; CV invalid (occlusion) → IMU only |
| Stick-assisted ER (elbow 90° at side) | ER angle, elbow drift from side | target zone; warn if elbow lifts/abducts |
| Cross-body adduction | horizontal adduction | hold timer |
| Active-assisted abduction | abduction (true vs apparent) | trunk lateral lean detection |

Harvard Health guidance: stretch to tension, not pain. Typical dosing in sources varies (e.g., 10–20 reps/day,
holds 10–30 s) — the clinician sets actual dosing.

---

## 11. Team document summary (Physio_Buddy_..._Discussion_Document.docx, 11 Oct 2026)

Five core problems and the agreed direction:
1. **Positioning unclear** → one platform, two pathways; narrow first workflow; intended-purpose statement +
   permitted/excluded claims; decide first customer (clinic/physio/hospital/direct-to-patient).
2. **IMU unreliability** (drift, placement, straps, magnetic interference) → relative upper-arm vs torso orientation;
   standardized placement/calibration; log raw data, timestamps, missing samples, saturation, battery, calibration
   status; evaluate Madgwick/Mahony/Kalman on evidence; compare to reference (goniometer/mocap); report **MAE, RMSE,
   bias, repeatability, drift, latency, invalid-measurement rate per movement**; suppress values when quality is poor.
3. **CV blind spots** → camera guidance, landmark confidence/plausibility, "zero" ≠ "unavailable", explicit fusion
   states, depth/multi-camera only if justified.
4. **Exercise delivery undefined** → clinician-approved content first; track completion + symptoms; no auto-progression
   from ROM alone; voice optional for accessibility; usability testing with older adults.
5. **Architecture/manufacturing** → modules (wearable/firmware, measurement engine, patient app, clinician dashboard,
   backend, safety/escalation); design for cleaning, repair, charging, strap wear, calibration; avoid 24/7 monitoring.

Standards matrix (candidates — regulatory specialist must confirm): **Core:** ISO 14971:2019 (risk mgmt) + ISO/TR
24971, ISO 13485:2016 (QMS, for commercialization), IEC 62304 (software lifecycle), IEC 62366-1 (usability).
**Conditional:** ISO 10993-1:2025 (strap skin contact), IEC 60601-1 / -1-2 (EMC) / -1-11 (home healthcare),
IEC 81001-5-1 (health software cybersecurity). **India:** Medical Devices Rules 2017 (as amended), CDSCO Medical
Device Software guidance (listed 21 Jul 2026), BIS adoptions.

Example hazards (ISO 14971 style): IMU drift shows false improvement; CV loses arm → reports 0°; strap slips;
unsuitable exercise; voice intake misses urgent symptoms; battery fault; data attached to wrong patient — each with
controls + verification evidence.

Staged roadmap: 0 intended use → 1 proof of principle (sensor repeatability vs reference) → 2 integrated POC →
3 risk & verification design → 4 DFM → 5 clinical/regulatory readiness → 6 pilot.

Do/Don't: version firmware/algorithms/app/model/content per session; separate measurement engine from UI and clinical
rules; privacy-by-design (no raw video upload by default); test across body sizes/clothing/lighting/placements; don't
equate chip datasheet with joint-angle accuracy; don't let an LLM prescribe.

Also references an IIT Bombay "MDI-M2 Develop" lecture (product architecture, POC, form/fit/function prototyping,
usability engineering) as the team's process.

---

## 12. Validation plan (for the demo and beyond)

- **Bench:** IMU on a protractor jig/rotating table at known angles → static error, drift over 10 min hold, latency.
- **Human (team members, healthy):** each movement × 3 reps × N subjects; device vs **goniometer** (same trained
  tester); record MAE, RMSE, bias, Bland–Altman 95% LoA, ICC; within- and between-session repeatability
  (re-don straps).
- **Robustness:** strap re-placement ±2 cm, loose strap, different clothing, lighting/camera angles, occlusion test
  set (behind-back IR) → false-valid output rate must be ~0.
- **Fix acceptance criteria before testing** (team doc), e.g., provisional engineering band per movement — do not
  advertise as clinically sufficient.
- Keep test logs (CSV + session JSON with firmware/algorithm versions) in `docs/validation/`.
- **Demo:** goniometer reading next to device reading live; show "apparent vs true" angle during a deliberate trunk
  lean; show "measurement unavailable" when arm is hidden from camera.

---

## 13. Build plan (suggested order — confirm with the user)

1. **Order hardware** (verify links/prices; Robocraze for IMUs/XIAO, Robu for the rest).
2. **Firmware v0:** one XIAO + one BNO085 → Serial quaternions @100 Hz (verify I2C stability, address jumpers).
3. **Firmware v1:** 2 IMUs + BLE 17-byte packets + COMMAND (tare/haptic) + STATUS/battery.
4. **Web v0:** Web Bluetooth connect + parse + live numbers + simple Three.js box per sensor.
5. **Calibration + kinematics:** N-pose (+ functional) → elevation / plane / ER angles; verify vs goniometer.
6. **Avatar:** GLB humanoid retargeting + ghost target + colour zones.
7. **Coach:** rule-based rep/hold for 3–4 exercises + haptic/voice cues + pain slider.
8. **CV:** MediaPipe landmarks, visibility gating, shrug metric, fusion state machine.
9. **Chest unit** (Unit B) + trunk-lean compensation + apparent-vs-true display.
10. **Dashboard + PDF report**, IndexedDB history, adherence streak.
11. **Optional:** MyoWare EMG shrug detection; exercise classifier (Lee 2024 approach, LOSO evaluation).
12. **Pitch:** problem stats (§3), evidence (§3.3), live demo script (§12), risk/standards slide (§11), cost
    (≈ ₹5–6k/patient kit at scale vs lakhs for clinical mocap).

---

## 14. Known pitfalls

- BNO08x over I2C on ESP32 can hang/reset → wire RST/INT, lower clock, consider SPI; handle `wasReset()` and re-enable
  reports.
- 7Semi BNO086 default address 0x4B vs Adafruit 0x4A — check before putting two on one bus.
- Game rotation vector yaw is per-sensor arbitrary → always calibrate all sensors at the same instant.
- Quaternion order mismatch (w-first vs Three.js w-last) and left/right arm mirroring.
- Euler gimbal lock near 0° elevation for Y-X-Y — compute elevation from vectors, not Euler, for display.
- Web Bluetooth: needs user gesture per device, HTTPS/localhost, Chromium only; Windows sometimes needs device
  re-pairing — keep a reconnect button.
- JSON over BLE caused brownouts in a published ESP32 project → binary packets only.
- XIAO ESP32-S3 charges at ~100 mA (500 mAh ≈ 5 h) and has no battery-voltage pin → divider.
- Strap slip is the largest real-world error source; rigid mounts + re-calibration prompts.
- MediaPipe fails behind-the-back and with depth ambiguity; landmarks disappearing must never become 0°.
- Robu product URLs here were partly inferred from mirror domains — verify.

---

## 15. Open questions / decisions still needed (ask the user)

1. Hackathon date/deadline and judging criteria? Team size and who owns firmware / web / CV / pitch?
2. Has any hardware been bought? Does the senior already own BNO055s (use as fallback)?
3. Two BLE units vs one MCU with a cable to the chest IMU?
4. Include MyoWare EMG (₹7k incl. electrodes) or rely on CV for shrug detection?
5. Which shoulder (left/right) for the demo; which 3 movements are the validation target?
6. Web stack: vanilla JS vs React; any backend needed (clinician dashboard, cloud sync)?
7. Is a physiotherapist available to approve exercise content and escalation rules?
8. First customer framing for the pitch: clinic/physio-prescribed kit vs direct-to-patient.

---

## 16. References

1. Ajčević M. et al. IMU assessment in adhesive capsulitis (arXiv 2020) — https://arxiv.org/pdf/2010.16169
2. Chen Y-P. et al. Wearable IMU kit for adhesive capsulitis home exercise, JMIR 2020 — https://www.jmir.org/2020/7/e17032
3. Digital ROM devices vs goniometry, systematic review & meta-analysis (2024) — https://pmc.ncbi.nlm.nih.gov/articles/PMC10490745
4. Rigoni M. et al. Shoulder ROM with wireless IMU, Sensors 2019 — https://www2.mdpi.com/1424-8220/19/8/1781
5. Monocular 3D body tracking in MSK telerehab, Sensors 2024 — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10781343/
6. MediaPipe ROM reliability/validity, Measurement 2023 — https://hal-lirmm.ccsd.cnrs.fr/lirmm-04055464
7. IMU shoulder angle error sources, IEEE TNSRE 2023 — https://doaj.org/article/82f138124fa74988b05a47b9f48e5506
8. IMU sensor-to-segment calibration for humerothoracic angles — https://research.rug.nl/en/publications/effects-of-different-inertial-measurement-unit-sensor-to-segment-/
9. Adhesive capsulitis with diabetes, narrative review 2024 — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11477401/
10. Adhesive capsulitis & diabetes prevalence meta-analysis — https://clok.uclan.ac.uk/26358/1/26358%20Adhesive-capsulitis-of-the-shoulder-and-diabetes-a-meta-analysis-of-prevalence.pdf
11. Trapezius EMG imbalance in frozen shoulder — https://link.springer.com/article/10.1007/s10067-005-1105-x
12. Neck muscle compensation in frozen shoulder, Biomedicines 2024 — https://doaj.org/article/8cf33a9e41f1461cbfd83b3c6562dd3f
13. Physiotherapy adherence, smartwatch cohort — https://pubmed.ncbi.nlm.nih.gov/33704076/
14. **Lee K. et al. Deep learning classification of shoulder rehab exercises with IMU, JNER 2024;21:42** — https://pmc.ncbi.nlm.nih.gov/articles/PMC10967210/
15. Harvard Health — frozen shoulder exercises — https://www.health.harvard.edu/stretching-exercises-frozen-shoulder
16. SWORD Health RCT — https://swordhealth.com/resources/clinical-studies/comparing-digital-to-conventional-physical-therapy-for-chronic-shoulder-pain-randomized-controlled-trial
17. Adafruit BNO085 guide — https://learn.adafruit.com/adafruit-9-dof-orientation-imu-fusion-breakout-bno085
18. SparkFun BNO086 (accuracy figures) — https://www.sparkfun.com/sparkfun-vr-imu-breakout-bno086-qwiic.html
19. ESP32 Web BLE tutorial — https://randomnerdtutorials.com/esp32-web-ble-sensor-visualization/
20. XIAO ESP32-S3 getting started (Robocraze) — https://robocraze.com/blogs/post/xiao-esp32-s3-getting-started
21. ISO 14971:2019 — https://www.iso.org/standard/72704.html
22. IEC 62304 — https://committee.iso.org/standard/38421.html
23. IEC 62366-1 — https://webstore.iec.ch/en/publication/67220
24. CDSCO Medical Devices portal — https://www.cdsco.gov.in/opencms/opencms/en/Medical-Device-Diagnostics/Medical-Device-Diagnostics/

---

## 17. Glossary

- **ROM** range of motion · **ER/IR** external/internal rotation · **IMU** inertial measurement unit (accel + gyro
  [+ mag]) · **Game rotation vector** BNO08x fused orientation without magnetometer · **N-pose** standing, arms at
  sides · **Sensor-to-segment calibration** finding how a sensor is mounted relative to the bone · **Humerothoracic**
  humerus relative to thorax · **Capsular pattern** ER > abduction > IR loss · **MAE/RMSE** mean absolute / root
  mean square error · **LoA** Bland–Altman limits of agreement · **ICC** intraclass correlation · **LOSO**
  leave-one-subject-out validation · **EMG** electromyography (muscle electrical activity).

*Disclaimer: hackathon prototype guidance, not medical advice. Exercise limits for any patient must be set by a
qualified physiotherapist.*
