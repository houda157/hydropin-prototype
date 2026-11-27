#include <Arduino.h>
#include <ArduinoJson.h>

#include "config.h"
#include "network.h"
#include "sensors.h"

static uint32_t s_seq = 0;
static uint32_t s_last_publish = 0;

static void publish_snapshot(const SensorSnapshot& s) {
    JsonDocument doc;
    doc["schema"] = SCHEMA_VERSION;
    doc["device"] = DEVICE_ID;
    doc["seq"] = s_seq;
    char ts[32];
    iso8601_now(ts, sizeof(ts));
    doc["ts"] = ts;
    doc["ts_device_ms"] = millis();
    doc["label"] = "none";
    doc["scenario"] = "live";

    JsonObject raw = doc["raw"].to<JsonObject>();
    raw["flow_main_pulses"] = s.pulses_main;
    raw["flow_l1_pulses"] = 0;
    raw["flow_l2_pulses"] = 0;
    raw["flow_l3_pulses"] = 0;
    raw["pressure_adc"] = s.pressure_adc;
    raw["pressure_b_adc"] = s.pressure_b_adc;

    JsonObject values = doc["values"].to<JsonObject>();
    values["flow_main_lpm"] = roundf(s.flow_main_lpm * 100.0f) / 100.0f;
    values["flow_l1_lpm"] = 0.0f;
    values["flow_l2_lpm"] = 0.0f;
    values["flow_l3_lpm"] = 0.0f;
    // 4 decimals: one ADC count is ~0.2 mbar; 0.01 bar rounding looked like a stuck sensor.
    // (The backend recomputes bar from raw ADC anyway, so older firmware still works.)
    values["pressure_bar"] = roundf(s.pressure_bar * 10000.0f) / 10000.0f;
    values["pressure_b_bar"] = roundf(s.pressure_b_bar * 10000.0f) / 10000.0f;

    JsonObject quality = doc["quality"].to<JsonObject>();
    quality["dropout"] = false;
    quality["ripple"] = false;
    quality["clipped"] = s.clipped;

    char payload[768];
    size_t needed = measureJson(doc);
    if (needed >= sizeof(payload)) {
        Serial.println("[main] JSON too large, dropping sample");
        return;
    }
    serializeJson(doc, payload, sizeof(payload));
    // One JSON line per frame on USB too: tools/serial_bridge.py forwards it if WiFi fails.
    Serial.println(payload);
    if (!network_publish(payload)) {
        Serial.println("[main] publish failed (mqtt down)");
    }
    s_seq++;
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("[main] hydropin bench node");
    sensors_begin();
    network_begin();
}

void loop() {
    network_loop();
    uint32_t now = millis();
    if (now - s_last_publish < PUBLISH_PERIOD_MS) {
        delay(2);
        return;
    }
    s_last_publish = now;
    SensorSnapshot snap = sensors_read();
    publish_snapshot(snap);
}
