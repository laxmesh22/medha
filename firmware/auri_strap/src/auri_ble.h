// Auri strap BLE protocol v1: UUIDs, opcodes and packet packing. The contract is firmware/protocol/PROTOCOL.md (this file lives in the sketch so Arduino can build it);
// the hub-side decoder is firmware/protocol/auri_ble.py. Change all three together.
#pragma once
#include <stdint.h>
#include <string.h>

namespace auri {

constexpr uint8_t PROTOCOL_VERSION = 2;  // v2: combined 37-byte IMU_DATA when the MTU allows, notify drops in STATUS

constexpr const char* SERVICE_UUID = "3c3ff578-acd0-46f5-a868-3ef18783e0b1";
constexpr const char* IMU_DATA_UUID = "55b3d211-8c74-4650-9156-6b55c5d4384a";
constexpr const char* RAW_DATA_UUID = "eaa61235-25bd-4c94-acef-04fde856d914";
constexpr const char* COMMAND_UUID = "98d96b03-6a94-49f4-8044-9659ea5c31bb";
constexpr const char* STATUS_UUID = "25fc04e0-6984-40dd-a21c-f6d007e20fcd";

enum Unit : uint8_t { UNIT_ARM = 1, UNIT_TRUNK = 2 };
enum Sensor : uint8_t { SENSOR_UPPER_ARM = 0, SENSOR_FOREARM = 1, SENSOR_TRUNK = 2 };

enum Opcode : uint8_t {
  CMD_TARE = 0x01,
  CMD_HAPTIC = 0x02,
  CMD_RATE = 0x03,
  CMD_STREAM = 0x04,
  CMD_IMU_RESET = 0x05,
  CMD_TIME_PING = 0x06,
};

enum Haptic : uint8_t { HAPTIC_TARGET = 1, HAPTIC_HOLD_DONE = 2, HAPTIC_WARNING = 3, HAPTIC_STOP = 4 };

constexpr uint8_t STATUS_RECORD = 0x01;
constexpr uint8_t STATUS_PONG = 0x06;

constexpr size_t IMU_PACKET_LEN = 17;
constexpr size_t RAW_PACKET_LEN = 20;
constexpr size_t STATUS_LEN = 16;
constexpr size_t PONG_LEN = 13;
constexpr size_t COMBINED_LEN = IMU_PACKET_LEN + RAW_PACKET_LEN;  // v2, MTU >= 40

// IMU_DATA flags
constexpr uint8_t F_VALID = 0x01;
constexpr uint8_t F_CALIB_OK = 0x02;
constexpr uint8_t F_RESET = 0x10;
inline uint8_t accuracyBits(uint8_t acc) { return (uint8_t)((acc & 0x03) << 2); }

// ESP32 is little-endian, so memcpy of native integers gives the wire order.
inline void put16(uint8_t* p, uint16_t v) { memcpy(p, &v, 2); }
inline void put32(uint8_t* p, uint32_t v) { memcpy(p, &v, 4); }
inline void put64(uint8_t* p, uint64_t v) { memcpy(p, &v, 8); }

inline int16_t fixed(float v, float scale) {
  float s = v * scale;
  if (s > 32767.f) s = 32767.f;
  if (s < -32768.f) s = -32768.f;
  return (int16_t)(s < 0 ? s - 0.5f : s + 0.5f);
}

inline uint8_t idByte(uint8_t unit, uint8_t sensor) { return (uint8_t)((unit << 4) | (sensor & 0x0F)); }

// Quaternion is w, x, y, z (BNO real part first), Q14.
inline void packImu(uint8_t out[IMU_PACKET_LEN], uint8_t unit, uint8_t sensor, uint8_t flags, uint16_t seq,
                    uint32_t tMs, float qw, float qx, float qy, float qz) {
  out[0] = idByte(unit, sensor);
  out[1] = flags;
  put16(out + 2, seq);
  put32(out + 4, tMs);
  put16(out + 8, (uint16_t)fixed(qw, 16384.f));
  put16(out + 10, (uint16_t)fixed(qx, 16384.f));
  put16(out + 12, (uint16_t)fixed(qy, 16384.f));
  put16(out + 14, (uint16_t)fixed(qz, 16384.f));
  out[16] = 0;
}

// gyro rad/s (Q10), gravity m/s^2 (Q8), sensor frame.
inline void packRaw(uint8_t out[RAW_PACKET_LEN], uint8_t unit, uint8_t sensor, bool gyroOk, bool gravOk, uint16_t seq,
                    uint32_t tMs, const float gyro[3], const float grav[3]) {
  out[0] = idByte(unit, sensor);
  out[1] = (uint8_t)((gyroOk ? 0x01 : 0) | (gravOk ? 0x02 : 0));
  put16(out + 2, seq);
  put32(out + 4, tMs);
  for (int i = 0; i < 3; i++) put16(out + 8 + 2 * i, (uint16_t)fixed(gyro[i], 1024.f));
  for (int i = 0; i < 3; i++) put16(out + 14 + 2 * i, (uint16_t)fixed(grav[i], 256.f));
}

struct StatusRecord {
  uint8_t fwMajor, fwMinor, fwPatch;
  uint8_t unit;
  uint8_t present;   // bit = sensor_id
  uint8_t ok;        // bit = sensor_id
  uint16_t batteryMv;  // 0 = unavailable (no divider), not empty
  uint16_t i2cErrors;
  bool streaming;
  uint8_t rateHz;
  bool haptics;
  uint8_t notifyDrops;  // notifications that could not be queued since boot, saturating
};

inline void packStatus(uint8_t out[STATUS_LEN], const StatusRecord& s) {
  out[0] = STATUS_RECORD;
  out[1] = PROTOCOL_VERSION;
  out[2] = s.fwMajor;
  out[3] = s.fwMinor;
  out[4] = s.fwPatch;
  out[5] = s.unit;
  out[6] = s.present;
  out[7] = s.ok;
  put16(out + 8, s.batteryMv);
  put16(out + 10, s.i2cErrors);
  out[12] = s.streaming ? 1 : 0;
  out[13] = s.rateHz;
  out[14] = s.haptics ? 1 : 0;
  out[15] = s.notifyDrops;
}

inline void packPong(uint8_t out[PONG_LEN], uint64_t hostUs, uint32_t tMs) {
  out[0] = STATUS_PONG;
  put64(out + 1, hostUs);
  put32(out + 9, tMs);
}

}  // namespace auri
