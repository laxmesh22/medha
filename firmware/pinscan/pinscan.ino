// Read-only search for a BNO on the XIAO pads. One sketch, C3 or S3.
// Two passes, each at 100 kHz then 400 kHz. Wire is the only thing that drives a pin.
#include <Wire.h>

struct Pad {
  const char *name;
  int gpio;
};

#if defined(CONFIG_IDF_TARGET_ESP32C3)
static const Pad PADS[] = {
    {"D0", 2}, {"D1", 3}, {"D2", 4}, {"D3", 5}, {"D4", 6}, {"D5", 7},
    {"D6", 21}, {"D7", 20}, {"D8", 8}, {"D9", 9}, {"D10", 10},
};
static const int PIN_BAT = 3;  // D1
#elif defined(CONFIG_IDF_TARGET_ESP32S3)
// Seeed XIAO ESP32-S3. D4/D5 are GPIO5/GPIO6, the same labels board.h uses for SDA/SCL.
static const Pad PADS[] = {
    {"D0", 1}, {"D1", 2}, {"D2", 3}, {"D3", 4}, {"D4", 5}, {"D5", 6},
    {"D6", 43}, {"D7", 44}, {"D8", 7}, {"D9", 8}, {"D10", 9},
};
static const int PIN_BAT = 2;  // D1
#else
#error "pinscan supports the XIAO ESP32-C3 and ESP32-S3"
#endif

static const size_t NPAD = sizeof(PADS) / sizeof(PADS[0]);
static const uint8_t HINTS[] = {0x4A, 0x4B, 0x28, 0x29, 0x5A};
static const uint32_t SPEEDS[] = {100000, 400000};
static bool wireUp = false;

static bool ack(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

static void printLevels() {
  Serial.println("--- pad levels (input, pulls off) ---");
  for (size_t i = 0; i < NPAD; i++) {
    pinMode(PADS[i].gpio, INPUT);
    int first = digitalRead(PADS[i].gpio);
    bool same = true;
    for (int n = 0; n < 15; n++) {
      delayMicroseconds(50);
      if (digitalRead(PADS[i].gpio) != first) same = false;
    }
    Serial.printf("pad %s GPIO%d level %s\n", PADS[i].name, PADS[i].gpio, same ? (first ? "1" : "0") : "changing");
  }
}

static void printSupply() {
  // D1 is the battery-divider pin. This board has no pin wired to 3V3 for an ADC reading.
  int raw = analogRead(PIN_BAT);
  int mv = analogReadMilliVolts(PIN_BAT);
  Serial.printf("supply battery-pin D1 GPIO%d adc %d mV %d\n", PIN_BAT, raw, mv);
  Serial.println("supply 3V3 adc unavailable (no sense pin)");
}

// SHTP product-id request. Returns the SH-2 part number, or 0 if the part does not answer.
static uint32_t productId(uint8_t addr) {
  uint8_t seq[6] = {0};
  auto send = [&](uint8_t channel, const uint8_t *data, uint8_t len) -> bool {
    uint16_t total = len + 4;
    Wire.beginTransmission(addr);
    Wire.write((uint8_t)(total & 0xFF));
    Wire.write((uint8_t)(total >> 8));
    Wire.write(channel);
    Wire.write(seq[channel]++);
    for (uint8_t i = 0; i < len; i++) Wire.write(data[i]);
    return Wire.endTransmission() == 0;
  };
  auto receive = [&](uint8_t &channel, uint8_t *buf, int cap) -> int {
    if (Wire.requestFrom(addr, (uint8_t)4) != 4) return -1;
    uint8_t h[4];
    for (int i = 0; i < 4; i++) h[i] = Wire.read();
    uint16_t len = (uint16_t)(h[0] | (h[1] << 8)) & 0x7FFF;
    if (len <= 4 || len == 0x7FFF) return 0;
    channel = h[2];
    int payload = len - 4;
    int got = 0;
    while (got < payload && got < cap) {
      int chunk = payload - got;
      if (chunk > 32) chunk = 32;
      if (Wire.requestFrom(addr, (uint8_t)(chunk + 4)) != chunk + 4) return -1;
      for (int i = 0; i < 4; i++) Wire.read();
      for (int i = 0; i < chunk && got < cap; i++) buf[got++] = Wire.read();
    }
    return got;
  };

  const uint8_t resetCmd[1] = {1};
  send(1, resetCmd, 1);
  memset(seq, 0, sizeof(seq));
  uint32_t t0 = millis();
  uint8_t buf[48];
  while (millis() - t0 < 500) {
    uint8_t ch;
    int n = receive(ch, buf, sizeof(buf));
    if (n <= 0) delay(10);
  }
  const uint8_t prodReq[2] = {0xF9, 0};
  for (int attempt = 0; attempt < 3; attempt++) {
    if (!send(2, prodReq, 2)) {
      delay(40);
      continue;
    }
    t0 = millis();
    while (millis() - t0 < 250) {
      uint8_t ch;
      int n = receive(ch, buf, sizeof(buf));
      if (n >= 14 && ch == 2 && buf[0] == 0xF8) {
        return (uint32_t)buf[4] | ((uint32_t)buf[5] << 8) | ((uint32_t)buf[6] << 16) | ((uint32_t)buf[7] << 24);
      }
      if (n <= 0) delay(5);
    }
  }
  return 0;
}

static void found(const Pad &sda, const Pad &scl, uint32_t hz, uint8_t addr) {
  uint32_t part = 0;
  if (addr == 0x4A || addr == 0x4B) part = productId(addr);
  Serial.printf("FOUND sda=%s (GPIO%d) scl=%s (GPIO%d) hz %lu addr 0x%02X part %lu\n",
                sda.name, sda.gpio, scl.name, scl.gpio, (unsigned long)hz, addr, (unsigned long)part);
}

static void scanPair(const Pad &sda, const Pad &scl, uint32_t hz) {
  if (wireUp) Wire.end();
  Wire.begin(sda.gpio, scl.gpio, hz);
  Wire.setTimeOut(10);
  wireUp = true;
  bool hinted = false;
  for (size_t i = 0; i < sizeof(HINTS); i++) {
    if (ack(HINTS[i])) hinted = true;
  }
  if (!hinted) return;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    if (ack(addr)) found(sda, scl, hz, addr);
  }
}

static void pass(int n) {
  Serial.printf("--- pinscan pass %d ---\n", n);
  if (n == 1) {
    printLevels();
    printSupply();
  }
  for (uint32_t hz : SPEEDS) {
    Serial.printf("--- speed %lu ---\n", (unsigned long)hz);
    for (size_t s = 0; s < NPAD; s++) {
      for (size_t c = 0; c < NPAD; c++) {
        if (s == c) continue;
        scanPair(PADS[s], PADS[c], hz);
      }
    }
  }
  if (wireUp) {
    Wire.end();
    wireUp = false;
  }
  Serial.printf("--- pass %d done ---\n", n);
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);
  delay(200);
  Serial.println("pinscan S3-or-C3");
  pass(1);
  pass(2);
  Serial.println("--- pinscan finished ---");
}

void loop() { delay(1000); }
