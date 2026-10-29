# Auri strap BLE protocol v1

Fixed contract between the strap firmware (`firmware/auri_strap/`) and the hub. The C header
(`../auri_strap/src/auri_ble.h`) and the Python decoder (`auri_ble.py`) implement exactly this page; change all three together and bump
`PROTOCOL_VERSION`. Based on `agenthandoff.md` §7, with the time-sync ping from `jetson_realsense_ai_design.md`.

All multi-byte fields are **little-endian**. Every packet fits the default 20-byte ATT payload (no MTU negotiation).

## Devices
| Unit | `unit_id` | BLE name | Sensors (`sensor_id`) |
|---|---|---|---|
| A, upper-arm pod | 1 | `AURI-ARM` | 0 upper arm (BNO085 0x4A), 1 forearm (BNO085 0x4B); DRV2605L haptics |
| B, trunk pod | 2 | `AURI-TRUNK` | 2 trunk (BNO085 0x4A) |

## GATT
Service `3c3ff578-acd0-46f5-a868-3ef18783e0b1`, plus the standard Battery Service `0x180F`.

| Characteristic | UUID | Props | Content |
|---|---|---|---|
| IMU_DATA | `55b3d211-8c74-4650-9156-6b55c5d4384a` | notify | 17-byte orientation packet per sensor sample |
| RAW_DATA | `eaa61235-25bd-4c94-acef-04fde856d914` | notify | 20-byte gyro + gravity packet per sensor sample |
| COMMAND | `98d96b03-6a94-49f4-8044-9659ea5c31bb` | write | opcode + arguments |
| STATUS | `25fc04e0-6984-40dd-a21c-f6d007e20fcd` | read, notify | status record, or a time-sync pong |

## IMU_DATA (17 bytes)
| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `unit_id << 4 \| sensor_id` |
| 1 | 1 | flags: bit0 valid, bit1 calib_ok, bits2-3 BNO accuracy (0-3), bit4 reset_occurred (sticky until the next packet of that sensor) |
| 2 | 2 | `seq` uint16 per sensor, wraps; gaps = dropped samples |
| 4 | 4 | `t_ms` uint32, device `millis()` when the report was read |
| 8 | 8 | `qw, qx, qy, qz` int16, Q14 (value / 16384), BNO **game rotation vector** (no magnetometer; yaw is per-sensor arbitrary) |
| 16 | 1 | reserved (EMG was dropped), always 0 |

`valid = 0` means the sensor was silent for more than 200 ms or failed: the quaternion is the last good one and must
not be used. The firmware never fabricates samples.

`sensor_id = 15` is a **link test** (firmware built with `AURI_TEST_PATTERN=1` and no IMU present): always `valid = 0`,
identity quaternion. Receivers must ignore it except for link statistics.

## RAW_DATA (20 bytes), same `seq`/`t_ms` as the matching IMU_DATA packet
| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `unit_id << 4 \| sensor_id` |
| 1 | 1 | flags: bit0 gyro valid, bit1 gravity valid |
| 2 | 2 | `seq` |
| 4 | 4 | `t_ms` |
| 8 | 6 | gyro x, y, z int16, rad/s Q10 (value / 1024, range ±32 rad/s), BNO calibrated gyroscope, sensor frame |
| 14 | 6 | gravity x, y, z int16, m/s² Q8 (value / 256), BNO gravity report, sensor frame |

## COMMAND (write)
| Opcode | Arguments | Effect |
|---|---|---|
| 0x01 | none | tare: re-initialise the IMUs (re-enable reports) |
| 0x02 | `pattern` uint8 | haptic: 1 target reached, 2 hold complete, 3 warning/compensation, 4 stop |
| 0x03 | `hz` uint8 | stream rate, 10-100 Hz (clamped); default 50 |
| 0x04 | `on` uint8 | 1 start streaming, 0 stop |
| 0x05 | `mask` uint8 | hard-reset the IMUs in the bit mask (bit = sensor_id) |
| 0x06 | `host_us` uint64 | time ping: the device answers on STATUS with a pong |

## STATUS
Status record (16 bytes), notified every 2 s and on change:
| Offset | Size | Field |
|---|---|---|
| 0 | 1 | type = 0x01 |
| 1 | 1 | `PROTOCOL_VERSION` (1) |
| 2 | 3 | firmware major, minor, patch |
| 5 | 1 | unit_id |
| 6 | 1 | IMUs present (bit = sensor_id) |
| 7 | 1 | IMUs streaming OK (bit = sensor_id) |
| 8 | 2 | battery mV uint16 (0 = no divider fitted: unavailable, not empty) |
| 10 | 2 | I2C error count uint16 (saturates) |
| 12 | 1 | streaming on/off |
| 13 | 1 | rate Hz |
| 14 | 1 | haptics present |
| 15 | 1 | reserved |

Time pong (13 bytes): type = 0x06, `host_us` uint64 echoed, `t_ms` uint32 at reception. The hub tracks
`offset = host_rx_time - t_ms` (lower envelope) and uses the pong round trip to bound it.
