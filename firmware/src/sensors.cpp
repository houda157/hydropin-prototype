#include "sensors.h"

#include <Adafruit_ADS1X15.h>
#include <Wire.h>

#include "config.h"

volatile uint32_t g_pulses_main = 0;

static Adafruit_ADS1115 s_ads;
static uint32_t s_last_count = 0;
static uint32_t s_slots[FLOW_WINDOW_SLOTS] = {};
static uint8_t s_slot = 0;

static void IRAM_ATTR isr_main() { g_pulses_main++; }

static void attach_flow(uint8_t pin, void (*isr)()) {
    pinMode(pin, INPUT);
    attachInterrupt(digitalPinToInterrupt(pin), isr, FALLING);
}

void sensors_begin() {
    attach_flow(PIN_FLOW_MAIN, isr_main);

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

static int16_t read_adc(uint8_t channel) {
    int32_t acc = 0;
    for (uint8_t i = 0; i < PRESSURE_OVERSAMPLE; i++) {
        acc += s_ads.readADC_SingleEnded(channel);
    }
    return (int16_t)(acc / PRESSURE_OVERSAMPLE);
}

static float adc_to_bar(int16_t adc, float divider, float gain, float offset) {
    float sensor_volts = (adc / ADS_COUNTS) * ADS_VOLTAGE_RANGE * divider;
    return sensor_volts * gain + offset;
}

SensorSnapshot sensors_read() {
    uint32_t count;
    noInterrupts();
    count = g_pulses_main;
    interrupts();

    uint32_t delta = count - s_last_count;
    s_last_count = count;
    s_slots[s_slot] = delta;
    s_slot = (s_slot + 1) % FLOW_WINDOW_SLOTS;

    uint32_t sum = 0;
    for (uint8_t k = 0; k < FLOW_WINDOW_SLOTS; k++) sum += s_slots[k];

    const float window_s = FLOW_WINDOW_MS / 1000.0f;

    int16_t adc_pt1 = read_adc(ADS_CHANNEL_PT1);
    int16_t adc_pt2 = read_adc(ADS_CHANNEL_PT2);
    float bar_pt1 = adc_to_bar(adc_pt1, PRESSURE_DIVIDER, PRESSURE_GAIN, PRESSURE_OFFSET_BAR);
    float bar_pt2 = adc_to_bar(
        adc_pt2,
        PRESSURE_B_DIVIDER,
        PRESSURE_B_GAIN,
        PRESSURE_B_OFFSET_BAR
    );

    SensorSnapshot snap;
    snap.pulses_main = sum;
    snap.flow_main_lpm = pulses_to_lpm(sum, window_s);
    snap.pressure_adc = adc_pt1;
    snap.pressure_b_adc = adc_pt2;
    snap.pressure_bar = constrain(bar_pt1, PRESSURE_MIN_BAR, PRESSURE_MAX_BAR);
    snap.pressure_b_bar = constrain(bar_pt2, PRESSURE_B_MIN_BAR, PRESSURE_B_MAX_BAR);
    snap.clipped =
        (bar_pt1 < PRESSURE_MIN_BAR) || (bar_pt1 > PRESSURE_MAX_BAR) ||
        (bar_pt2 < PRESSURE_B_MIN_BAR) || (bar_pt2 > PRESSURE_B_MAX_BAR) ||
        (adc_pt1 >= 32760) || (adc_pt2 >= 32760);

    return snap;
}
