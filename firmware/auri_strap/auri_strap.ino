// Auri strap firmware: BNO085 game rotation vector (+ calibrated gyro + gravity) over BLE, protocol v3.
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
#include <esp_sleep.h>
#include <driver/gpio.h>
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
  uint8_t recoverTries = 0;
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
static volatile bool cmdTare = false, cmdStatus = false, cmdWake = false, cmdPowerPending = false;
static volatile uint8_t cmdHaptic = 0, cmdRate = 0, cmdStream = 0xFF, cmdResetMask = 0;
static volatile uint8_t cmdPowerMode = 0, cmdPowerMinutes = 0;
static volatile bool pongPending = false;
static volatile uint64_t pongHostUs = 0;
static volatile uint32_t pongTms = 0;

static uint16_t testSeq = 0;
static uint32_t lastTestMs = 0, lastDetectMs = 0, lastStatusMs = 0, lastStatusKey = 0;

// Reports are held for a low cell or for the idle policy. Silence recovery must not turn them back on.
static bool reportsHeld = false;
static bool batteryStop = false;
static uint8_t batFlags = 0;
static uint16_t lastBatMv = 0;
static bool idleLatched = false;
static uint8_t idleTimeoutMin = 0;  // 0 = idle policy off
static uint8_t powerState = PWR_RUN;
static uint32_t discSince = 0;
static bool wasConnected = false;
static const int8_t TX_DBM = 9;  // matches NimBLEDevice::setPower(ESP_PWR_LVL_P9)
static const uint16_t ADV_SLOW = 1600;  // 1600 * 0.625 ms = 1 s
static const uint32_t IDLE_AWAKE_MS = 500;
static const uint32_t IDLE_SLEEP_US = 500000;

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
  if (!reportsHeld) enableReports(m);
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

// Non-blocking: send a soft reset and return. pollImu() keeps reporting the sensor as silent (valid = 0 at 5 Hz)
// until the sensor says it is back (takeReset), then re-enables its reports. After 3 failed tries, and only when
// RST is wired, pulse the shared reset line (this restarts every IMU on the pod).
static void recoverImu(Imu& m) {
  m.lastRecoverMs = millis();
  m.resetFlag = true;
  if (!i2cAck(m.slot.address)) {  // gone from the bus: detectImus() will look for it
    Serial.printf("imu sensor %u not on the bus\n", m.slot.sensorId);
    m.present = false;
    m.recoverTries = 0;
    return;
  }
  m.recoverTries++;
  Serial.printf("imu sensor %u silent: soft reset (try %u)\n", m.slot.sensorId, m.recoverTries);
  if (m.recoverTries > 3 && AURI_BNO_RST_WIRED) {
    hardResetImus();  // every sensor on the pod reboots and announces it; pollImu re-enables each
    m.recoverTries = 0;
    return;
  }
  m.dev.resetAsync();
}

static uint16_t notifyDrops = 0;
static uint16_t attPayload = 20;  // negotiated ATT MTU - 3; 20 until the client asks for more

static void notifyOrCount(NimBLECharacteristic* ch, const uint8_t* data, size_t len) {
  ch->setValue(data, len);
  if (!ch->notify() && notifyDrops < 0xFFFF) notifyDrops++;
}

// One packet per sensor sample. With a large enough MTU, orientation and the matching gyro + gravity record go out
// together in one 37-byte IMU_DATA notification (protocol v2); otherwise as two notifications (17 + 20 bytes).
static void sendImuPacket(Imu& m, bool valid) {
  uint8_t flags = (valid ? F_VALID : 0) | accuracyBits(m.accuracy) | (m.resetFlag ? F_RESET : 0);
  if (valid && m.accuracy >= 2) flags |= F_CALIB_OK;
  uint32_t t = millis();
  uint8_t buf[IMU_PACKET_LEN + RAW_PACKET_LEN];
  packImu(buf, AURI_UNIT, m.slot.sensorId, flags, m.seq, t, m.q[0], m.q[1], m.q[2], m.q[3]);
  packRaw(buf + IMU_PACKET_LEN, AURI_UNIT, m.slot.sensorId, valid && m.gyroOk, valid && m.gravOk, m.seq, t, m.gyro,
          m.grav);
  if (attPayload >= sizeof(buf)) {
    notifyOrCount(chImu, buf, sizeof(buf));
  } else {
    notifyOrCount(chImu, buf, IMU_PACKET_LEN);
    notifyOrCount(chRaw, buf + IMU_PACKET_LEN, RAW_PACKET_LEN);
  }
  m.seq++;
  m.resetFlag = false;
}

// Drain every event the sensor has queued; send one packet per new game-rotation-vector sample.
static void pollImu(Imu& m) {
  if (!m.present || reportsHeld) return;
  uint8_t got = m.dev.poll();
  if (m.dev.takeReset()) {  // the BNO rebooted on its own: reports are gone, re-enable them
    Serial.printf("imu sensor %u reset (by us or by itself): re-enabling reports\n", m.slot.sensorId);
    enableReports(m);
    m.resetFlag = true;
    m.recoverTries = 0;
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

static void updateBattery();
static void sendPower();

static void sendStatus() {
  updateBattery();
  sendPower();  // notified first; the 16-byte record is written last so a GATT read still returns it
  StatusRecord s{};
  s.fwMajor = FW_MAJOR;
  s.fwMinor = FW_MINOR;
  s.fwPatch = FW_PATCH;
  s.unit = AURI_UNIT;
  for (size_t i = 0; i < IMU_COUNT; i++) {
    if (imus[i].present) s.present |= 1 << imus[i].slot.sensorId;
    if (imus[i].streaming) s.ok |= 1 << imus[i].slot.sensorId;
  }
  s.batteryMv = lastBatMv;
  uint32_t errs = i2cErrors;
  for (size_t i = 0; i < IMU_COUNT; i++) errs += imus[i].dev.i2cErrors;
  s.i2cErrors = errs > 0xFFFF ? 0xFFFF : (uint16_t)errs;
  s.streaming = streamOn && !reportsHeld;
  s.rateHz = rateHz;
  s.haptics = hapticsPresent;
  s.notifyDrops = notifyDrops > 0xFF ? 0xFF : (uint8_t)notifyDrops;
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

static void disableReports(Imu& m) {
  m.dev.enable(BnoLite::R_GAME_RV, 0);
  m.dev.enable(BnoLite::R_GYRO_CAL, 0);
  m.dev.enable(BnoLite::R_GRAVITY, 0);
  m.streaming = false;
}

static void holdReports(bool hold) {
  if (hold == reportsHeld) return;
  reportsHeld = hold;
  for (size_t i = 0; i < IMU_COUNT; i++) {
    if (!imus[i].present) continue;
    if (hold) disableReports(imus[i]);
    else enableReports(imus[i]);
  }
}

static void syncReports() { holdReports(batteryStop || idleLatched); }

static void applyAdv(bool slow) {
  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  if (adv == nullptr) return;
  adv->setAdvertisingInterval(slow ? ADV_SLOW : 0);  // 0 = the stack default used at boot
  if (!connected) {
    adv->stop();
    adv->start();
  }
}

static void enterIdle() {
  if (idleLatched) return;
  idleLatched = true;
  powerState = PWR_SLOW;
  syncReports();
  applyAdv(true);
  cmdStatus = true;
  Serial.println("idle: reports off, advertising 1 s");
}

static void leaveIdle() {
  if (!idleLatched && powerState == PWR_RUN) return;
  idleLatched = false;
  powerState = PWR_RUN;
  discSince = millis();
  applyAdv(false);
  syncReports();
  cmdStatus = true;
  Serial.println("idle: awake");
}

// Divider-off builds never set a flag and never stop the sensors. 0 mV stays "unavailable".
static void updateBattery() {
#if !AURI_HAS_BATTERY_DIVIDER
  lastBatMv = 0;
  batFlags = 0;
  if (batteryStop) {
    batteryStop = false;
    syncReports();
  }
#else
  uint16_t mv = batteryMv();
  lastBatMv = mv;
  if (mv == 0) {
    batFlags = 0;
    if (batteryStop) {
      batteryStop = false;
      syncReports();
    }
    return;
  }
  // +50 mV to release, so ADC noise around the PLACEHOLDER thresholds does not re-buzz.
  bool warn = (batFlags & 0x01) ? mv <= (uint16_t)(AURI_BAT_WARN_MV + 50) : mv <= AURI_BAT_WARN_MV;
  bool stop = (batFlags & 0x02) ? mv <= (uint16_t)(AURI_BAT_STOP_MV + 50) : mv <= AURI_BAT_STOP_MV;
  uint8_t next = (warn ? 0x01 : 0) | (stop ? 0x02 : 0);
  if ((next & 0x01) && !(batFlags & 0x01)) playHaptic(HAPTIC_WARNING);
  bool changed = next != batFlags || stop != batteryStop;
  batFlags = next;
  batteryStop = stop;
  if (changed) {
    syncReports();
    cmdStatus = true;
  }
#endif
}

static void sendPower() {
  if (chStatus == nullptr) return;
  uint8_t buf[POWER_LEN];
  uint16_t idleS = (uint16_t)idleTimeoutMin * 60;
  packPower(buf, batFlags, powerState, TX_DBM, idleS);
  chStatus->setValue(buf, sizeof(buf));
  if (connected) chStatus->notify();
}

static void serviceIdle() {
#if AURI_WAKE_BTN
  bool buttonDown = digitalRead(PIN_INT) == LOW;
#else
  bool buttonDown = false;
#endif
  if (buttonDown && idleLatched) leaveIdle();
  if (connected) {
    if (!wasConnected) cmdWake = true;
    wasConnected = true;
  } else if (wasConnected) {
    wasConnected = false;
    discSince = millis();
  }
  if (cmdWake) {
    cmdWake = false;
    leaveIdle();
  }
  if (!connected && !idleLatched && !buttonDown && idleTimeoutMin > 0 &&
      (uint32_t)(millis() - discSince) >= (uint32_t)idleTimeoutMin * 60000UL) {
    enterIdle();
  }
  if (!idleLatched || connected) return;
  // The Arduino-ESP32 3.3.12 C3 NimBLE library is built with modem-sleep and automatic
  // light-sleep off, so a long blocking sleep stops advertising. Stay awake 500 ms, sleep 500 ms.
  static uint32_t awakeSince = 0;
  uint32_t now = millis();
  if (awakeSince == 0) awakeSince = now;
  if ((uint32_t)(now - awakeSince) < IDLE_AWAKE_MS) return;
  awakeSince = 0;
  esp_sleep_enable_timer_wakeup(IDLE_SLEEP_US);
  esp_sleep_enable_bt_wakeup();
#if AURI_WAKE_BTN
  gpio_wakeup_enable((gpio_num_t)PIN_INT, GPIO_INTR_LOW_LEVEL);
  esp_sleep_enable_gpio_wakeup();
#endif
  if (esp_light_sleep_start() == ESP_OK) powerState = PWR_LIGHT;
  awakeSince = millis();
}

// ---------------------------------------------------------------------------------------------------------------------
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
    connected = true;
    cmdWake = true;  // a connection leaves idle; I2C stays in loop()
    // Windows exchanges the MTU before this callback runs, so onMTUChange may already have fired: read the current
    // value instead of resetting it (resetting to 20 kept the 37-byte path off in test 017).
    attPayload = info.getMTU() > 3 ? info.getMTU() - 3 : 20;
    s->updateConnParams(info.getConnHandle(), 6, 12, 0, 400);  // 7.5-15 ms interval for 100-200 notifies/s
    Serial.printf("ble connected %s\n", info.getAddress().toString().c_str());
  }
  void onMTUChange(uint16_t mtu, NimBLEConnInfo&) override {
    attPayload = mtu > 3 ? mtu - 3 : 20;
    Serial.printf("ble mtu %u: %s packets\n", mtu, attPayload >= IMU_PACKET_LEN + RAW_PACKET_LEN ? "combined 37-byte"
                                                                                                    : "17 + 20 byte");
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int reason) override {
    connected = false;
    attPayload = 20;
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
      case CMD_POWER:
        if (n >= 2) {
          cmdPowerMode = d[1];
          cmdPowerMinutes = (d[1] == PWR_MODE_TIMEOUT && n >= 3) ? d[2] : 0;
          cmdPowerPending = true;
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

  Wire.begin(I2C_SDA, I2C_SCL, I2C_HZ);
  Serial.printf("i2c SDA GPIO%d, SCL GPIO%d, %lu Hz\n", I2C_SDA, I2C_SCL, (unsigned long)I2C_HZ);
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
#if AURI_WAKE_BTN
  pinMode(PIN_INT, INPUT_PULLUP);  // D2 to GND, external button; idle light-sleep wake
  Serial.println("wake button: D2");
#endif
  discSince = millis();

  setupBle();
  if (chStatus) sendStatus();
}

void loop() {
  uint32_t now = millis();

  // commands queued by the BLE task
  if (cmdRate) {
    rateHz = cmdRate < 10 ? 10 : (cmdRate > 100 ? 100 : cmdRate);
    cmdRate = 0;
    if (!reportsHeld)
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
        if (!reportsHeld) enableReports(imus[i]);
        imus[i].resetFlag = true;
      }
    cmdStatus = true;
  }
  if (cmdPowerPending) {
    uint8_t mode = cmdPowerMode;
    uint8_t minutes = cmdPowerMinutes;
    cmdPowerPending = false;
    if (mode == PWR_MODE_RUN) {
      idleTimeoutMin = 0;
      leaveIdle();
    } else if (mode == PWR_MODE_SLEEP) {
      enterIdle();
    } else if (mode == PWR_MODE_TIMEOUT) {
      idleTimeoutMin = minutes;
      discSince = millis();
      if (minutes == 0) leaveIdle();
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

  // A BNO that is still busy after an MCU-only reset answers within ~2.5 s: look every 0.5 s for the first 5 s.
  if (now - lastDetectMs >= (now < 5000 ? 500 : DETECT_EVERY_MS)) {
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
  serviceIdle();
  delay(1);
}
