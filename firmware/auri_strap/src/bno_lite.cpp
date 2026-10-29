#include "bno_lite.h"

// SHTP over I2C: every packet starts with a 4-byte header: length (15 bits, includes the header; bit 15 =
// continuation), channel, per-channel sequence number. A read returns the header and as much of the packet as was
// asked for; the next read continues it with a fresh (continuation) header. ESP32 Wire buffers 128 bytes.
static const size_t I2C_CHUNK = 128;

static inline int16_t le16(const uint8_t* p) { return (int16_t)(p[0] | (p[1] << 8)); }
static inline uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

bool BnoLite::send(uint8_t channel, const uint8_t* data, uint8_t len) {
  uint16_t total = len + 4;
  wire_->beginTransmission(addr_);
  wire_->write((uint8_t)(total & 0xFF));
  wire_->write((uint8_t)(total >> 8));
  wire_->write(channel);
  wire_->write(seq_[channel]++);
  wire_->write(data, len);
  if (wire_->endTransmission() != 0) {
    error();
    return false;
  }
  return true;
}

int BnoLite::receive(uint8_t& channel) {
  if (wire_->requestFrom(addr_, (uint8_t)4) != 4) {
    error();
    return -1;
  }
  uint8_t h[4];
  for (int i = 0; i < 4; i++) h[i] = wire_->read();
  uint16_t len = (uint16_t)(h[0] | (h[1] << 8)) & 0x7FFF;
  if (len <= 4 || len == 0x7FFF) return 0;  // nothing waiting (0) or bus floating high
  channel = h[2];
  int payload = len - 4;
  int got = 0;
  while (got < payload) {
    int chunk = payload - got;
    if (chunk > (int)(I2C_CHUNK - 4)) chunk = I2C_CHUNK - 4;
    int n = wire_->requestFrom(addr_, (uint8_t)(chunk + 4));
    if (n != chunk + 4) {
      error();
      while (wire_->available()) wire_->read();
      return -1;
    }
    // Each read starts with a (continuation) header. It must be on our channel and announce at least the bytes we
    // still expect; anything else means we fell out of step with the sensor, so drop the packet as a bus error.
    uint8_t c[4];
    for (int i = 0; i < 4; i++) c[i] = wire_->read();
    uint16_t fragLen = (uint16_t)(c[0] | (c[1] << 8)) & 0x7FFF;
    if (c[2] != channel || fragLen < 4 || fragLen - 4 < (uint16_t)chunk) {
      error();
      while (wire_->available()) wire_->read();
      return -1;
    }
    for (int i = 0; i < chunk; i++) {
      uint8_t b = wire_->read();
      if (got + i < (int)BUF) buf_[got + i] = b;
    }
    got += chunk;
  }
  return payload > (int)BUF ? (int)BUF : payload;
}

bool BnoLite::begin(TwoWire& wire, uint8_t address) {
  wire_ = &wire;
  addr_ = address;
  memset(seq_, 0, sizeof(seq_));
  wire_->beginTransmission(addr_);
  if (wire_->endTransmission() != 0) return false;

  // Soft reset (executable channel, command 1), then drain the advertisement / reset-complete / init packets.
  const uint8_t resetCmd[1] = {1};
  send(CH_EXECUTABLE, resetCmd, 1);
  uint32_t t0 = millis();
  bool resetSeen = false;
  while (millis() - t0 < 600) {
    uint8_t ch;
    int n = receive(ch);
    if (n > 0 && ch == CH_EXECUTABLE && buf_[0] == 1) resetSeen = true;
    if (n <= 0) delay(10);
  }
  reset_ = false;

  // Product ID request 0xF9 -> response 0xF8 on the control channel.
  const uint8_t prodReq[2] = {0xF9, 0};
  if (!send(CH_CONTROL, prodReq, 2)) return false;
  t0 = millis();
  while (millis() - t0 < 300) {
    uint8_t ch;
    int n = receive(ch);
    if (n >= 14 && ch == CH_CONTROL && buf_[0] == 0xF8) {
      resetCause = buf_[1];
      swMajor = buf_[2];
      swMinor = buf_[3];
      partNumber = le32(buf_ + 4);
      swBuild = le32(buf_ + 8);
      swPatch = (uint16_t)le16(buf_ + 12);
      return true;
    }
    if (n <= 0) delay(5);
  }
  return resetSeen;  // answered the reset but not the product ID: still usable, IDs stay 0
}

bool BnoLite::enable(uint8_t reportId, uint32_t intervalUs) {
  // Set Feature 0xFD: id, flags, change sensitivity (2), report interval us (4), batch interval (4), sensor config (4)
  uint8_t cmd[17] = {0};
  cmd[0] = 0xFD;
  cmd[1] = reportId;
  cmd[5] = intervalUs & 0xFF;
  cmd[6] = (intervalUs >> 8) & 0xFF;
  cmd[7] = (intervalUs >> 16) & 0xFF;
  cmd[8] = (intervalUs >> 24) & 0xFF;
  return send(CH_CONTROL, cmd, sizeof(cmd));
}

bool BnoLite::takeReset() {
  bool r = reset_;
  reset_ = false;
  return r;
}

uint8_t BnoLite::poll(int maxPackets) {
  uint8_t got = 0;
  for (int i = 0; i < maxPackets; i++) {
    uint8_t ch;
    int n = receive(ch);
    if (n <= 0) break;
    got |= handle(ch, n);
  }
  return got;
}

uint8_t BnoLite::handle(uint8_t channel, int len) {
  if (channel == CH_EXECUTABLE && len >= 1 && buf_[0] == 1) {  // reset complete: the sensor rebooted
    reset_ = true;
    return 0;
  }
  if (channel == CH_REPORTS || channel == CH_WAKE) return parseReports(len);
  return 0;  // command-channel advertisements, Get Feature responses, etc.
}

// Input report lengths (bytes, including the 4-byte id/seq/status/delay header) for reports that can share a
// packet. An unknown id ends the packet: its length is not known, so nothing after it can be trusted.
static int reportLength(uint8_t id) {
  switch (id) {
    case 0xFB: return 5;   // base timestamp
    case 0xFA: return 5;   // timestamp rebase
    case 0x01: return 10;  // accelerometer
    case 0x02: return 10;  // gyroscope calibrated
    case 0x03: return 10;  // magnetic field calibrated
    case 0x04: return 10;  // linear acceleration
    case 0x05: return 14;  // rotation vector
    case 0x06: return 10;  // gravity
    case 0x07: return 16;  // gyroscope uncalibrated
    case 0x08: return 12;  // game rotation vector
    case 0x09: return 14;  // geomagnetic rotation vector
    default: return 0;
  }
}

uint8_t BnoLite::parseReports(int len) {
  uint8_t got = 0;
  int i = 0;
  while (i < len) {
    uint8_t id = buf_[i];
    int rl = reportLength(id);
    if (rl == 0 || i + rl > len) break;
    const uint8_t* r = buf_ + i;
    uint8_t status = r[2] & 0x03;
    switch (id) {
      case R_GAME_RV:  // i, j, k, real, Q14
        quat[1] = le16(r + 4) / 16384.0f;
        quat[2] = le16(r + 6) / 16384.0f;
        quat[3] = le16(r + 8) / 16384.0f;
        quat[0] = le16(r + 10) / 16384.0f;
        quatAccuracy = status;
        got |= NEW_GAME_RV;
        break;
      case R_GYRO_CAL:  // rad/s Q9
        for (int k = 0; k < 3; k++) gyro[k] = le16(r + 4 + 2 * k) / 512.0f;
        got |= NEW_GYRO;
        break;
      case R_GRAVITY:  // m/s^2 Q8
        for (int k = 0; k < 3; k++) gravity[k] = le16(r + 4 + 2 * k) / 256.0f;
        got |= NEW_GRAVITY;
        break;
    }
    i += rl;
  }
  return got;
}
