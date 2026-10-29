# Auri strap firmware

The XIAO on each pod reads BNO085 game-rotation quaternions (no magnetometer) and sends them over BLE. The packet layout is `protocol/PROTOCOL.md`. Degrees are not computed here.

`auri_strap/` builds for the Seeed XIAO ESP32-C3 and ESP32-S3. `AURI_UNIT=1` is the arm pod (`AURI-ARM`: sensors 0x4A and 0x4B, haptics). `AURI_UNIT=2` is the trunk pod (`AURI-TRUNK`: one sensor at 0x4A). Flags live in `auri_strap/board.h`:

| Flag | Default | Meaning |
|---|---|---|
| `AURI_UNIT` | 1 | 1 arm, 2 trunk |
| `AURI_HAS_BATTERY_DIVIDER` | 0 | 1 only when the 100k/100k divider is on D1. Otherwise battery is unavailable |
| `AURI_BNO_RST_WIRED` | 0 | 1 when BNO RST is wired to D3 |
| `AURI_TEST_PATTERN` | 0 | 1: if no IMU answers, send `valid=0` packets on sensor 15 so the BLE link can be tested |

Pins are chosen by chip in `board.h` (C3 and S3 use different GPIO numbers for the same XIAO labels). The C3 on this bench is COM7 when it enumerates as USB VID 303A.

From the repo root, with arduino-cli. The C3 option `CDCOnBoot=default` is the menu item **Enabled**.

Arm pod, C3, link-test build (what is flashed on the bare board). `upload` does not take `--build-property`, so the compile output directory is passed in:

```
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default --build-property "compiler.cpp.extra_flags=-DAURI_UNIT=1 -DAURI_TEST_PATTERN=1" --build-path %TEMP%\auri-strap-c3-arm-test firmware/auri_strap
arduino-cli upload -p COM7 --fqbn esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default --input-dir %TEMP%\auri-strap-c3-arm-test
```

Arm pod, S3 (compile only until an S3 is plugged in):

```
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 --build-property "compiler.cpp.extra_flags=-DAURI_UNIT=1" firmware/auri_strap
```

Trunk pod, C3:

```
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default --build-property "compiler.cpp.extra_flags=-DAURI_UNIT=2" firmware/auri_strap
```

Host check, after `python -m venv firmware/.venv` and `pip install bleak` in that venv:

```
firmware/.venv/Scripts/python.exe firmware/tools/ble_probe.py 20
```
