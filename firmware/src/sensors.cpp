#include "sensors.h"

#include <Adafruit_ADS1X15.h>
#include <Wire.h>

#include "config.h"

volatile uint32_t g_pulses_main = 0;
volatile uint32_t g_pulses_l1 = 0;
volatile uint32_t g_pulses_l2 = 0;
volatile uint32_t g_pulses_l3 = 0;

static Adafruit_ADS1115 s_ads;
static uint32_t s_last_counts[4] = {0, 0, 0, 0};
static uint32_t s_slots[4][FLOW_WINDOW_SLOTS] = {};
static uint8_t s_slot = 0;

static void IRAM_ATTR isr_main() { g_pulses_main++; }
static void IRAM_ATTR isr_l1() { g_pulses_l1++; }
static void IRAM_ATTR isr_l2() { g_pulses_l2++; }
static void IRAM_ATTR isr_l3() { g_pulses_l3++; }

static void attach_flow(uint8_t pin, void (*isr)()) {
    pinMode(pin, INPUT);
    attachInterrupt(digitalPinToInterrupt(pin), isr, FALLING);
}

void sensors_begin() {
    attach_flow(PIN_FLOW_MAIN, isr_main);
    attach_flow(PIN_FLOW_L1, isr_l1);
    attach_flow(PIN_FLOW_L2, isr_l2);
    attach_flow(PIN_FLOW_L3, isr_l3);

    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    if (!s_ads.begin(ADS_ADDR, &Wire)) {
        Serial.println("[sensors] ADS1115 not found at 0x48");
    }
    s_ads.setGain(GAIN_ONE);  // +/-4.096 V
    s_ads.setDataRate(RATE_ADS1115_128SPS);
}

static float pulses_to_lpm(uint32_t pulses, float window_s) {
    float raw = (pulses / window_s) / FLOW_PULSES_PER_LPM;
    return raw * FLOW_GAIN;
}

SensorSnapshot sensors_read() {
    uint32_t counts[4];
    noInterrupts();
    counts[0] = g_pulses_main;
    counts[1] = g_pulses_l1;
    counts[2] = g_pulses_l2;
    counts[3] = g_pulses_l3;
    interrupts();

    for (uint8_t i = 0; i < 4; i++) {
        uint32_t delta = counts[i] - s_last_counts[i];
        s_last_counts[i] = counts[i];
        s_slots[i][s_slot] = delta;
    }
    s_slot = (s_slot + 1) % FLOW_WINDOW_SLOTS;

    uint32_t sums[4] = {0, 0, 0, 0};
    for (uint8_t i = 0; i < 4; i++) {
        for (uint8_t k = 0; k < FLOW_WINDOW_SLOTS; k++) sums[i] += s_slots[i][k];
    }

    const float window_s = FLOW_WINDOW_MS / 1000.0f;
    SensorSnapshot snap;
    snap.pulses_main = sums[0];
    snap.pulses_l1 = sums[1];
    snap.pulses_l2 = sums[2];
    snap.pulses_l3 = sums[3];
    snap.flow_main_lpm = pulses_to_lpm(sums[0], window_s);
    snap.flow_l1_lpm = pulses_to_lpm(sums[1], window_s);
    snap.flow_l2_lpm = pulses_to_lpm(sums[2], window_s);
    snap.flow_l3_lpm = pulses_to_lpm(sums[3], window_s);

    int32_t acc = 0;
    for (uint8_t i = 0; i < PRESSURE_OVERSAMPLE; i++) acc += s_ads.readADC_SingleEnded(ADS_CHANNEL);
    int16_t adc = (int16_t)(acc / PRESSURE_OVERSAMPLE);
    float sensor_volts = (adc / ADS_COUNTS) * ADS_VOLTAGE_RANGE * PRESSURE_DIVIDER;
    float bar = sensor_volts * PRESSURE_GAIN + PRESSURE_OFFSET_BAR;
    snap.pressure_adc = adc;
    snap.clipped = (bar < 0.0f) || (bar > PRESSURE_MAX_BAR) || (sensor_volts > 5.0f);
    snap.pressure_bar = constrain(bar, 0.0f, PRESSURE_MAX_BAR);

    return snap;
}
