# Vendor STEP models

Put manufacturer STEP files here with these exact names (`.step` or `.stp`). `physio_pod.py` picks them up
automatically, lays Y-up models flat, uses them in the collision check and the assembly renders, and warns if a part is
bigger than its bay. The files are git-ignored (third-party licences); fetch them again with the commands below.

| File name | Part | Source | Status |
|---|---|---|---|
| `bno085.step` | BNO085 breakout | Adafruit 4754 (Adafruit_CAD_Parts) | in use, 25.4 x 22.9 x 4.5 mm |
| `xiao_esp32s3.step` | Seeed XIAO ESP32-S3 | GrabCAD "seeed-studio-xiao-esp32s3" (`XIAO-ESP32S3 v2.step`) | in use, 22.5 x 17.8 x 4.5 mm |
| `drv2605l.step` | DRV2605L haptic driver | Adafruit 2305 (Adafruit_CAD_Parts) | in use, 17.8 x 16.5 x 2.7 mm |
| `ss12d00.step` | SS-12D00 slide switch | supplied by the team | not imported (lever and pins pass through the wall slot); body 8.5 x 3.5 mm matches the bay |
| `lipo_752530.step` | 500 mAh LiPo 752530 | none found | measure the bought cell with calipers, edit `COMPONENTS["lipo"]` |
| `coin_motor_10mm.step` | 10 mm ERM coin motor | none needed | a 10 x 2.7 mm disc |

```bash
curl -L -o hardware/cad/vendor/bno085.step "https://raw.githubusercontent.com/adafruit/Adafruit_CAD_Parts/main/4754%20BNO085%20STEMMA%20QT/4754%20BNO085%20STEMMA%20QT.step"
```
```bash
curl -L -o hardware/cad/vendor/drv2605l.step "https://raw.githubusercontent.com/adafruit/Adafruit_CAD_Parts/main/2305%20DRV2605L/2305%20DRV2605L.step"
```

The Adafruit model is the Adafruit board. If you use the 7Semi BNO085, measure it: the bay is 27 x 23 mm.
