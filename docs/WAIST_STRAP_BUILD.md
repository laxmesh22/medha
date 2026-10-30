# Build the waist strap (new XIAO ESP32 + BNO085), step by step

Goal: a new board that streams the trunk sensor as `AURI-TRUNK` (unit 2). Same wiring as the arm straps.
The firmware already knows the pins: **SDA = D4, SCL = D5** on both the XIAO ESP32-C3 and the ESP32-S3
(the GPIO numbers differ between the two chips, the printed labels do not, so wire by the printed label).

## 0. Parts
- XIAO ESP32-C3 (recommended, same as boards 1 and 2) or XIAO ESP32-S3, with pin headers or bare pads.
- Adafruit BNO085 breakout (4754) with its header, or the same sensor on any board with the pins named below.
- 4 wires, 28-30 AWG, **5-8 cm** long: red, black, and two other colours (e.g. blue = SDA, yellow = SCL).
- Later: 3.7 V LiPo with JST, slide switch, strap pod. Not needed for this test (USB powers it).
- Tools: soldering iron (~330 C), thin solder, flux, multimeter (continuity), tweezers, magnifier.

## 1. Pin diagram (wire exactly this)

```
 BNO085 breakout (Adafruit 4754)               XIAO ESP32-C3 / S3  (USB-C at the top)
 -------------------------------               ---------------------------------------
 VIN  ---------- red ------------------------> 3V3        (right column, 3rd from the top)
 GND  ---------- black ----------------------> GND        (right column, 2nd from the top)
 SDA  ---------- blue ----------------------->  D4         (left column, 5th from the top)
 SCL  ---------- yellow --------------------->  D5         (left column, 6th from the top)
 INT, RST, DI, P0, P1, 3Vo  --------------------> NOT connected (leave open)

 Left column, top to bottom:  D0  D1  D2  D3  D4  D5  D6
 Right column, top to bottom: 5V  GND 3V3 D10 D9  D8  D7
```
Check the silkscreen on YOUR board before soldering: the printed labels are what count, not the order above.

| BNO085 pin | XIAO pad | Notes |
|---|---|---|
| VIN | 3V3 | 3.3 V, not 5V. |
| GND | GND | any GND pad. |
| SDA | **D4** | C3: GPIO6, S3: GPIO5 |
| SCL | **D5** | C3: GPIO7, S3: GPIO6 |
| DI | open | address 0x4A. (DI to 3V3 would make it 0x4B: the forearm slot only, never on the waist.) |
| INT / RST / P0 / P1 | open | not used. |

**Never use D6 for I2C on the C3.** It is the USB/UART TX pin; the sensor then answers only sometimes
(this cost us a day on the first board).

## 2. Solder, in this order
1. **Look first.** Put the two boards side by side, the BNO085 flat, the XIAO with USB-C pointing away from you.
2. **Tin** the pads or header pins you will use: a thin bright film of solder, 1-2 s with flux. Do not blob.
3. **Cut and strip** the 4 wires to 5-8 cm, strip 2 mm, tin the ends.
4. **GND first** (black), then **3V3/VIN** (red), then SDA (blue), then SCL (yellow). 2-3 s per joint, solder
   flows into a small shiny cone. A dull, ball-shaped or cracked joint is cold: reheat with fresh solder.
5. **Do not bridge neighbouring pads.** D4 and D5 are next to each other; look under the magnifier and
   check with the multimeter (step 3).
6. Keep wires short and routed together; strain-relieve with a drop of hot glue or Kapton tape once tested.
7. Clean flux with isopropyl alcohol and a brush; let it dry.

## 3. Check with the multimeter BEFORE plugging in USB (power off)
| Test | Expected |
|---|---|
| BNO VIN to XIAO 3V3 | beep (continuity) |
| BNO GND to XIAO GND | beep |
| BNO SDA to XIAO D4 | beep |
| BNO SCL to XIAO D5 | beep |
| 3V3 to GND | **no** beep (no short) |
| SDA to SCL | **no** beep |
| SDA to 3V3, SCL to 3V3 | no beep (a reading of tens of kOhm is the pull-up, fine) |
| D4 to D5 on the XIAO | no beep |

## 4. First power-up
1. Plug the XIAO in by USB-C. The red/orange power LED lights, nothing smokes or gets hot (finger test on
   the BNO chip and regulator: warm at most).
2. Windows shows a new `USB Serial Device (COMxx)`. If it shows nothing: new cable (many are charge-only),
   or hold **BOOT**, plug in, release after a second.
3. **Do not open the COM port in a serial monitor.** On these boards opening it resets the board.
   Tell Claude "waist board connected on COMxx" and Cursor reads its chip id and flashes it (below).

## 5. What we do next (Claude + Cursor, nothing for you to type)
1. Identify the chip (C3 or S3) and MAC, read-only.
2. Flash `auri_strap` with `-DAURI_UNIT=2` (name `AURI-TRUNK`, sensor 0x4A, trunk slot), board-correct pins.
3. Check over Bluetooth: ~50 Hz, 0 gaps, 100% valid, |q| = 1.000, gravity = 9.8 m/s2, I2C errors 0.
4. Map it to the **waist** slot in the station, then calibrate with the other two straps.

## 6. If it does not stream
| Symptom | Likely cause | Fix |
|---|---|---|
| Boot log: BNO absent / I2C errors climb | SDA or SCL cold joint, or swapped | reflow SDA and SCL, swap check |
| Works for a few seconds then fails | wires too long or loose joint | shorten, reflow |
| Nothing at all, board warm | short between 3V3 and GND | multimeter test again |
| Sensor found on a different address | DI pin touched 3V3 | clean DI, leave it open |
| Found only on other pins | wired to the wrong pads | compare with the table; Cursor's pin scan finds the real pins |

## 7. Wear it
Waist strap, **lid facing out, arrow pointing up**, snug against the body, board rigid on the belt (a
loose pod rocks and ruins the angle). Then the calibration steps in `docs/AGENT_HANDOFF_DEVICE_CV.md` §11.C.
