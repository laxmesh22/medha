# Physio Buddy hardware: wearable pods

Parametric CAD in `cad/physio_pod.py` (CadQuery / OpenCascade). One run builds every part, checks that the electronics
fit, and exports:

| Folder | Format | Use |
|---|---|---|
| `cad/out/stl/` | STL | 3D printing |
| `cad/out/step/` | STEP (parts + coloured assemblies) | open in SolidWorks, Fusion 360, FreeCAD, Onshape |
| `cad/out/solidworks/` | SLDPRT | native SolidWorks 2026 parts (`tools/cad/solidworks_convert.py`) |
| `cad/out/glb/` | GLB | Blender / three.js (units are millimetre numbers: scale 0.001 for metres) |
| `renders/` | PNG + MP4 | product renders and the on-body video |

## The system
- **Upper-arm unit (Unit A):** `pod_arm_body` + `pod_arm_deck` + `pod_arm_lid` (PB-ARM) on `base_upperarm`.
  Bottom layer: BNO085 #1, XIAO ESP32-S3 on rails with the coin motor underneath, slide switch, USB-C port.
  Deck: 500 mAh LiPo (752530) + DRV2605L. Pod 60.7 x 30.6 x 22.2 mm (25.2 mm with the rail).
- **Forearm unit:** `pod_forearm_body` + `pod_forearm_lid` (PB-FORE) on `base_forearm`. BNO085 #2 only, Qwiic cable to
  the arm pod. Pod 36.6 x 28.4 x 12.4 mm.
- **Trunk unit (Unit B):** arm pod body + deck with `pod_waist_lid` (PB-WAIST) on `base_waist` (40 mm belt), or
  `pod_chest_lid` + `base_chest` for a chest band. No haptic driver or motor.

**Waist vs chest:** the shoulder angle is the arm relative to the **thorax**. A waist pod measures the **pelvis**: it
misses a patient leaning sideways from the lower back. The station's camera still measures trunk lean, so the waist
belt is fine with the camera; for strap-only measurement prefer the chest band (`--trunk sternum` in the video script).

**PB-rail:** every pod has the same dovetail tongue and fits every base. Slide the pod in from the open end until the
latch clicks. Press the tab under the open end to release. The base stays on the strap, so the pod returns to the same
place and orientation every session, and comes off for charging (never charge while worn).

**Orientation:** the lid arrow and the base arrow point the same way. Upper arm: arrow toward the shoulder (cable exit
toward the elbow). Forearm: arrow toward the wrist. Trunk: arrow up.

## Printing
- PETG preferred (tougher latch, sweat), PLA works. 0.2 mm layers, 3 walls, 25 % gyroid.
- Pod bodies: open side up, no supports. Lids: label side up. Deck: flat.
- Bases: curved underside down **with supports from the build plate only** (or print upside down on the flat top).
  The latch beam must not be supported underneath its slots.
- Material: about 80 g of filament for a full set (three pods, three lids, deck, three bases).
- After printing, glue a 1 mm neoprene or silicone strip under each base (stops the base sliding on skin).

## Assembly
1. BNO085: foam tape on the four corner pads; the side ribs hold it. The sensor must not move inside the pod.
2. XIAO: slide onto the rails until the USB-C port sits in the wall opening. Coin motor goes in the floor pocket
   under it (adhesive back). Battery leads to the BAT pads through the slide switch.
3. Qwiic cable to the forearm pod through the grommet in the -X wall.
4. Deck in, LiPo + DRV2605L on top (foam tape), lid clicks in (snap ridges).
5. 25 mm velcro through the base slots; the forearm uses the same strap width; the waist uses a 40 mm belt.

## Regenerate
```bash
tools/cad/.venv/Scripts/python.exe hardware/cad/physio_pod.py
```
```bash
tools/cad/.venv/Scripts/python.exe tools/cad/solidworks_convert.py hardware/cad/out/step hardware/cad/out/solidworks
```
```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup -P tools/blender/render_units.py -- hardware/cad/out/glb hardware/renders 32
```
The video: `tools/blender/device_on_avatar.py` with modes `still`, `test`, `product`, `shots`, `edit` (see its docstring).
First-time setup of the CAD environment: `uv venv --python 3.12 tools/cad/.venv` then `uv pip install cadquery pywin32`.

## Make the fit exact
Component bays come from seller dimensions with 0.3 mm clearance (the BNO085 bay fits both the 7Semi and Adafruit
boards). Either edit `COMPONENTS` in `physio_pod.py` with caliper measurements, or put manufacturer STEP files in
`cad/vendor/` (names in `cad/vendor/README.md`). The build then checks the real models for collisions and warns if a
board is bigger than its bay.
