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
    raw["flow_l1_pulses"] = s.pulses_l1;
    raw["flow_l2_pulses"] = s.pulses_l2;
    raw["flow_l3_pulses"] = s.pulses_l3;
    raw["pressure_adc"] = s.pressure_adc;

    JsonObject values = doc["values"].to<JsonObject>();
    values["flow_main_lpm"] = roundf(s.flow_main_lpm * 100.0f) / 100.0f;
    values["flow_l1_lpm"] = roundf(s.flow_l1_lpm * 100.0f) / 100.0f;
    values["flow_l2_lpm"] = roundf(s.flow_l2_lpm * 100.0f) / 100.0f;
    values["flow_l3_lpm"] = roundf(s.flow_l3_lpm * 100.0f) / 100.0f;
    values["pressure_bar"] = roundf(s.pressure_bar * 100.0f) / 100.0f;

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
