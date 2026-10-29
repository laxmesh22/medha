// Read-only detector for a Seeed XIAO on the strap bus.
// XIAO labels are the same on C3 and S3; the GPIO numbers are not (message 008).
// This board has no Qwiic/STEMMA socket; the scan is D4/D5 only.
// Does not drive the haptic driver. Game rotation vector is enabled only long enough to print 5 samples.

#include <Wire.h>
#include <esp_mac.h>
#include <esp_system.h>
#include "SparkFun_BNO08x_Arduino_Library.h"

#if CONFIG_IDF_TARGET_ESP32C3
static const int PIN_SDA = 6;  // D4
static const int PIN_SCL = 7;  // D5
static const int PIN_BAT = 3;  // D1, ADC1_CH3, 100k/100k divider reads Vbat/2
static const int PIN_RST = 5;  // D3, optional BNO RST
static const char *CHIP_FAMILY = "ESP32-C3";
#elif CONFIG_IDF_TARGET_ESP32S3
static const int PIN_SDA = 5;  // D4
static const int PIN_SCL = 6;  // D5
static const int PIN_BAT = 2;  // D1
static const int PIN_RST = 4;  // D3
static const char *CHIP_FAMILY = "ESP32-S3";
#else
#error "probe supports ESP32-C3 and ESP32-S3 only"
#endif

struct BusTry {
  const char *which;
  int sda;
  int scl;
  uint32_t hz;
};

// 400 kHz and the swapped pair run only when the selected pins at 100 kHz ACK nothing.
static const BusTry TRIES[] = {
  {"D4/D5", PIN_SDA, PIN_SCL, 100000},
  {"D4/D5", PIN_SDA, PIN_SCL, 400000},
  {"swapped", PIN_SCL, PIN_SDA, 100000},
};

static const char *nameAddr(uint8_t addr) {
  switch (addr) {
    case 0x4A:
    case 0x4B: return "BNO08x";
    case 0x5A: return "DRV2605L";
    case 0x28:
    case 0x29: return "BNO055";
    case 0x68:
    case 0x69: return "MPU/ICM";
    default: return "unknown";
  }
}

static const char *resetName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_EXT: return "external";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int-wdt";
    case ESP_RST_TASK_WDT: return "task-wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    case ESP_RST_USB: return "usb";
    case ESP_RST_JTAG: return "jtag";
    default: return "unknown";
  }
}

static void printChip() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_BT);
  esp_reset_reason_t reason = esp_reset_reason();
  Serial.printf("family %s\n", CHIP_FAMILY);
  Serial.printf("pins SDA D4/GPIO%d SCL D5/GPIO%d BAT D1/GPIO%d RST D3/GPIO%d\n",
                PIN_SDA, PIN_SCL, PIN_BAT, PIN_RST);
  Serial.printf("chip %s rev %u\n", ESP.getChipModel(), (unsigned)ESP.getChipRevision());
  Serial.printf("cpu_mhz %u\n", ESP.getCpuFreqMHz());
  Serial.printf("flash_bytes %u\n", ESP.getFlashChipSize());
  Serial.printf("psram_bytes %u\n", ESP.getPsramSize());
  Serial.printf("ble_mac %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.printf("reset %s (%d)\n", resetName(reason), (int)reason);
  Serial.printf("free_heap %u\n", ESP.getFreeHeap());
  Serial.println("qwiic none; this XIAO has no Qwiic/STEMMA socket; I2C is D4/D5 only");
  int mv = analogReadMilliVolts(PIN_BAT);
  Serial.printf("battery_pin_mV %d (D1/GPIO%d, may be floating if no divider)\n", mv, PIN_BAT);
}

static int scanBus(int sda, int scl, uint32_t hz, uint8_t *found, int cap) {
  Wire.end();
  delay(20);
  Wire.begin(sda, scl, hz);
  delay(50);
  int n = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("ACK 0x%02X %s\n", addr, nameAddr(addr));
      if (n < cap) found[n++] = addr;
    }
  }
  if (n == 0) Serial.println("no ACK");
  return n;
}

static void probeBno(uint8_t addr) {
  BNO08x imu;
  bool ok = imu.begin(addr, Wire, -1, -1);
  Serial.printf("bno08x 0x%02X begin %s (INT none, RST none)\n", addr, ok ? "ok" : "fail");
  if (!ok) {
    ok = imu.begin(addr, Wire, -1, PIN_RST);
    Serial.printf("bno08x 0x%02X begin %s (INT none, RST GPIO%d)\n", addr, ok ? "ok" : "fail", PIN_RST);
  }
  if (!ok) return;

  Serial.printf("bno08x 0x%02X product_entries %u\n", addr, imu.prodIds.numEntries);
  uint8_t n = imu.prodIds.numEntries;
  if (n > 5) n = 5;
  for (uint8_t i = 0; i < n; i++) {
    const sh2_ProductId_t &e = imu.prodIds.entry[i];
    Serial.printf("  part %lu fw %u.%u.%u build %lu reset_cause %u\n",
                  (unsigned long)e.swPartNumber,
                  e.swVersionMajor, e.swVersionMinor, e.swVersionPatch,
                  (unsigned long)e.swBuildNumber, e.resetCause);
  }

  bool enabled = imu.enableGameRotationVector(100);  // 100 ms -> 10 Hz
  Serial.printf("bno08x 0x%02X game_rotation_vector_10Hz %s\n", addr, enabled ? "ok" : "fail");
  uint32_t t0 = millis();
  int got = 0;
  while ((millis() - t0) < 2000 && got < 5) {
    if (imu.getSensorEvent() && imu.getSensorEventID() == SENSOR_REPORTID_GAME_ROTATION_VECTOR) {
      Serial.printf("  quat %d w %.5f x %.5f y %.5f z %.5f\n",
                    got, imu.getGameQuatReal(), imu.getGameQuatI(), imu.getGameQuatJ(), imu.getGameQuatK());
      got++;
    }
    delay(5);
  }
  Serial.printf("bno08x 0x%02X quats_printed %d window_ms %lu\n",
                addr, got, (unsigned long)(millis() - t0));
}

static void cycle() {
  Serial.println("--- probe cycle ---");
  printChip();
  uint8_t found[16];
  int n = 0;
  for (unsigned i = 0; i < sizeof(TRIES) / sizeof(TRIES[0]); i++) {
    Serial.printf("scan %s SDA=GPIO%d SCL=GPIO%d %lu kHz\n",
                  TRIES[i].which, TRIES[i].sda, TRIES[i].scl, TRIES[i].hz / 1000);
    n = scanBus(TRIES[i].sda, TRIES[i].scl, TRIES[i].hz, found, 16);
    if (n > 0) break;
  }
  if (n == 0) {
    Serial.println("i2c result: nothing ACKed on 100 kHz, 400 kHz, or swapped pins");
    return;
  }
  for (int i = 0; i < n; i++) {
    if (found[i] == 0x4A || found[i] == 0x4B) probeBno(found[i]);
  }
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && (millis() - t0) < 2000) delay(10);
  delay(200);
  cycle();
}

void loop() {
  delay(5000);
  cycle();
}
