#pragma once
#include <Arduino.h>

// Keep these in sync with hydropin/config.py (tests/test_contract.py guards it).
#define SCHEMA_VERSION "1.0"
#define DEVICE_ID "esp32-bench-01"

// ---- pins -----------------------------------------------------------------
// 34/35 are input-only. For a 5 V push-pull flow sensor use a divider
// (10k series / 18k shunt) and NO pull-up. For an open-collector sensor use a
// 10k pull-up to 3.3 V and no divider. Never feed 5 V straight into an ESP32.
#define PIN_FLOW_MAIN 34
#define PIN_FLOW_L1 35
#define PIN_FLOW_L2 32
#define PIN_FLOW_L3 33
#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22
#define ADS_ADDR 0x48
#define ADS_CHANNEL 0

// ---- timing ---------------------------------------------------------------
static const uint32_t PUBLISH_PERIOD_MS = 500;   // 2 Hz
static const uint32_t FLOW_WINDOW_MS = 2000;     // 2 s sliding pulse window
static const uint8_t FLOW_WINDOW_SLOTS = 4;      // 4 x 500 ms
static_assert(FLOW_WINDOW_SLOTS == FLOW_WINDOW_MS / PUBLISH_PERIOD_MS, "window slots mismatch");

// ---- flow (YF-S201 class) -------------------------------------------------
static const float FLOW_K_PULSES_PER_LITRE = 450.0f;
static const float FLOW_PULSES_PER_LPM = FLOW_K_PULSES_PER_LITRE / 60.0f;  // 7.5
static const float FLOW_GAIN = 1.5f;                                       // "flow * 3/2"

// ---- pressure (0..5 V sensor -> 3.2 divider -> ADS1115 +/-4.096 V) --------
// Divider: 22k series + 10k shunt -> V_ads = V_sensor * 10/32 = V_sensor/3.2.
static const float ADS_VOLTAGE_RANGE = 4.096f;
static const float ADS_COUNTS = 32767.0f;
static const float PRESSURE_DIVIDER = 3.2f;
static const float PRESSURE_GAIN = 3.0f;                                   // "pressure * 3"
static const float PRESSURE_OFFSET_BAR = 0.0f;                             // fit on bench

// ---- sanity ---------------------------------------------------------------
static const float FLOW_MAX_LPM = 60.0f;
// 0..5 V * 3.0 bar/V = 15 bar full scale; 16 bar cannot be represented.
static const float PRESSURE_MAX_BAR = 15.0f;
static const uint8_t PRESSURE_OVERSAMPLE = 8;
