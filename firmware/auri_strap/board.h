// Board and unit configuration for the Auri strap firmware.
// XIAO pin labels are the same on the ESP32-C3 and ESP32-S3 boards; the GPIO numbers are not (handoff §6.1 is S3).
#pragma once
#include "src/auri_ble.h"

// ---- which pod this build is for (override with -DAURI_UNIT=2) -----------------------------------------------------
#ifndef AURI_UNIT
#define AURI_UNIT 1  // 1 = AURI-ARM (upper arm + forearm + haptics), 2 = AURI-TRUNK
#endif

// ---- optional hardware fitted on this pod ---------------------------------------------------------------------------
#ifndef AURI_HAS_BATTERY_DIVIDER
#define AURI_HAS_BATTERY_DIVIDER 0  // 1 when the 100k/100k divider is on D1; otherwise battery is reported unavailable
#endif
#ifndef AURI_BNO_RST_WIRED
#define AURI_BNO_RST_WIRED 0  // 1 when BNO085 RST goes to D3 (lets firmware hard-reset a hung IMU)
#endif
#ifndef AURI_TEST_PATTERN
#define AURI_TEST_PATTERN 0  // 1: with no IMU present, send valid=0 packets on sensor 15 to test the BLE link only
#endif

// ---- pins -----------------------------------------------------------------------------------------------------------
#if CONFIG_IDF_TARGET_ESP32C3
static const char* const CHIP = "ESP32-C3";
static const int PIN_SDA = 6;  // D4
static const int PIN_SCL = 7;  // D5
static const int PIN_BAT = 3;  // D1 (ADC1)
static const int PIN_INT = 4;  // D2
static const int PIN_RST = 5;  // D3
#elif CONFIG_IDF_TARGET_ESP32S3
static const char* const CHIP = "ESP32-S3";
static const int PIN_SDA = 5;  // D4
static const int PIN_SCL = 6;  // D5
static const int PIN_BAT = 2;  // D1
static const int PIN_INT = 3;  // D2
static const int PIN_RST = 4;  // D3
#else
#error "Auri strap firmware supports the XIAO ESP32-C3 and ESP32-S3"
#endif

// Override for a board wired off-spec, e.g. -DAURI_PIN_SDA=7 -DAURI_PIN_SCL=21. Never use GPIO21 (D6) for I2C on the
// C3: it is UART0 TX, the core claims it at boot and the BNO then fails to answer (seen on the first bench unit, which
// was re-soldered to D4/D5 on 2026-10-29).
#ifdef AURI_PIN_SDA
#define I2C_SDA AURI_PIN_SDA
#else
#define I2C_SDA PIN_SDA
#endif
#ifdef AURI_PIN_SCL
#define I2C_SCL AURI_PIN_SCL
#else
#define I2C_SCL PIN_SCL
#endif

// Handoff §6.2 is 400 kHz. The first C3 bench cable (SCL on GPIO21) often does not ACK at 400;
// pass -DAURI_I2C_HZ=100000 for that board. Other builds stay at 400.
#ifndef AURI_I2C_HZ
#define AURI_I2C_HZ 400000
#endif
static const uint32_t I2C_HZ = AURI_I2C_HZ;

// ---- sensors per unit (handoff §6.2 addresses) ---------------------------------------------------------------------
struct ImuSlot {
  uint8_t sensorId;
  uint8_t address;
};

#if AURI_UNIT == 1
static const char* const DEVICE_NAME = "AURI-ARM";
static const ImuSlot IMU_SLOTS[] = {{auri::SENSOR_UPPER_ARM, 0x4A}, {auri::SENSOR_FOREARM, 0x4B}};
static const bool UNIT_HAS_HAPTICS = true;
#elif AURI_UNIT == 2
static const char* const DEVICE_NAME = "AURI-TRUNK";
static const ImuSlot IMU_SLOTS[] = {{auri::SENSOR_TRUNK, 0x4A}};
static const bool UNIT_HAS_HAPTICS = false;
#else
#error "AURI_UNIT must be 1 (arm) or 2 (trunk)"
#endif
static const size_t IMU_COUNT = sizeof(IMU_SLOTS) / sizeof(IMU_SLOTS[0]);

static const uint8_t FW_MAJOR = 0, FW_MINOR = 1, FW_PATCH = 0;
