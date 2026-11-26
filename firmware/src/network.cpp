#include "network.h"

#include <PubSubClient.h>
#include <WiFi.h>
#include <sys/time.h>
#include <time.h>

#include "config.h"
#include "secrets.h"

static WiFiClient s_wifi;
static PubSubClient s_mqtt(s_wifi);
static char s_telemetry_topic[96];
static char s_status_topic[96];
static uint32_t s_last_wifi_attempt = 0;
static uint32_t s_last_mqtt_attempt = 0;

static void build_topics() {
    snprintf(s_telemetry_topic, sizeof(s_telemetry_topic), "hydropin/bench/%s/telemetry", DEVICE_ID);
    snprintf(s_status_topic, sizeof(s_status_topic), "hydropin/bench/%s/status", DEVICE_ID);
}

static void mqtt_connect() {
    Serial.print("[mqtt] connecting...");
    bool ok = s_mqtt.connect(DEVICE_ID, nullptr, nullptr, s_status_topic, 1, true, "offline");
    if (ok) {
        s_mqtt.publish(s_status_topic, "online", true);
        Serial.println("ok");
    } else {
        Serial.printf("failed rc=%d\n", s_mqtt.state());
    }
}

bool network_begin() {
    build_topics();
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("[wifi] connecting");
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
        Serial.print("[wifi] ip ");
        Serial.println(WiFi.localIP());
    } else {
        Serial.println("[wifi] not connected yet; will retry in loop");
    }

    configTime(0, 0, "pool.ntp.org", "time.google.com");
    s_mqtt.setServer(MQTT_HOST, MQTT_PORT);
    s_mqtt.setBufferSize(1024);
    s_mqtt.setKeepAlive(30);
    return WiFi.status() == WL_CONNECTED;
}

void network_loop() {
    if (WiFi.status() != WL_CONNECTED) {
        if (millis() - s_last_wifi_attempt > 5000) {
            s_last_wifi_attempt = millis();
            WiFi.reconnect();
        }
    } else if (!s_mqtt.connected()) {
        if (millis() - s_last_mqtt_attempt > 5000) {
            s_last_mqtt_attempt = millis();
            mqtt_connect();
        }
    }
    s_mqtt.loop();
}

bool network_publish(const char* payload) {
    if (!s_mqtt.connected()) return false;
    return s_mqtt.publish(s_telemetry_topic, payload, false);
}

bool network_connected() { return WiFi.status() == WL_CONNECTED && s_mqtt.connected(); }

void iso8601_now(char* out, size_t n) {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    if (tv.tv_sec < 1600000000) {
        snprintf(out, n, "1970-01-01T00:00:00.000Z");
        return;
    }
    struct tm tm_utc;
    gmtime_r(&tv.tv_sec, &tm_utc);
    snprintf(
        out,
        n,
        "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
        tm_utc.tm_year + 1900,
        tm_utc.tm_mon + 1,
        tm_utc.tm_mday,
        tm_utc.tm_hour,
        tm_utc.tm_min,
        tm_utc.tm_sec,
        (int)(tv.tv_usec / 1000)
    );
}
