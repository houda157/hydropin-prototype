#pragma once
#include <Arduino.h>

// Keep these in sync with hydropin/config.py (tests/test_contract.py guards it).
#define SCHEMA_VERSION "1.0"
#define DEVICE_ID "esp32-bench-01"

// ---- pins -----------------------------------------------------------------
// Rev 1 bench has ONE flow sensor (main) and TWO pressure sensors.
// Flow: 5 V pulse through R5=10k series + R6=20k shunt -> ~3.33 V on GPIO27.
// Do not add a pull-up on the divider node. Never feed 5 V into the ESP32.
#define PIN_FLOW_MAIN 27
#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22
#define ADS_ADDR 0x48
#define ADS_CHANNEL_PT1 0   // PT1, branch A, 0..6 bar
#define ADS_CHANNEL_PT2 1   // PT2, branch B, -1..1.6 bar

// ---- timing ---------------------------------------------------------------
static const uint32_t PUBLISH_PERIOD_MS = 500;   // 2 Hz
static const uint32_t FLOW_WINDOW_MS = 2000;     // 2 s sliding pulse window
static const uint8_t FLOW_WINDOW_SLOTS = 4;      // 4 x 500 ms
static_assert(FLOW_WINDOW_SLOTS == FLOW_WINDOW_MS / PUBLISH_PERIOD_MS, "window slots mismatch");

// ---- flow (YF-S201 class) -------------------------------------------------
static const float FLOW_K_PULSES_PER_LITRE = 450.0f;
static const float FLOW_PULSES_PER_LPM = FLOW_K_PULSES_PER_LITRE / 60.0f;  // 7.5
static const float FLOW_GAIN = 1.5f;                                       // "flow * 3/2"

// ---- pressure (0-10 V sensors -> 22k/10k divider -> ADS1115 gain=1) -------
// Divider: 22k series + 10k shunt -> V_ads = V_sensor * 10/32 = V_sensor/3.2.
// At 10 V the ADS pin sees 3.125 V, inside the +/-4.096 V range.
static const float ADS_VOLTAGE_RANGE = 4.096f;
static const float ADS_COUNTS = 32767.0f;

// PT1, branch A: 0..6 bar over 0-10 V.
static const float PRESSURE_DIVIDER = 3.2f;
static const float PRESSURE_GAIN = 0.6f;          // 6 bar / 10 V
static const float PRESSURE_OFFSET_BAR = 0.0f;
static const float PRESSURE_MIN_BAR = 0.0f;
static const float PRESSURE_MAX_BAR = 6.0f;

// PT2, branch B: -1..1.6 bar over 0-10 V.
static const float PRESSURE_B_DIVIDER = 3.2f;
static const float PRESSURE_B_GAIN = 0.26f;       // 2.6 bar / 10 V
static const float PRESSURE_B_OFFSET_BAR = -1.0f;
static const float PRESSURE_B_MIN_BAR = -1.0f;
static const float PRESSURE_B_MAX_BAR = 1.6f;

// ---- sanity ---------------------------------------------------------------
static const float FLOW_MAX_LPM = 60.0f;
static const uint8_t PRESSURE_OVERSAMPLE = 8;
