// Minimal BNO08x (BNO085/BNO086) driver over I2C: SHTP transport + the few SH-2 messages Auri needs.
// Unlike the SparkFun/Adafruit libraries (one global CEVA SH-2 session, SparkFun sh2.c:323, shtp.c:148
// MAX_INSTANCES 1), every BnoLite object keeps its own state, so two sensors can share one bus (0x4A + 0x4B).
// References: CEVA "SH-2 Reference Manual" and "SHTP Reference Manual" (packet header, Set Feature 0xFD,
// Product ID 0xF9/0xF8, input reports and their lengths, base timestamp 0xFB, reset complete on channel 1).
#pragma once
#include <Arduino.h>
#include <Wire.h>

class BnoLite {
 public:
  // SH-2 report IDs used here
  static const uint8_t R_GYRO_CAL = 0x02, R_GRAVITY = 0x06, R_GAME_RV = 0x08;
  // poll() result bits
  static const uint8_t NEW_GAME_RV = 0x01, NEW_GYRO = 0x02, NEW_GRAVITY = 0x04;

  // Soft-resets the sensor, waits for it to come back, reads its product ID. False if it does not answer.
  bool begin(TwoWire& wire, uint8_t address);
  // Ask for a report every intervalUs (0 disables it).
  bool enable(uint8_t reportId, uint32_t intervalUs);
  // Read everything the sensor has queued (up to maxPackets); returns NEW_* bits for what arrived.
  uint8_t poll(int maxPackets = 6);
  // The sensor rebooted on its own (reports are off until enabled again). Clears the flag.
  bool takeReset();

  float quat[4] = {1, 0, 0, 0};  // w, x, y, z of the last game rotation vector
  uint8_t quatAccuracy = 0;      // SH-2 status bits 0-1 (0 unreliable .. 3 high)
  float gyro[3] = {0, 0, 0};     // rad/s, calibrated, sensor frame
  float gravity[3] = {0, 0, 0};  // m/s^2, sensor frame
  uint16_t i2cErrors = 0;
  // product ID (valid after begin)
  uint32_t partNumber = 0;
  uint8_t swMajor = 0, swMinor = 0;
  uint16_t swPatch = 0;
  uint32_t swBuild = 0;
  uint8_t resetCause = 0;

 private:
  // Fixed on BNO08x parts (datasheet, SHTP channels): CEVA's generic sh2.c looks them up by name from the boot
  // advertisement instead, which also works for other SH-2 hubs. If a future part reorders them, parse tag 0x81.
  static const uint8_t CH_COMMAND = 0, CH_EXECUTABLE = 1, CH_CONTROL = 2, CH_REPORTS = 3, CH_WAKE = 4;
  static const size_t BUF = 300;  // largest packet we keep (the boot advertisement is ~276 bytes)

  TwoWire* wire_ = nullptr;
  uint8_t addr_ = 0;
  uint8_t seq_[6] = {0};
  uint8_t buf_[BUF];
  bool reset_ = false;

  bool send(uint8_t channel, const uint8_t* data, uint8_t len);
  // Reads one packet into buf_; returns payload length (0 = nothing waiting, -1 = bus error).
  int receive(uint8_t& channel);
  uint8_t handle(uint8_t channel, int len);
  uint8_t parseReports(int len);
  void error() { if (i2cErrors < 0xFFFF) i2cErrors++; }
};
