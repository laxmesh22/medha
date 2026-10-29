// Auri strap firmware: BNO085 game rotation vector (+ calibrated gyro + gravity) over BLE, protocol v1.
// Contract: firmware/protocol/PROTOCOL.md. Spec: agenthandoff.md §7. Pins and unit: board.h.
//
// Rules this firmware keeps (handoff §0 / §7):
//  - packets are sent only when the sensor produced a sample; a silent sensor (> 200 ms) is reported with valid = 0
//    and the last good quaternion, and the firmware tries to recover it. Nothing is ever made up.
//  - binary packets only (JSON over BLE caused brownouts in a published ESP32 project).
//  - no magnetometer: game rotation vector; yaw is per-sensor arbitrary and the hub calibrates it.
//  - I2C work happens in loop(), never inside BLE callbacks (they only queue commands).

#include <Wire.h>
#include <NimBLEDevice.h>
#include <Adafruit_DRV2605.h>
#include "board.h"
#include "src/bno_lite.h"  // own SH-2 driver: the SparkFun/Adafruit ones allow only one BNO08x per MCU

using namespace auri;

static const uint32_t SILENT_MS = 200;        // handoff §7: IMU silence > 200 ms -> valid = 0 + recover
static const uint32_t RECOVER_EVERY_MS = 1000;
static const uint32_t DETECT_EVERY_MS = 3000;  // look again for IMUs that were absent at boot
static const uint32_t STATUS_EVERY_MS = 2000;

// ---------------------------------------------------------------------------------------------------------------------
struct Imu {
  ImuSlot slot;
  BnoLite dev;
  bool present = false;
  bool streaming = false;  // produced a sample within SILENT_MS
  bool resetFlag = false;  // sticky until the next packet of this sensor
  uint16_t seq = 0;
  uint32_t lastSampleMs = 0, lastSilentPacketMs = 0, lastRecoverMs = 0;
  float q[4] = {1, 0, 0, 0};  // w, x, y, z (last good)
  uint8_t accuracy = 0;
  float gyro[3] = {0, 0, 0}, grav[3] = {0, 0, 0};
  bool gyroOk = false, gravOk = false;
};

static Imu imus[IMU_COUNT];
static Adafruit_DRV2605 drv;
static bool hapticsPresent = false;
static uint16_t i2cErrors = 0;

static uint8_t rateHz = 50;
static volatile bool streamOn = true;

static NimBLEServer* server = nullptr;
static NimBLECharacteristic *chImu = nullptr, *chRaw = nullptr, *chStatus = nullptr, *chBattery = nullptr;
static volatile bool connected = false;

// Commands arrive in the BLE task; loop() executes them.
static volatile bool cmdTare = false, cmdStatus = false;
static volatile uint8_t cmdHaptic = 0, cmdRate = 0, cmdStream = 0xFF, cmdResetMask = 0;
static volatile bool pongPending = false;
static volatile uint64_t pongHostUs = 0;
static volatile uint32_t pongTms = 0;

static uint16_t testSeq = 0;
static uint32_t lastTestMs = 0, lastDetectMs = 0, lastStatusMs = 0, lastStatusKey = 0;

// ---------------------------------------------------------------------------------------------------------------------
static bool i2cAck(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

static uint32_t reportIntervalUs() { return 1000000UL / rateHz; }

static bool enableReports(Imu& m) {
  uint32_t us = reportIntervalUs();
  bool ok = m.dev.enable(BnoLite::R_GAME_RV, us);
  ok = m.dev.enable(BnoLite::R_GYRO_CAL, us) && ok;
  ok = m.dev.enable(BnoLite::R_GRAVITY, us) && ok;
  return ok;
}

// Both BNOs share the RST line when it is wired (handoff §6.1 has one D3), so a hard reset hits every sensor.
static void hardResetImus() {
  pinMode(PIN_RST, OUTPUT);
  digitalWrite(PIN_RST, LOW);
  delay(10);
  digitalWrite(PIN_RST, HIGH);
  delay(100);
}

static bool startImu(Imu& m) {
  if (!i2cAck(m.slot.address)) return false;
  if (!m.dev.begin(Wire, m.slot.address)) return false;
  enableReports(m);
  m.present = true;
  m.lastSampleMs = millis();
  Serial.printf("imu sensor %u at 0x%02X: started (part %lu, sw %u.%u.%u build %lu, reset cause %u)\n",
                m.slot.sensorId, m.slot.address, (unsigned long)m.dev.partNumber, m.dev.swMajor, m.dev.swMinor,
                m.dev.swPatch, (unsigned long)m.dev.swBuild, m.dev.resetCause);
  return true;
}

static void detectImus() {
  for (size_t i = 0; i < IMU_COUNT; i++)
    if (!imus[i].present) startImu(imus[i]);
}

static void recoverImu(Imu& m) {
  m.lastRecoverMs = millis();
  Serial.printf("imu sensor %u silent: recovering\n", m.slot.sensorId);
  if (!startImu(m)) {  // soft reset first; the shared RST line only if that fails
    if (AURI_BNO_RST_WIRED) {
      hardResetImus();
      for (size_t i = 0; i < IMU_COUNT; i++)
        if (&imus[i] != &m && imus[i].present) imus[i].dev.takeReset(), enableReports(imus[i]);
    }
    if (!startImu(m)) m.present = false;  // detectImus() keeps looking for it
  }
  m.resetFlag = true;
}

static void sendImuPacket(Imu& m, bool valid) {
  uint8_t flags = (valid ? F_VALID : 0) | accuracyBits(m.accuracy) | (m.resetFlag ? F_RESET : 0);
  if (valid && m.accuracy >= 2) flags |= F_CALIB_OK;
  uint8_t buf[IMU_PACKET_LEN];
  packImu(buf, AURI_UNIT, m.slot.sensorId, flags, m.seq, millis(), m.q[0], m.q[1], m.q[2], m.q[3]);
  chImu->setValue(buf, sizeof(buf));
  chImu->notify();
  uint8_t raw[RAW_PACKET_LEN];
  packRaw(raw, AURI_UNIT, m.slot.sensorId, valid && m.gyroOk, valid && m.gravOk, m.seq, millis(), m.gyro, m.grav);
  chRaw->setValue(raw, sizeof(raw));
  chRaw->notify();
  m.seq++;
  m.resetFlag = false;
}

// Drain every event the sensor has queued; send one packet per new game-rotation-vector sample.
static void pollImu(Imu& m) {
  if (!m.present) return;
  uint8_t got = m.dev.poll();
  if (m.dev.takeReset()) {  // the BNO rebooted on its own: reports are gone, re-enable them
    Serial.printf("imu sensor %u reset itself: re-enabling reports\n", m.slot.sensorId);
    enableReports(m);
    m.resetFlag = true;
  }
  // gyro and gravity first, so the packet sent for this rotation sample carries the newest of both
  if (got & BnoLite::NEW_GYRO) {
    memcpy(m.gyro, m.dev.gyro, sizeof(m.gyro));
    m.gyroOk = true;
  }
  if (got & BnoLite::NEW_GRAVITY) {
    memcpy(m.grav, m.dev.gravity, sizeof(m.grav));
    m.gravOk = true;
  }
  if (got & BnoLite::NEW_GAME_RV) {
    memcpy(m.q, m.dev.quat, sizeof(m.q));
    m.accuracy = m.dev.quatAccuracy;
    m.lastSampleMs = millis();
    m.streaming = true;
    if (connected && streamOn) sendImuPacket(m, true);
  }
  uint32_t now = millis();
  if (now - m.lastSampleMs > SILENT_MS) {
    m.streaming = false;
    m.gyroOk = m.gravOk = false;
    if (connected && streamOn && now - m.lastSilentPacketMs >= SILENT_MS) {  // tell the hub, at 5 Hz, flagged invalid
      m.lastSilentPacketMs = now;
      sendImuPacket(m, false);
    }
    if (now - m.lastRecoverMs >= RECOVER_EVERY_MS) recoverImu(m);
  }
}

// ---------------------------------------------------------------------------------------------------------------------
static uint16_t batteryMv() {
  if (!AURI_HAS_BATTERY_DIVIDER) return 0;  // 0 = unavailable (protocol), not an empty battery
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogReadMilliVolts(PIN_BAT);
  return (uint16_t)(sum / 8 * 2);  // 100k/100k divider reads Vbat/2
}

static uint8_t batteryPercent(uint16_t mv) {  // rough LiPo curve, 3.3 V empty, 4.2 V full
  if (mv >= 4200) return 100;
  if (mv <= 3300) return 0;
  return (uint8_t)((mv - 3300) * 100 / 900);
}

static void sendStatus() {
  StatusRecord s{};
  s.fwMajor = FW_MAJOR;
  s.fwMinor = FW_MINOR;
  s.fwPatch = FW_PATCH;
  s.unit = AURI_UNIT;
  for (size_t i = 0; i < IMU_COUNT; i++) {
    if (imus[i].present) s.present |= 1 << imus[i].slot.sensorId;
    if (imus[i].streaming) s.ok |= 1 << imus[i].slot.sensorId;
  }
  s.batteryMv = batteryMv();
  uint32_t errs = i2cErrors;
  for (size_t i = 0; i < IMU_COUNT; i++) errs += imus[i].dev.i2cErrors;
  s.i2cErrors = errs > 0xFFFF ? 0xFFFF : (uint16_t)errs;
  s.streaming = streamOn;
  s.rateHz = rateHz;
  s.haptics = hapticsPresent;
  uint8_t buf[STATUS_LEN];
  packStatus(buf, s);
  chStatus->setValue(buf, sizeof(buf));
  if (connected) chStatus->notify();
  if (chBattery && s.batteryMv) {
    uint8_t pct = batteryPercent(s.batteryMv);
    chBattery->setValue(&pct, 1);
    if (connected) chBattery->notify();
  }
  lastStatusKey = (uint32_t)s.present | (uint32_t)s.ok << 8 | (uint32_t)streamOn << 16 | (uint32_t)rateHz << 24;
}

static uint32_t statusKey() {
  uint32_t present = 0, ok = 0;
  for (size_t i = 0; i < IMU_COUNT; i++) {
    if (imus[i].present) present |= 1 << imus[i].slot.sensorId;
    if (imus[i].streaming) ok |= 1 << imus[i].slot.sensorId;
  }
  return present | ok << 8 | (uint32_t)streamOn << 16 | (uint32_t)rateHz << 24;
}

static void playHaptic(uint8_t pattern) {
  if (!hapticsPresent) return;
  // DRV2605L ROM library 1 (ERM) effects: 1 strong click, 10 double click, 47 buzz 100 %, 14 strong buzz
  static const uint8_t effect[] = {0, 1, 10, 47, 14};
  if (pattern < 1 || pattern > 4) return;
  drv.setWaveform(0, effect[pattern]);
  drv.setWaveform(1, 0);
  drv.go();
}

// ---------------------------------------------------------------------------------------------------------------------
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
    connected = true;
    s->updateConnParams(info.getConnHandle(), 6, 12, 0, 400);  // 7.5-15 ms interval for 100-200 notifies/s
    Serial.printf("ble connected %s\n", info.getAddress().toString().c_str());
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int reason) override {
    connected = false;
    Serial.printf("ble disconnected (reason %d), advertising again\n", reason);
    NimBLEDevice::startAdvertising();
  }
};

class CommandCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo&) override {
    NimBLEAttValue v = c->getValue();
    const uint8_t* d = v.data();
    size_t n = v.length();
    if (n == 0) return;
    switch (d[0]) {
      case CMD_TARE: cmdTare = true; break;
      case CMD_HAPTIC: if (n >= 2) cmdHaptic = d[1]; break;
      case CMD_RATE: if (n >= 2) cmdRate = d[1]; break;
      case CMD_STREAM: if (n >= 2) cmdStream = d[1] ? 1 : 0; break;
      case CMD_IMU_RESET: if (n >= 2) cmdResetMask = d[1]; break;
      case CMD_TIME_PING:
        if (n >= 9) {
          uint64_t h;
          memcpy(&h, d + 1, 8);
          pongTms = millis();  // stamp on reception, before any queueing delay
          pongHostUs = h;
          pongPending = true;
        }
        break;
    }
  }
};

static void setupBle() {
  // NimBLE 2.5 init() returns false when the controller does not start; ignoring that still printed "advertising".
  if (!NimBLEDevice::init(DEVICE_NAME)) {
    Serial.println("ble init FAILED");
    return;
  }
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);
  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(SERVICE_UUID);
  chImu = svc->createCharacteristic(IMU_DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  chRaw = svc->createCharacteristic(RAW_DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic* chCmd =
      svc->createCharacteristic(COMMAND_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  chCmd->setCallbacks(new CommandCallbacks());
  chStatus = svc->createCharacteristic(STATUS_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  svc->start();

  if (AURI_HAS_BATTERY_DIVIDER) {  // no divider -> no Battery Service (a made-up % would be worse than none)
    NimBLEService* bat = server->createService(NimBLEUUID((uint16_t)0x180F));
    chBattery = bat->createCharacteristic(NimBLEUUID((uint16_t)0x2A19), NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
    bat->start();
  }

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  // Scan response must be on before setName, or NimBLE 2.5 puts the name in the 31-byte advert
  // and the 128-bit service UUID may not fit (NimBLEAdvertising.cpp setName).
  adv->enableScanResponse(true);
  if (!adv->setName(DEVICE_NAME)) Serial.println("ble name did not fit");
  if (!adv->addServiceUUID(SERVICE_UUID)) Serial.println("ble service uuid did not fit");
  bool advOk = adv->start();
  Serial.printf("advertising as %s (%s)\n", DEVICE_NAME, advOk ? "started" : "FAILED");
}

// ---------------------------------------------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);
  Serial.printf("Auri strap %u.%u.%u, %s, unit %u (%s), protocol v%u\n", FW_MAJOR, FW_MINOR, FW_PATCH, CHIP,
                AURI_UNIT, DEVICE_NAME, PROTOCOL_VERSION);

  Wire.begin(PIN_SDA, PIN_SCL, I2C_HZ);
  for (size_t i = 0; i < IMU_COUNT; i++) imus[i].slot = IMU_SLOTS[i];
  detectImus();
  if (UNIT_HAS_HAPTICS && i2cAck(0x5A) && drv.begin(&Wire)) {
    drv.selectLibrary(1);  // ERM coin motor
    drv.setMode(DRV2605_MODE_INTTRIG);
    hapticsPresent = true;
  }
  for (size_t i = 0; i < IMU_COUNT; i++)
    Serial.printf("imu sensor %u at 0x%02X: %s\n", imus[i].slot.sensorId, imus[i].slot.address,
                  imus[i].present ? "present" : "absent (will keep looking)");
  Serial.printf("haptics: %s; battery divider: %s\n", hapticsPresent ? "DRV2605L" : "none",
                AURI_HAS_BATTERY_DIVIDER ? "yes" : "no (battery unavailable)");

  setupBle();
  if (chStatus) sendStatus();
}

void loop() {
  uint32_t now = millis();

  // commands queued by the BLE task
  if (cmdRate) {
    rateHz = cmdRate < 10 ? 10 : (cmdRate > 100 ? 100 : cmdRate);
    cmdRate = 0;
    for (size_t i = 0; i < IMU_COUNT; i++)
      if (imus[i].present) enableReports(imus[i]);
    cmdStatus = true;
  }
  if (cmdStream != 0xFF) {
    streamOn = cmdStream == 1;
    cmdStream = 0xFF;
    cmdStatus = true;
  }
  if (cmdTare) {
    cmdTare = false;
    for (size_t i = 0; i < IMU_COUNT; i++)
      if (imus[i].present) {
        enableReports(imus[i]);
        imus[i].resetFlag = true;
      }
    cmdStatus = true;
  }
  if (cmdResetMask) {
    uint8_t mask = cmdResetMask;
    cmdResetMask = 0;
    for (size_t i = 0; i < IMU_COUNT; i++)
      if (mask & (1 << imus[i].slot.sensorId)) recoverImu(imus[i]);
    cmdStatus = true;
  }
  if (cmdHaptic) {
    playHaptic(cmdHaptic);
    cmdHaptic = 0;
  }
  if (pongPending) {
    pongPending = false;
    uint8_t buf[PONG_LEN];
    packPong(buf, pongHostUs, pongTms);
    chStatus->setValue(buf, sizeof(buf));
    if (connected) chStatus->notify();
  }

  for (size_t i = 0; i < IMU_COUNT; i++) pollImu(imus[i]);

  if (now - lastDetectMs >= DETECT_EVERY_MS) {
    lastDetectMs = now;
    detectImus();
  }

#if AURI_TEST_PATTERN
  // Link test without sensors: invalid packets on sensor 15 at the stream rate. The hub must ignore them.
  bool anyPresent = false;
  for (size_t i = 0; i < IMU_COUNT; i++) anyPresent |= imus[i].present;
  if (!anyPresent && connected && streamOn && now - lastTestMs >= 1000 / rateHz) {
    lastTestMs = now;
    uint8_t buf[IMU_PACKET_LEN];
    packImu(buf, AURI_UNIT, 15, 0, testSeq++, now, 1, 0, 0, 0);
    chImu->setValue(buf, sizeof(buf));
    chImu->notify();
  }
#endif

  if (cmdStatus || now - lastStatusMs >= STATUS_EVERY_MS || statusKey() != lastStatusKey) {
    cmdStatus = false;
    lastStatusMs = now;
    sendStatus();
  }
  delay(1);
}
