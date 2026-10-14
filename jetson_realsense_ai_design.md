# Physio Buddy — Jetson + RealSense + AI Design Addendum

> Companion to `agenthandoff.md` (read that first). Written **14 Oct 2026**.
> This file covers the change from "laptop webcam + MediaPipe in the browser" to a
> **portable NVIDIA Jetson + Intel RealSense depth camera** hub that runs a **neural network trained on the
> strap + camera sensor data**, plus a **retrieval-grounded (RAG) exercise-guidance assistant**.
> Everything in the handoff's §0 "core design rules" still applies. Where this file and the handoff
> disagree on architecture, this file is newer; on clinical/product rules, the handoff and team doc win.

---

## 0. Summary

**What changes**
1. A **portable edge hub** (Jetson Orin Nano Super + RealSense D435i/D455 on a tripod, battery powered)
   replaces the laptop as the brain. It receives both BLE straps, runs the depth camera and the neural nets,
   and serves the UI over local Wi-Fi to **any browser**: laptop, tablet, or phone (iOS included, which also
   removes the Web Bluetooth limitation).
2. **Depth gives real 3D keypoints in metres.** That fixes the main weakness of MediaPipe (depth ambiguity, which
   gave 15–25 % ROM error in the cited studies). Shoulder rotation and shrug become measurable by camera.
3. **One multimodal neural network** ("PB-MotionNet") takes IMU and depth-skeleton streams together. It
   recognises the exercise, segments rep phases, detects compensation, and rejects unknown movements.
4. **Exercise suggestion** is done by a clinician-gated rules + ranking engine. **RAG** grounds the
   explanations and answers in approved content and in the patient's own session history.

**Four corrections to the idea as stated** (each one matters, see §1):
- RAG is **not trained** on sensor data. The neural net is trained. RAG retrieves.
- The neural net **must not produce the ROM number.** The angle stays deterministic geometry.
- "Suggest exercise" must **select within the physio's plan**. It must not prescribe or progress on its own
  (handoff rule 5).
- **The budget breaks.** Jetson + RealSense alone cost about ₹75–85k against a ₹30k cap (§3).

### Decisions locked (14 Oct 2026)
| Question | Decision |
|---|---|
| Hub hardware | **Owned:** Jetson Orin Nano (dev kit, 8 GB) + **RealSense D455f**. Budget conflict in §3.3 resolved |
| Showcase | **31 Oct 2026, IIT Bombay.** That leaves 17 days. Plan in §17 |
| Product framing | **Clinic Station** (hub + camera + strap at the physio). The home strap kit is roadmap only |
| AI placement | **Hybrid edge + cloud** (§16). Everything real-time on the Jetson; cloud for LLM, sync, clinician dashboard, training. Works fully offline |

**D455f notes:** it is a D455 (95 mm baseline, global-shutter RGB, IMU) with a factory **750 nm NIR-pass filter on the
depth imagers**. Depth then relies on the IR projector, so **keep the emitter ON** (indoor). The filter suppresses
visible-light reflections and repetitive-pattern errors (tiled floors/ceilings are common at venues), which helps here.
The RGB lens keeps its IR-cut filter, so colour is normal for pose estimation.

**Jetson:** check `cat /etc/nv_tegra_release`. If it is not on JetPack 6.2.x, upgrade. 6.2 enables **Super mode** on the
original Orin Nano dev kit (25 W / MAXN SUPER, ~50 % more memory bandwidth). From JetPack 5.x a QSPI firmware update is
needed first (NVIDIA Initial Setup Guide).

---

## 1. Reality check (read before building)

### 1.1 "RAG trained on sensor data": what that should actually mean
RAG (retrieval-augmented generation) means that at question time you **search** a knowledge store and give the
results to a language model so its answer stays grounded. Nothing in RAG is trained on your data.
The plan needs two separate components:

| Component | Learns from | Job |
|---|---|---|
| **PB-MotionNet** (CNN/TCN neural net) | Recorded IMU + depth-skeleton sessions (labelled) | Which exercise, which phase, compensation yes/no, "not an exercise" |
| **Guidance engine + RAG** | Nothing learned. It **retrieves** from approved exercise cards, education sheets, guideline summaries, and the patient's own session summaries | Pick today's focus **from the approved plan**, explain why in plain language, answer questions with citations |

The sensor data reaches the RAG side only as **session summaries** (e.g., "ER peak 32° vs target 45°,
shrug in 4/10 reps, pain 3→4"). Those summaries are documents the assistant can retrieve and cite.

### 1.2 The angle must stay deterministic
ROM numbers come from calibrated quaternion geometry (handoff §8) and the depth-skeleton geometry (§6 here).
They are verifiable against a goniometer, explainable, and versionable. A neural net that "predicts the angle"
cannot be verified the same way, and it fails silently on patients unlike its training set.
**Neural nets classify and flag. Geometry measures.** This also keeps the IEC 62304 / ISO 14971 story clean.

### 1.3 Exercise suggestion vs. "no auto-progression"
Handoff rule 5: progression is clinician-defined. So the system may:
- choose **which approved exercises to emphasise today** and in what order,
- **regress** to a gentler approved variant when stop rules fire (pain, compensation),
- **propose** a progression to the physio, who approves it in the dashboard.

It may **never** add exercises outside the plan, change dosing numbers, or progress difficulty from ROM trend
alone. See §9.

### 1.4 Accuracy has to be measured, not assumed
"Accurate tracking" is a claim that needs numbers. The dominant error sources for shoulder IMU angles, in order:

| Source | Typical size | Mitigation in this design |
|---|---|---|
| Sensor-to-segment misalignment (mounting/calibration) | 5–10°+ | Functional calibration (handoff §8.2) + **camera-assisted axis check** (§7.2) |
| Soft-tissue artefact on upper arm (skin slides over humerus, worst for axial rotation) | Underestimates humeral rotation a lot | Measure ER/IR from the **forearm** with elbow at 90° (already planned). Depth camera gives an independent ER estimate |
| Strap slip during session | Grows over time | **Slip detector** = persistent IMU-vs-camera offset (§7.3) |
| Game-RV yaw drift | 0.5°/min | Re-zero every ~10 min or when the camera confirms rest pose (§7.2) |
| Sensor fusion noise | 1.5–2.5° | Already the smallest term |
| Time misalignment IMU vs camera | ω × Δt, e.g. 90°/s × 33 ms ≈ 3° | Clock sync (§5) |

Set provisional acceptance bands **before** testing (team doc), e.g. flexion/abduction MAE ≤ 5°, ER ≤ 8° vs
goniometer, false-valid output rate ≈ 0. Report them as engineering targets, not clinical validity.

---

## 2. Revised architecture

```
 Unit A (upper arm + forearm IMUs, haptic)      Unit B (sternum IMU)
        │ BLE notify 17-byte packets                │ BLE notify
        ▼                                           ▼
┌──────────────────────── PORTABLE HUB: Jetson Orin Nano Super (JetPack 6.2.x, headless) ───────────────────────┐
│                                                                                                               │
│  [P1 capture]  ble_ingest (bleak/BlueZ) ─┐                                                                    │
│                realsense (pyrealsense2)  ├─► time-sync + resample → common 50 Hz timeline                     │
│                pose2d (RTMPose/YOLO-pose, TensorRT FP16) → depth lift → 3D keypoints (m)                      │
│                                                                                                               │
│  [P2 core]     calib → kinematics (IMU angles) ─┐                                                             │
│                skeleton kinematics (cam angles) ├─► fusion state machine (explicit states, quality flags)     │
│                PB-MotionNet (TensorRT)  ────────┘     → coach (reps/holds/cues) → haptic COMMAND back to P1   │
│                                                                                                               │
│  [P3 app]      FastAPI: WebSocket 30 Hz live state · REST sessions/plan/reports · SQLite + Parquet raw logs  │
│  [P4 guide]    guidance rules + RAG (sqlite-vec/BM25) + LLM (local small model or cloud) — runs between sets │
└───────────────────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                                │ local Wi-Fi (hub as hotspot) — no video leaves the hub
                                                ▼
            Any browser: Three.js avatar · live angles + quality · coach UI · dashboard · PDF report
            (patient tablet/phone, physio laptop; iOS works because BLE is no longer in the browser)
```

**Key architectural decision:** the hub is **one Python codebase that runs on the Jetson *or* on a laptop**
(x86, RealSense works there too, pose via ONNX Runtime). The browser is **UI only**. That gives:
- one measurement engine (no JS/Python duplication),
- a **fallback demo** if the Jetson misbehaves on stage (run the hub on the laptop),
- the Jetson as the "portable product" form factor.

Web Bluetooth in the browser is dropped from the main path. Keep it only if the team wants a no-hub "Lite" mode later.

**Skip ROS 2 for the hackathon.** It adds build and debugging overhead with no benefit at this scale. Use plain
Python processes with shared-memory ring buffers or ZeroMQ.

---

## 3. Hardware additions & budget

### 3.1 New parts
| Item | Notes | Price seen (verify) |
|---|---|---|
| **Jetson Orin Nano Super Developer Kit (8 GB)** | 67 TOPS in 25 W "MAXN SUPER" mode; Wi-Fi + BT card on the dev kit | ~₹30,000 at ThinkRobotics (sale); other Indian sellers list up to ₹55,000 |
| NVMe SSD 256 GB (M.2 2280) | microSD is too slow for TensorRT engines and logs | ~₹2,000 |
| **RealSense D455** (preferred) or **D435i** | See 3.2 | D455 ~₹55,000, D435i ~₹44,000 (Indian listing, price-to-product mapping unconfirmed) |
| USB 3 cable (short, good quality) | RealSense needs USB 3 for depth + colour at 30 fps | ~₹500 |
| 100 W USB-C PD power bank (≥ 20,000 mAh) + 20 V PD-trigger → DC barrel cable | Dev kit ships with a 19 V barrel adapter. **Check the carrier's accepted DC input range in the NVIDIA user guide before using a trigger cable.** ~20–28 W total load → ~2.5–3 h | ~₹5,000 + ₹500 |
| Tripod (to ~1.5 m) + 3D-printed bracket holding Jetson + camera | Single portable unit | ~₹1,500 |
| Optional USB BT 5 dongle | If the on-board combo card drops BLE packets when Wi-Fi hotspot is active (known coexistence issue) | ~₹800 |

### 3.2 D455 vs D435i
Patient stands **~2.0–2.5 m** away so the whole torso and an overhead arm fit in frame (58° vertical depth FOV → ~2.2 m
of height at 2 m).
- **D455:** 95 mm stereo baseline, rated < 2 % depth error at 4 m → better at 2–2.5 m. **Pick this if buying.**
- **D435i:** 50 mm baseline, rated < 2 % at 2 m (~4 cm at 2 m). OK if you can borrow one. Its built-in IMU is not needed.
- D405 is short-range (< 0.5 m) and will not work for this use.
- RealSense spun out of Intel as RealSense Inc. (July 2025). librealsense remains open source. On JetPack 6, use the
  **RSUSB backend build** (JetsonHacks "RealSense in 5 minutes" route) and expect some setup friction.

### 3.3 Budget: RESOLVED (Jetson + D455f owned). Kept for the pitch's cost slide
Still to buy for the station: NVMe SSD (if not fitted), 100 W PD power bank + trigger cable, tripod + bracket,
**pocket 4G router** (§16.4). **Drop the MyoWare** (depth camera covers shrug) and the webcam. This keeps the strap kit
near the minimum-kit cost.

Original analysis:
Current full kit ≈ ₹27,229 + hub additions ≈ ₹85–95k ⇒ **≈ ₹1.1–1.2 lakh vs ₹30k cap.**

Options, in recommended order:
1. **Borrow the Jetson and RealSense** (college lab, senior, department). Most realistic. Ask first.
2. If buying: get Jetson + D435i and **drop** the MyoWare EMG (−₹7k; depth camera now covers shrug), the spare
   BNO085 + spare XIAO (−₹2.8k), and the webcam (−₹1.3k).
3. Cheaper depth cameras (Luxonis OAK-D Lite, Orbbec Gemini/Astra series) are worth a price check. OAK-D Lite also
   runs small NNs on-camera. All the depth-lifting code below is camera-agnostic except the SDK calls.
4. Last resort: Jetson + normal webcam. This keeps the portable hub but loses the depth advantages in §6–7.

**Pitch framing that fits the cost:** a **Clinic Station** (hub + camera + strap, owned by the physio, used for
assessment and to calibrate and validate the strap) and a **Home Kit** (strap + phone app). The clinic sessions
produce the reference data that make home IMU-only readings trustworthy. This also answers handoff open
question 8 (first customer = clinic/physio).

---

## 4. Jetson software stack & runtime

| Layer | Choice | Why |
|---|---|---|
| OS | JetPack **6.2.x** (Ubuntu 22.04, L4T 36.4+), **headless**, Super mode `nvpmodel` MAXN SUPER | Frees ~1 GB RAM vs desktop |
| Containers | `dusty-nv/jetson-containers` (PyTorch, TensorRT, ONNX Runtime, llama.cpp images) | Avoids wheel hell on aarch64 |
| Camera | librealsense 2.5x (RSUSB backend, CUDA on) + `pyrealsense2` | CUDA accelerates align/colour conversion |
| 2D pose | **RTMPose-m** (Apache-2.0) via `rtmlib` → ONNX → TensorRT FP16. Quick-start alternative: **YOLO11n/s-pose** (Ultralytics, **AGPL-3.0**, needs a licence for a commercial product) | Both give COCO-17 keypoints incl. ears/shoulders/elbows/wrists/hips at 30 fps with headroom |
| Not MediaPipe | No supported GPU path on Jetson aarch64 | Keep MediaPipe only for a laptop "Lite" mode |
| BLE | `bleak` on BlueZ | Async, handles two peripherals and notifications |
| App/API | FastAPI + uvicorn, WebSockets | Simple, typed |
| Storage | SQLite (sessions, plans, metrics, versions) + Parquet (raw 50/100 Hz streams, keypoints) | Lightweight, portable, inspectable |
| ML runtime | PyTorch for training (laptop/Colab) → ONNX → TensorRT (`trtexec`) on Jetson | |

### 4.1 Latency budget (camera path)
Exposure + USB ~33 ms → pose 8–15 ms → depth lift + kinematics 2–3 ms → MotionNet < 1 ms → WebSocket to browser 5–20 ms
⇒ **~60–80 ms glass-to-screen**. The IMU path is ~25–40 ms. Haptic cues are driven from the IMU path, which is faster.

### 4.2 Memory budget (8 GB shared CPU/GPU)
OS headless ~1.2 GB · RealSense + pose engine ~1.0–1.5 GB · MotionNet + app ~0.5 GB · **local 3B LLM (Q4) ~2.5 GB**.
It fits, but **do not run LLM generation during active capture.** Run it between sets or after the session.

---

## 5. Time synchronisation (the piece teams usually forget)

Three independent clocks: Unit A `millis`, Unit B `millis`, RealSense hardware clock.
- **RealSense:** enable `global_time_enabled` → frame timestamps are already mapped to the host clock.
- **Each BLE unit:** for every packet, `offset_i = host_rx_time − t_ms`. Track the **lower envelope** (minimum
  over a sliding 5 s window ≈ minimum transport latency) and fit a line over 60 s to capture crystal drift.
  Device time → host time = `t_ms + offset(t)`.
- **Firmware addition (small):** `COMMAND 0x06 time_ping <host_us>` → device echoes `<host_us, t_ms>` on STATUS
  for round-trip estimation. Add this to the firmware spec in handoff §7.
- **Resample** everything onto one **50 Hz timeline**: slerp for quaternions, linear for keypoints and gyro.
  Mark samples as gaps (never interpolate across gaps longer than 60 ms).
- **Verify with a "sync swing"** at session start: one quick arm swing. Cross-correlate IMU humerus angular speed
  with camera wrist speed and log the residual lag. Pass if < 20 ms.

---

## 6. RealSense depth pipeline

### 6.1 Placement & capture
- Tripod at ~1.1–1.3 m height (chest level), **2.0–2.5 m** from the patient, **rotated ~30° toward the affected
  side** (frontal-oblique). This sees abduction (frontal plane) and flexion (sagittal) without full self-occlusion.
- Streams: depth **848×480 @ 30** (the D4xx optimal depth resolution), colour 848×480 @ 30, `rs.align` depth→colour.
- Visual preset **High Accuracy**, emitter on, auto-exposure ROI on the body. Post-filters: spatial + temporal
  (disparity domain), hole-filling **off** (filled holes become fake depth). Indoor only; strong sunlight degrades IR stereo.
- On-screen guidance from the camera itself: distance OK (from torso depth), whole body in frame, lighting, start pose.

### 6.2 2D → 3D lifting
For each keypoint with confidence ≥ 0.5:
1. Take a patch around the pixel (5×5 at 2 m, scale with 1/depth). Take the **median of valid depths**. If fewer than 50 %
   of the patch pixels are valid, mark the 3D point **invalid**. Never use 0.
2. Deproject with the colour intrinsics (`rs2_deproject_pixel_to_point`) → metres in camera frame.
3. **Surface → joint-centre bias:** depth hits skin/clothing in front of the joint. Segment *directions* are mostly
   unaffected because both ends shift similarly. Optional fixed offsets along the camera ray (shoulder ~4 cm, elbow ~3 cm,
   wrist ~2 cm) should be tuned against goniometer data, not assumed.
4. **Plausibility gates:** per-session median upper-arm and forearm length; frames with > 15 % deviation are flagged
   implausible. Check left/right swap and keypoint jumps > physiological speed.
5. Smoothing: One-Euro filter for **display only**. Raw values go to the log and metrics.

### 6.3 Camera kinematics (same maths as the IMU, so they're directly comparable)
- **Thorax frame from the skeleton:** Y = shoulder-mid − hip-mid (up); Z = R-shoulder − L-shoulder, orthogonalised (lateral);
  X = Y × Z (anterior).
- Humerus vector `elbow − shoulder` in thorax frame → **elevation** and **plane of elevation** with the same formulas as handoff §8.3.
- **ER/IR from the camera:** with elbow at 90°, the forearm vector `wrist − elbow` in the transverse plane. This is exactly the
  case where 2D pose fails (the forearm points at the camera). **Depth solves it.** That is a strong demo point.
- **Shrug / scapular elevation:** 3D distance ear→shoulder and shoulder height above the shoulder-hip line, normalised by
  shoulder width, compared with a per-session baseline. With depth this replaces the EMG for the hackathon.
- **Trunk lean:** thorax Y vs gravity. RealSense has no gravity reference except the D435i IMU, so take gravity from the
  **sternum IMU** or a one-time "camera level" calibration.

---

## 7. Fusion upgrades with depth

The explicit fusion-state table (handoff §9.4) **stays unchanged**. Depth adds three capabilities that are cross-checks,
never averaging:

### 7.1 Consistency check gets meaningful
With 3D camera angles, "IMU and CV agree within tolerance" becomes a real test. Fix the tolerance per movement from
validation data (e.g., start at 8° for elevation and 12° for ER) and record the disagreement rate per session.

### 7.2 Camera-assisted calibration and re-zero
- During the N-pose and the functional flexion, the camera independently measures humerus and forearm axes in the thorax
  frame. If the IMU-derived mounting axis disagrees with the camera axis by > ~10°, **reject the calibration and repeat**
  (catches a strap put on rotated).
- When the camera sees a confident rest pose (arm at side, still for 2 s), offer a **one-tap re-zero** of yaw drift.
  It is explicit and logged, never silent.

### 7.3 Strap-slip detector
Track `d(t) = angle_IMU − angle_CAM` during valid-valid periods. A **CUSUM** on `d` that shows a persistent step
(rather than noise) means the strap moved → "Strap may have shifted — please recalibrate", and IMU-only values are
marked low-quality until recalibrated. This directly controls the team doc hazard "strap slips".

### 7.4 Apparent vs true ROM: now three ways
Arm vs world (single IMU) · arm vs thorax (IMU pair) · arm vs thorax (camera). Show all three during a deliberate trunk
lean in the demo.

---

## 8. PB-MotionNet: the neural network

### 8.1 What it does (and doesn't)
| Head | Output | Used for |
|---|---|---|
| Exercise | One of N approved exercises **+ "rest" + "unknown/other"** | Auto-detect what the patient is doing; **reject non-exercise motion** (scratching head, adjusting strap) so reps aren't faked |
| Phase (per timestep) | none / up / hold / down / rest | Cross-checks the rule-based rep state machine. Reps count only when both agree |
| Compensation (multi-label) | shrug · trunk lateral lean · back arch · trunk rotation · elbow drift (ER) · too fast/jerky | Cues + session summary |

It never outputs an angle, a pain estimate, or a diagnosis. Where pure geometry suffices (e.g., trunk lean > X° from
the sternum IMU), a **rule** is used instead. The net covers the patterns rules handle badly: shrug combinations,
guarded/jerky movement, and exercise identity.

### 8.2 Inputs (common 50 Hz timeline, body-frame features)
The big improvement over Lee 2024 is the choice of features. Lee fed raw wrist-sensor-frame accel/gyro, which depend
on how the sensor is mounted and confuse banded extension with ER. Here **all features are in anatomical frames after
calibration**, so they don't depend on strap mounting or which way the patient faces, and humeral axial rotation is
an explicit input:

- **IMU branch (~31 dims/step):** q_TH and q_HF as 6D rotation representation (12) · thorax tilt sagittal/frontal (2) ·
  humerus, forearm, thorax angular velocity in thorax frame (9) · arm linear accel, gravity removed (3) · clinical
  angles: elevation, plane, axial rotation, ER, trunk lean (5) · [EMG envelope (1) if fitted].
- **Skeleton branch (36 dims/step):** 9 joints (nose, ears, shoulders, elbows, wrists, hips; drop hips if not visible)
  × xyz in the **skeleton thorax frame**, normalised by shoulder width (27) + per-joint valid mask (9).
- **Modality mask:** which streams are valid at each step (mirrors the fusion states).

### 8.3 Architecture (small, causal, streaming)
```
IMU (T×31) ──► causal TCN: 4 residual blocks, 64 ch, k=5, dilation 1-2-4-8 ──┐
                                                                            ├─► gated fusion (uses modality mask)
Skeleton (T×36) ─► causal TCN (same) or 3-layer light ST-GCN ───────────────┘          │
                                                                ┌───────────────────────┼──────────────────────┐
                                                        phase head (per step)   attention-pool → exercise   compensation
                                                                                  head (+unknown)          head (sigmoid ×6)
```
- **Causal** convolutions → runs online with no look-ahead (receptive field ~2 s).
- **Modality dropout** in training (drop camera 30 %, forearm IMU 10 %, chest IMU 10 %) → the net degrades
  gracefully in the "IMU valid / CV invalid" states instead of failing.
- ~150–250 k parameters → < 1 ms in TensorRT FP16. It could even run on the laptop CPU.
- **Open-set rejection:** energy score / max-softmax threshold tuned on the "unknown" recordings. Below threshold →
  "unknown", no reps counted.

### 8.4 Training data protocol (the real work)
- **Subjects:** ≥ 12 (team, friends, family; written consent). Two sessions on different days for at least half, with the
  straps **re-donned** to capture placement variance.
- **Per exercise:** 2 sets × 8 correct reps, plus 1 set × 5 reps for **each scripted compensation** ("shrug as you lift",
  "lean away"), plus 2 min of **unknown activity** per subject (reach for phone, adjust strap, scratch head, wave). That
  last part is what stops false rep counts.
- **Simulated restriction:** healthy people don't have frozen shoulders. Have them stop at ~60–100° and also use the
  augmentation below. Flag the **domain gap** honestly. Real patient data comes later through a physio with consent
  and ethics approval.
- **Labels:** exercise class comes from the app's guided script (automatic). Phases are auto-labelled from the angle
  state machine, then corrected in a **replay tool** (avatar + skeleton + timeline scrubber; build this, it pays for itself).
  Compensation labels come from the scripted condition and are spot-checked with geometry.
- **Volume:** ~12 subjects × ~6 exercises × ~45 reps ≈ 3,000+ reps (~5–6 h). Enough for this model size with augmentation.

### 8.5 Augmentation (what makes it robust)
- **Mounting perturbation:** rotate the raw sensor quaternions by random ±10–15° *before* calibration and feature
  computation. This simulates strap misplacement and is the most important augmentation.
- **ROM scaling:** slerp each trajectory toward rest by a factor 0.5–1.0 to synthesise restricted-ROM movement from healthy data.
- Time-warp 0.8–1.2×, gyro bias drift, sensor noise, left↔right mirroring (for either affected side),
  keypoint jitter/dropout/occlusion masks (e.g., hide the wrist as in behind-back IR).
- Optional pretraining (post-hackathon): virtual IMUs synthesised from AMASS mocap, skeleton branch on NTU RGB+D 120.
  Both are **research/non-commercial licences**, so check before any product use.

### 8.6 Evaluation (what to show the judges)
- **Leave-one-subject-out** (fixes Lee 2024's 80:20 random-split limitation). Report: exercise macro-F1, confusion
  matrix (especially extension vs ER), unknown-rejection rate, **rep-count error per set**, phase boundary error (ms),
  compensation sensitivity at 95 % specificity, latency on Jetson.
- **Ablation table:** IMU-only vs camera-only vs fused. This is the clearest slide for *why* the project needs both
  sensors.
- Version every model (hash) into each session record (team doc requirement).

### 8.7 Personalisation (V1 = thresholds only)
Per-patient baselines (resting shrug height, rest-pose angles, typical rep speed) adapt the *thresholds*, not the
weights. No per-patient fine-tuning in V1. It is hard to verify and easy to overfit.

---

## 9. Exercise suggestion engine + RAG

### 9.1 Three layers, in this order
```
1. SAFETY RULES (deterministic, run first)      red-flag symptoms → fixed safety message + "contact clinician"; stop rules
         │                                       (pain ≥ plan threshold, sharp pain, pain +2 vs pre-session) → stop & flag
         ▼
2. PLAN FILTER (clinician-owned)                 candidate set = exercises in the active, versioned care plan
         │                                       + their approved regressions/variants. Nothing else can pass.
         ▼
3. RANK + REASON CODES (transparent rules)       order today's session; attach machine-readable reasons
         │
         ▼
4. RAG + LLM (language only)                     turn reason codes + retrieved snippets into plain-language,
                                                 cited explanation (EN/HI/regional). Output validated.
```

### 9.2 Ranking rules (examples; the physio can edit the parameters)
- **Focus the most-limited movement relative to its target.** In the capsular pattern that is usually ER, then
  abduction. `priority = (target − recent_peak) / target`, weighted by the plan.
- **High compensation rate** on exercise E (> 30 % of reps) → put E's approved easier variant first (e.g., table slide
  before wall climb) and add a setup re-check cue.
- **Pain rose ≥ 2 points last session** → approved gentler variants only, fewer sets **within the plan's range**, flag to physio.
- **Plateau:** peak ROM change < 3° over 14 days with adherence ≥ 70 % and stable pain → **"propose progression" to the
  physio** (dashboard queue). No change for the patient until approved. A new plan version is created on approval.
- **Low adherence** → shortest approved routine + reminder. Never more load.
- **Tissue irritability** (from the physio's intake: high/moderate/low, as used in the adhesive-capsulitis clinical
  practice guideline) sets which intensity tier of the plan is eligible. **The physio sets it, not the AI.**

Output example (what the UI and the LLM receive):
```json
{
  "plan_version": "p-0007",
  "session": [
    {"exercise_id": "er_stick_90", "sets": 2, "reps": 10, "hold_s": 15,
     "reasons": ["MOST_LIMITED:ER:peak32/target45", "COMP_RATE_OK"]},
    {"exercise_id": "table_slide_flex", "sets": 2, "reps": 10, "hold_s": 20,
     "reasons": ["REGRESSED_FROM:wall_climb", "COMP_SHRUG:4/10"]}
  ],
  "clinician_flags": ["PAIN_UP_2:2026-10-13"],
  "proposals": []
}
```
All numbers come from the plan. None are invented by the LLM.

### 9.3 The RAG part
**Corpus (all versioned, all approved):**
1. Exercise cards: the handoff §10 JSON (purpose, steps, compensations, precautions, stop conditions, when to seek help).
2. Patient education sheets (what frozen shoulder is, stages, night pain, why "stretch to tension, not pain").
3. Guideline summaries written/approved by the physio (e.g., irritability-based dosing principles).
4. **The patient's own session summaries:** daily templated text generated from metrics, with metadata
   (patient_id, date, exercise_id, metric). This is where the sensor data enters RAG.

**Retrieval:** filter by metadata first (this patient, date window, exercise IDs in the plan), then hybrid BM25 + a small
embedding model (`bge-small-en-v1.5`, or `multilingual-e5-small` for Hindi/regional languages) in **SQLite + sqlite-vec**.
The corpus is small (tens of cards plus daily summaries), so a vector database server is unnecessary.

**Generation guardrails:**
- The LLM gets: structured state + reason codes + top-k snippets. It must return JSON `{message, cited_ids[]}`.
- A **validator** rejects output that mentions any exercise ID not in the plan, contains numbers not present in the inputs,
  uses banned terms (diagnosis, medication, "cure", "clinically validated"), or lacks citations. On rejection it falls back to
  a **template message**. The app must work fully with the LLM switched off.
- Free-text patient questions are answered **only from the approved corpus**, with a citation. Otherwise: "Please ask your physiotherapist."

**LLM placement:** local small instruct model (3B class, 4-bit, via llama.cpp on the Jetson, between sets/after the
session) for offline privacy, **or** a cloud API with **de-identified** inputs only. Decide per pitch narrative. Local is
a strong privacy story; cloud gives better language quality.

---

## 10. Touch-free control (good accessibility win, optional)
A frozen-shoulder patient can't easily tap a screen mid-exercise. Add:
- **Hand gestures** with the *unaffected* hand (open palm = pause, thumbs-up = next). Use a whole-body pose model with hand
  keypoints (e.g., RTMW) or a hand-landmark model on a crop around the wrist.
- **Voice** commands ("pause", "next", "stop") via a small on-device speech model, plus `speechSynthesis` cues in the browser.

---

## 11. Privacy & safety additions (add to the ISO 14971-style hazard list)
| Hazard | Control | Verification |
|---|---|---|
| Video of patient at home leaks | Video processed in RAM on the hub. Only keypoints/metrics stored. Raw video recording is opt-in for debugging, with consent. No cloud upload | Code review + network capture shows no video traffic |
| NN counts non-exercise motion as reps → inflated adherence | "Unknown" class + rule/NN agreement required | LOSO unknown-rejection rate |
| LLM states something unsafe/off-plan | Deterministic safety layer first, plan filter, output validator, template fallback | Red-team prompt set, 0 violations |
| Strap slip → false improvement | Slip detector (§7.3), recalibration prompts | Deliberate slip test |
| Hub battery/thermal | Certified PD power bank, fan unobstructed, hub not worn | Thermal log over 60 min |
| Tripod/cable trip, IR emitter | Short cables, stable tripod. RealSense emitter is Class 1 (eye-safe), state it | Setup checklist |
| Wrong patient profile | Patient selection + confirmation at session start, session ID on every record | Usability test |

---

## 12. Validation additions (on top of handoff §12)
- **IMU vs camera vs goniometer** for each movement → three-way Bland–Altman. The camera is *not* the reference; the goniometer is.
- **Depth-only robustness:** distance 1.5 / 2.0 / 2.5 / 3.0 m, clothing (loose kurta vs T-shirt), lighting, camera angle 0/30/60°.
- **Sync test:** sync-swing lag distribution over 20 sessions.
- **Slip test:** rotate the strap 10–15° mid-session → time-to-detection.
- **MotionNet:** §8.6 metrics under LOSO + on-device latency.
- **Guidance engine:** scenario tests (pain spike, plateau, low adherence, red flag) → expected outputs, 100 % pass.

---

## 13. Revised build plan (MoSCoW; map to the deadline once known)

**Must (demo spine)**
1. Firmware v1 per handoff §7, plus `COMMAND 0x06` time ping.
2. Hub on the **laptop first**: bleak ingest → calibration → IMU angles → FastAPI WebSocket → browser Three.js avatar.
3. RealSense + 2D pose + depth lift + camera angles on the laptop.
4. Time sync + explicit fusion states + "measurement unavailable".
5. Rule-based coach for 3 movements (flexion, abduction, ER) + haptic + pain slider.
6. Port the hub to the **Jetson** (containers, TensorRT pose engine), battery power, hotspot UI.

**Should**
7. Data-collection mode + replay/labelling tool → record ≥ 12 subjects.
8. PB-MotionNet v1 (exercise + unknown + phase), LOSO results, ablation table.
9. Guidance engine layers 1–3 + clinician plan JSON + "propose progression" queue.
10. Slip detector + camera-assisted calibration check.

**Could**
11. RAG + LLM explanations (with validator and template fallback), multilingual.
12. Compensation head, gesture/voice control, PDF report with three-way validation plots.

**Won't (this hackathon)**
Per-patient NN fine-tuning, autonomous progression, cloud video, ROS 2, multi-camera rigs.

Reason for laptop-first: the Jetson adds setup risk (librealsense on JetPack 6, TensorRT builds). Getting the pipeline
right on x86 and then porting avoids debugging two things at once.

---

## 14. Open questions (add to handoff §15)
1. Can you **borrow** a Jetson and RealSense (which models?) or must you buy them? This decides the budget.
2. Hackathon **deadline**? It decides how much of "Should/Could" is real.
3. Is the Jetson meant to be the **home** device or the **clinic** station? (Recommendation: clinic station + home strap.)
4. LLM: **local** (privacy story) or **cloud** (quality)? Or a template-only demo?
5. Can a physiotherapist provide the care-plan structure, stop rules, and irritability tiers, and approve the exercise cards?
6. Consent form for recording team/friends' data (even for a hackathon, do it; judges notice).
7. Languages for patient messages (English + which?).

---

## 15. Repository layout (create at `D:\medha`, `git init`)
```
medha/
  firmware/pb_unit/            # PlatformIO, UNIT_ARM / UNIT_CHEST build flags
  hub/physiobuddy_hub/         # runs on Jetson AND laptop (same code)
    capture/  realsense.py  pose.py (TensorRT | ONNX Runtime)  lift.py
    ble/      ingest.py (bleak)  protocol.py (17-byte packet)
    core/     sync.py  calib.py  kinematics.py  skeleton_kin.py  fusion.py  coach.py  slip.py
    ml/       motionnet_infer.py
    guide/    rules.py  rag.py  llm_router.py  validator.py  templates/
    api/      server.py (FastAPI: WS live state, REST)  static/ ← built web UI
    store/    db.py (SQLite)  outbox.py (cloud sync queue)  rawlog.py (Parquet)
    replay/   player.py        # feeds recorded sessions through the full pipeline (demo fail-safe + labelling)
  web/                         # Vite + Three.js UI (patient tablet + station screen)
  cloud/                       # FastAPI + Postgres: sync API, clinician dashboard, LLM proxy
  ml/                          # MotionNet training, LOSO eval, ONNX export
  content/                     # exercises/*.json, education/*.md, plans/*.json (physio-approved, versioned)
  docs/                        # handoff, this file, validation logs, pitch
```

---

## 16. Hybrid edge + cloud design

### 16.1 Split of responsibilities
| Runs on **Jetson (edge)**: must work offline | Runs in **cloud**: optional, adds value when online |
|---|---|
| BLE ingest, RealSense, pose, depth lift, sync, calibration, kinematics | **LLM** for rich explanations, multilingual patient messages, clinician session summaries |
| Fusion states, coach, haptics, MotionNet inference | **Clinician dashboard** (web): review sessions and trends, edit plans, approve progression proposals |
| Guidance layers 1–3 (safety, plan filter, ranking) | **Sync store:** de-identified session summaries + metrics (Postgres) |
| Local RAG index + **local LLM** fallback + templates | **Training pipeline:** consented datasets → MotionNet training → versioned ONNX in object storage |
| SQLite source of truth for the station; outbox queue | Model + content registry (edge pulls new versions) |

**Rule:** the cloud never sits in the measurement or safety path. Losing the internet only changes the language quality
of explanations and delays sync.

### 16.2 LLM router (one interface, four backends): decided 14 Oct, **Claude + DeepSeek**
```
request (state + reason codes + retrieved snippets, de-identified)
   ├─ online → Railway LLM proxy
   │     ├─ 1st: Claude   (claude-haiku-5-5 patient messages, claude-sonnet-5-5 clinician summaries)
   │     └─ 2nd: DeepSeek (OpenAI-compatible API) when Claude errors/times out, or by per-route config
   ├─ offline / proxy down → Local LLM on Jetson (llama.cpp, 1.5B–3B instruct, 4-bit; between sets / after session)
   └─ else / any validator failure → Template message
          ▼
   SAME validator for all backends (plan IDs only, no new numbers, banned terms, citations required)
```
- **Why both:** provider redundancy for the live demo, plus a cost/quality comparison table for the pitch (same prompts,
  same validator, pass rate + latency per provider).
- **DeepSeek data caveat:** DeepSeek's API is operated from China. Send it only the same **de-identified** payload as Claude
  (it already contains no name, video or raw keypoints). For a real product, cross-border transfer under India's DPDP Act
  needs review, so make the provider a per-route config flag. Good DeepSeek-only routes: drafting translations of
  education content for physio review, and the fallback path.
- Model IDs: Claude IDs as above. Check DeepSeek's current model names in their API docs when wiring the proxy.
- Cloud timeout of 4 s, then fall back to local. The UI labels the source (`cloud` / `on-device` / `template`). Judges like seeing that.
- **What leaves the device:** pseudonymous patient ID, metrics, reason codes, retrieved approved snippets. **No name, no
  video, no images, no raw keypoints.** The name ↔ ID mapping stays in the Jetson's SQLite.
- The API key lives only in the cloud **LLM proxy** (part of `cloud/`). The Jetson authenticates to the proxy with a
  per-station token and never holds the provider key. Rate-limit at the proxy.

### 16.3 Sync (outbox pattern)
- Every finished session writes a summary row + an **outbox** entry in SQLite within one transaction. A background task
  POSTs to `cloud/` with retries and idempotency keys (session UUID). Offline at the venue → it syncs later and loses nothing.
- Plan changes made in the clinician dashboard are versioned in the cloud and **pulled** by the station at session start
  (and on a "sync" button). Conflict rule: the cloud plan version wins, and every session records which plan version it used.
- Raw IMU/keypoint data for training uploads **only** for subjects with a training-consent flag, as a separate manual job.

### 16.4 Network at the venue (plan for bad Wi-Fi)
- Bring a **pocket 4G router**. Jetson, tablet and laptop all join it. The UI is reached at `http://physiobuddy.local:8000`
  (mDNS). If the router dies, the Jetson can still run its own hotspot (offline mode).
- Don't rely on IIT Bombay venue Wi-Fi (captive portals, client isolation).
- Use the cloud dashboard on a phone over mobile data. This works independently of the station network.

### 16.5 Cloud hosting: **Railway** (decided 14 Oct)
One Railway project, `physiobuddy`: **one FastAPI service** (`cloud/`: sync API + clinician dashboard + LLM proxy) +
**one Railway Postgres**, in an Asia region. Secrets as Railway variables: `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`,
`STATION_TOKENS`, `DATABASE_URL` (injected). Never commit keys. The Jetson only holds its station token. For the pitch, mention India's DPDP Act 2023 (consent, purpose limitation,
data-residency questions) as a known future requirement.

### 16.6 Models across edge/cloud
MotionNet is trained in the cloud/Colab → exported to **ONNX** → the station downloads it → **builds the TensorRT engine
on the Jetson itself** (engines are device- and TensorRT-version-specific). Never ship a `.engine` built elsewhere.
Every session logs `{firmware, hub, pose_model, motionnet, plan, content}` versions.

---

## 17. Showcase plan: 31 Oct 2026, IIT Bombay (Clinic Station)

### 17.1 Critical path & risk
- **Highest risk = strap hardware arrival.** Order the minimum strap kit **today** (express). If it is late, Lamington Road
  (Mumbai) shops may have ESP32-S3/XIAO boards and straps the same day. BNO085s are rarer, so order those first.
- **Mitigation:** the camera pipeline is built first, because you already have the hardware. A **camera-only clinic
  station is a complete demo on its own**. The straps add accuracy, rotation-behind-back, haptics and the
  IMU-vs-camera story.
- **Replay mode** (recorded sessions through the full pipeline) is the on-stage fail-safe and the labelling tool. Build it early.

### 17.2 Day-by-day: **team of 3** (updated 14 Oct)
**A = Hardware & firmware** (straps, firmware, BLE, calibration, validation rig) ·
**B = Vision, Jetson & ML** (camera pipeline on Jetson, depth metrics, data collection, MotionNet) ·
**C = App, cloud & AI** (UI/avatar/coach, Railway, LLM router with Claude + DeepSeek, guidance, pitch).
Claude Code supports all three.

| Date | A | B | C |
|---|---|---|---|
| **Tue 14** ✅ | — | — | Repo + camera pipeline v0 + UI + sim mode **done** |
| Wed 15 | **Strap parts ordered** (by 15 Oct). Firmware v0 on any ESP32 + IMU at hand | JetPack 6.2 + librealsense + D455f on Jetson (`docs/setup_jetson.md`) | Run `--sim`; plan exercise cards (3 movements) + consent form |
| Thu 16 – Fri 17 | Firmware v1 (2 IMUs, BLE 17-byte packets, COMMAND/STATUS, time ping) as parts arrive | Live camera pipeline on laptop → tune thresholds with real people; `--record` 3 reference sessions | Coach UI v0 (reps/hold/target zone/pain slider) on camera angles |
| Sat 18 – Sun 19 | BLE ingest in hub (bleak) + IMU kinematics + N-pose calibration | Pipeline on Jetson with CUDA, ≥ 25 fps; TensorRT EP | Avatar (GLB) driven by skeleton; session summary + SQLite store |
| Mon 20 – Tue 21 | Chest unit, haptics, time sync + sync swing | Fusion states IMU+camera, apparent-vs-true 3-way, slip detector | **Railway:** cloud service + Postgres + sync outbox + clinician dashboard v0 |
| Wed 22 – Thu 23 | Strap mechanics; IMU reset/recovery | **Data collection** (≥ 8–12 people, guided script) + labelling in replay | Guidance rules + plan JSON + proposal queue |
| Fri 24 – Sat 25 | Goniometer validation rig + protocol | **MotionNet v1** train (LOSO), ONNX → Jetson | **LLM proxy: Claude → DeepSeek → local → template** + validator + RAG |
| Sun 26 – Mon 27 | Validation runs (Bland–Altman) | Integration, thermals, power bank | PDF report, multilingual messages, pitch deck draft |
| **Tue 28** | **CODE FREEZE.** Only bug fixes after this | | |
| Wed 29 – Thu 30 | Rehearsals ×5, failure drills (kill internet, unplug camera, power-cycle strap, flat battery), backup video, one-pager | | |
| **Fri 31** | **Showcase.** Arrive early, test the venue light and floor (tiles!), set up the router before judging | | |

**Cut order if behind:** compensation head → local LLM (keep Claude/DeepSeek + templates) → camera-assisted calibration →
MotionNet phase head → chest strap unit (camera trunk lean covers it).

### 17.3 Live demo script (~6 min)
1. **Check-in** on the tablet: pick pseudonymous patient, pain 0–10, red-flag questions.
2. **Strap on + N-pose:** the camera confirms the pose and the calibration passes its quality gate (try a rotated strap once → rejected).
3. **Flexion** with a goniometer held next to the arm: screen shows IMU, camera and the goniometer reading.
4. **Trunk lean** → "apparent 150° vs true 128°" (three-way).
5. **Shrug** → compensation cue + haptic buzz.
6. **ER at 90° elbow:** depth gets it right where 2D pose fails. Then **behind-back IR:** camera shows "unavailable", the IMU continues, never 0°.
7. **Random movement** (scratch head) → MotionNet "unknown", no rep counted. Then a real rep → auto-recognised.
8. **End of session** → "today's focus" with reasons → Claude explanation in **Marathi/Hindi** → **pull the router plug** →
   the same flow continues with the on-device LLM, labelled "on-device".
9. **Clinician view on a phone (cloud):** approve the proposed progression → the station pulls plan v+1.
10. Close with the validation slide (MAE/Bland–Altman, LOSO ablation) and the safety/standards slide.

### 17.4 Showcase fail-safes
Replay mode with 3 good recorded sessions · laptop can run the hub · spare strap unit + charged LiPos · wall adapter +
power bank · offline mode · pre-recorded demo video · printed one-pager.

---

## Sources checked for this addendum (14 Oct 2026)
- Jetson Orin Nano pricing India: https://thinkrobotics.com/blogs/product-reviews-buying-guides/jetson-orin-nano-price-complete-buying-guide-for-ai-robotics-development ,
  https://varietyinfotech.com/product/nvidia-jetson-orin-nano-super-developer-kit/
- RealSense pricing India (mapping unconfirmed): https://thinkrobotics.com/collections/lidars-online
- librealsense on Jetson: https://docs.ros.org/en/jazzy/p/librealsense2/doc/installation_jetson.html ,
  https://jetsonhacks.com/2025/03/20/jetson-orin-realsense-in-5-minutes/ ,
  https://forums.developer.nvidia.com/t/realsense-d435i-not-working-with-jetson-orin-nano-8gb-jetpack-6-0/298870
- RealSense spin-out from Intel: https://www.edge-ai-vision.com/2025/07/realsense-completes-spinout-from-intel-raises-50-million-to-accelerate-ai-powered-vision-for-robotics-and-biometrics/

*Hackathon prototype guidance, not medical advice. Exercise content, dosing, stop rules and progression must be set by a
qualified physiotherapist.*

---

## 18. Research lock — evening of 14 Oct 2026

Checked against NVIDIA JetPack notes, RealSense D455f docs and JetPack 6 issues, RTMPose/rtmlib, Ultralytics licensing,
the 2025 RGB-D shoulder ROM review, Lee 2024, Sassi 2024, Gauci 2023, and current Claude API model IDs. The architecture
in §0–§16 stands. These points **narrow what ships on 31 Oct**.

### 18.1 What “the OpenCV model” actually is
OpenCV is the image toolkit (colour conversion, skeleton overlay, patch maths). It is not the pose model.
`cv2.dnn` / rtmlib’s `backend='opencv'` is a CPU fallback and is too slow for the live path.
**Live pose: RTMPose-s (COCO-17) through [rtmlib](https://github.com/Tau-J/rtmlib), ONNX Runtime on the laptop,
TensorRT FP16 on the Jetson once export is proven.** RTMPose-m only if -s misses the shoulder at 2 m.
Apache-2.0. YOLO11-pose is a 48-hour emergency fallback only (AGPL-3.0; a later closed product would need an
Ultralytics enterprise licence). Do not run RTMW 133-keypoint whole-body, RTMW3D, MediaPipe, or `trt_pose` in the
live loop. Metric depth is the 3D signal; an RGB-to-3D network would fight the D455f.

### 18.2 Camera bring-up (do this before any model work)
- D455f USB ID `8086:0b5c`. Depth dies on USB 2. Confirm `lsusb -t` shows 5000M on the Jetson port.
- JetPack 6 removed `hiddraw`, so IMU-equipped RealSense cameras often fail until librealsense is **built from source
  with the RSUSB/libuvc backend**. `pip install pyrealsense2` does not work on Jetson. SDK **2.55.1+**. Firmware
  **5.16.0.1** (D455f support starts at 5.15.0.2; **never flash 5.13.0.50**).
- Emitter **on**. Streams 848×480 @ 30. High Accuracy. Hole-filling **off**. Official 19 V barrel until the pipeline
  is stable; the power bank is a later test.
- Super mode (`sudo nvpmodel -m 2`) needs the `jetson-orin-nano-devkit-super.conf` flash and is for LLM headroom.
  If the board already runs pose at 30 fps, **do not reflash this week**.

### 18.3 Accuracy gates (stricter than §6)
- Default patient distance **2.0 m**, oblique ~30°, tripod 1.15–1.25 m. 2.5 m is the far limit: stereo error grows
  with distance squared. Factory D455 figure is <2% at 4 m (~8 cm). Scaled to 2 m that is on the order of 2 cm on a
  flat target, about 4° on a 30 cm humerus; clothing and edges can roughly double it. Camera-only flexion/abduction
  engineering target for the booth is **MAE ≤ 8°**, not 5°. The 5° target stays with the **IMU as the number**.
- Before a label is shown: flexion only if the plane is within ±30° of anterior; abduction within ±30° of lateral;
  **ER only if elbow flexion is 70–110° and arm elevation < 30°**. Otherwise “protocol not met”, never a wrong degree.
- Behind-back IR: camera **unavailable**, IMU continues, never 0°.
- Frontiers 2025 (14 RGB-D studies): flexion and abduction are the movements with evidence; rotation is inconsistent.
  Gauci 2023 (RGB-D + CNN, 30 healthy volunteers): mean bias under 10° vs goniometer. Say that on the slide.
- Unaffected-hand “gesture control” at 2 m is not reliable (the hand is too small). Pause = the **unaffected wrist**
  from COCO-17 rising above the shoulder, or the physio’s tablet. No second hand network.
- Verify COCO left/right with a one-arm wave before retargeting the avatar. Person-left is not image-left.

### 18.4 What the neural net is, for this deadline
Sassi 2024 (3 IMUs on thorax, upper arm, forearm; 19 healthy + 17 rotator-cuff; nested CV) reached **89.9% with a
random forest**, close to Lee’s 92.5% DNN and with a harder split. So the Oct 31 classifier, if any data exists, is a
**random forest or a tiny causal TCN on anatomical features**, evaluated leave-one-subject-out, labelled as an
engineering prototype. The full PB-MotionNet in §8 remains the architecture. It is **not on the critical path**.

Until that model exists, “unknown” is a **geometry envelope**: if plane or speed leaves the scripted exercise for
more than about 1 s, do not count the rep. Reps still require the rule-based state machine.

### 18.5 RAG and the two LLMs
Unchanged rule: RAG retrieves, it is not trained. Sensor data enters only as session-summary documents.
For the booth, SQLite FTS5 is enough. Skip the embedding model unless keyword retrieval fails.

| Path | Model | When |
|---|---|---|
| Cloud | `claude-haiku-5-5` (API id confirmed 7 Oct 2026) | Patient explanation and clinician blurb. Sonnet 5.5 only if Haiku wording is weak |
| Offline live demo | Pre-written EN + HI + MR templates for the scripted scenes | This is the “pull the router plug” moment |
| On-device | Qwen2.5-1.5B-Instruct Q4 (~1 GB, ~15 tok/s on Orin-class) | After the set, model unloaded before the next capture |

Do not keep a 3B model resident during RealSense + pose. A measured Qwen2.5-3B Q4 run on Orin Nano Super was ~24 tok/s
headless, but it competes with the camera for the same 8 GB. Marathi quality of a 1.5B model is weak; do not promise it.

### 18.6 Cloud cut
One small FastAPI service and SQLite are enough for 31 Oct (Postgres can wait). One clinician screen: session, pain,
ROM peaks, one Approve button that bumps the plan version. QR code of `http://<ip>:8000` as well as mDNS. Pocket 4G
router. No IIT Bombay venue Wi-Fi. No video, images, or raw keypoints leave the Jetson.

### 18.7 Critical path from the evening of 14 Oct
1. Tonight: D455f in `realsense-viewer` on the Jetson (USB 3, emitter on, 848×480). Laptop fallback if the build fails.
2. 15–16 Oct: RTMPose-s + depth lift + camera angles on the laptop, then the same code on the Jetson.
3. Order the minimum strap kit now. Camera-only is a complete clinic-station demo if the IMUs are late.
4. Code freeze 28 Oct still holds. Cut order if late: compensation head, local LLM, camera-assisted calibration,
   MotionNet. Never cut fusion states, “measurement unavailable”, or the safety/plan filter.
