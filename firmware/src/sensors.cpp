#include "sensors.h"

#include <Adafruit_ADS1X15.h>
#include <Wire.h>

#include "config.h"
#include "remote_log.h"

volatile uint32_t g_pulses_main = 0;

static Adafruit_ADS1115 s_ads;
static uint32_t s_last_count = 0;
static uint32_t s_slots[FLOW_WINDOW_SLOTS] = {};
static uint8_t s_slot = 0;
static bool s_ads_ok = false;
static uint32_t s_last_ads_probe = 0;
static uint32_t s_last_ads_warn = 0;
static char s_i2c_summary[160] = "not scanned";
static char s_wire_test[64] = "";

// Before Wire.begin(): weakly pull SDA/SCL DOWN (~45k). If the jumpers reach a
// breakout with its own 10k pull-ups the pin still reads HIGH; an open wire
// (or a bare chip with no pull-ups) reads LOW.
static void wire_continuity_test() {
    pinMode(PIN_I2C_SDA, INPUT_PULLDOWN);
    pinMode(PIN_I2C_SCL, INPUT_PULLDOWN);
    delay(5);
    bool sda = digitalRead(PIN_I2C_SDA);
    bool scl = digitalRead(PIN_I2C_SCL);
    snprintf(s_wire_test, sizeof(s_wire_test), "pulldown test SDA=%s SCL=%s",
             sda ? "HIGH(wired)" : "LOW(open?)", scl ? "HIGH(wired)" : "LOW(open?)");
    pinMode(PIN_I2C_SDA, INPUT);
    pinMode(PIN_I2C_SCL, INPUT);
}

static void IRAM_ATTR isr_main() { g_pulses_main = g_pulses_main + 1; }

static void attach_flow(uint8_t pin, void (*isr)()) {
    pinMode(pin, INPUT);
    attachInterrupt(digitalPinToInterrupt(pin), isr, FALLING);
}

static void wire_continuity_test();
static void i2c_scan(bool print);

// Adafruit's readADC_SingleEnded() spins forever waiting for a conversion if
// the chip is absent, so never call it unless begin() succeeded.
static void ads_probe() {
    s_last_ads_probe = millis();
    s_ads_ok = s_ads.begin(ADS_ADDR, &Wire);
    if (!s_ads_ok) {
        // Re-run the wiring diagnostics on every retry so wiggling wires shows
        // up live. Print on change, otherwise every 30 s.
        char prev[sizeof(s_i2c_summary)];
        strncpy(prev, s_i2c_summary, sizeof(prev));
        Wire.end();
        wire_continuity_test();
        Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
        i2c_scan(false);
        s_ads_ok = s_ads.begin(ADS_ADDR, &Wire);
        bool changed = strcmp(prev, s_i2c_summary) != 0;
        if (!s_ads_ok && (changed || s_last_ads_warn == 0 || millis() - s_last_ads_warn > 30000)) {
            s_last_ads_warn = millis();
            Log.printf("[sensors] ADS1115 not found at 0x48%s | %s\n", changed ? " (CHANGED)" : "", s_i2c_summary);
        }
        if (!s_ads_ok) return;
    }
    s_ads.setGain(GAIN_ONE);  // +/-4.096 V
    s_ads.setDataRate(RATE_ADS1115_128SPS);
    Log.println("[sensors] ADS1115 ok");
}

// Boot-time wiring diagnostic: idle line levels + every address that ACKs.
// Result is kept in s_i2c_summary and repeated with every "not found" warning.
// err codes: 2 = address NACK (nothing there), 5 = bus timeout (line held low).
static void i2c_scan(bool print) {
    bool sda = digitalRead(PIN_I2C_SDA);
    bool scl = digitalRead(PIN_I2C_SCL);
    char found[48] = "";
    size_t used = 0;
    uint8_t err_0x48 = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        uint8_t err = Wire.endTransmission();
        if (addr == ADS_ADDR) err_0x48 = err;
        if (err == 0 && used + 6 < sizeof(found)) {
            used += snprintf(found + used, sizeof(found) - used, " 0x%02X", addr);
        }
    }
    snprintf(s_i2c_summary, sizeof(s_i2c_summary), "i2c: %s | idle SDA=%s SCL=%s 0x48err=%u found:%s",
             s_wire_test, sda ? "HIGH" : "LOW", scl ? "HIGH" : "LOW", err_0x48, used ? found : " none");
    if (print) Log.printf("[%s]\n", s_i2c_summary);
}

void sensors_begin() {
    attach_flow(PIN_FLOW_MAIN, isr_main);

    wire_continuity_test();
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    i2c_scan(true);
    ads_probe();
}

static float pulses_to_lpm(uint32_t pulses, float window_s) {
    float raw = (pulses / window_s) / FLOW_PULSES_PER_LPM;
    return raw * FLOW_GAIN;
}

static int16_t read_adc(uint8_t channel) {
    if (!s_ads_ok) return 0;
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

    if (!s_ads_ok && millis() - s_last_ads_probe > 5000) ads_probe();

    // Flow diagnostic every 5 s: total ISR pulses since boot + GPIO27 level.
    // HIGH should be >2.5 V; if it always reads LOW the sensor output never
    // reaches a valid logic high through the R5/R6 divider.
    static uint32_t s_last_flow_log = 0;
    if (millis() - s_last_flow_log > 5000) {
        s_last_flow_log = millis();
        Log.printf("[flow] GPIO%d=%s total_pulses=%lu window=%lu\n", PIN_FLOW_MAIN,
                   digitalRead(PIN_FLOW_MAIN) ? "HIGH" : "LOW", (unsigned long)count,
                   (unsigned long)sum);
    }

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
