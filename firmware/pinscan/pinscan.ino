// Read-only search for a STEMMA device on the wrong XIAO ESP32-C3 pads.
// One pass over every ordered SDA/SCL pair, then again every 10 s.
// Wire is the only thing that drives a pin.
#if !defined(CONFIG_IDF_TARGET_ESP32C3)
#error "pinscan is ESP32-C3 only"
#endif

#include <Wire.h>

struct Pad {
  const char *name;
  int gpio;
};

// Seeed XIAO ESP32-C3 labels. D0/D8/D9 are strapping pins; they are included because the cable may be on them.
static const Pad PADS[] = {
    {"D0", 2}, {"D1", 3},  {"D2", 4},  {"D3", 5}, {"D4", 6}, {"D5", 7},
    {"D6", 21}, {"D7", 20}, {"D8", 8}, {"D9", 9}, {"D10", 10},
};
static const size_t NPAD = sizeof(PADS) / sizeof(PADS[0]);

static const uint8_t HINTS[] = {0x4A, 0x4B, 0x28, 0x29, 0x5A};

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

static void found(const Pad &sda, const Pad &scl, uint8_t addr) {
  Serial.printf("FOUND sda=%s (GPIO%d) scl=%s (GPIO%d) addr 0x%02X\n", sda.name, sda.gpio, scl.name, scl.gpio, addr);
}

static void scanPair(const Pad &sda, const Pad &scl) {
  if (wireUp) Wire.end();
  Wire.begin(sda.gpio, scl.gpio, 100000);
  Wire.setTimeOut(20);  // default 50 ms; a stuck pad must not eat the whole pass
  wireUp = true;

  bool hinted = false;
  for (size_t i = 0; i < sizeof(HINTS); i++) {
    if (ack(HINTS[i])) hinted = true;
  }
  if (!hinted) return;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    if (ack(addr)) found(sda, scl, addr);
  }
}

static void pass() {
  Serial.println("--- pinscan pass ---");
  printLevels();
  for (size_t s = 0; s < NPAD; s++) {
    for (size_t c = 0; c < NPAD; c++) {
      if (s == c) continue;
      scanPair(PADS[s], PADS[c]);
    }
  }
  if (wireUp) {
    Wire.end();
    wireUp = false;
  }
  Serial.println("--- pass done ---");
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);
  delay(200);
  pass();
}

void loop() {
  delay(10000);
  pass();
}
