#include "remote_log.h"

#include <WiFi.h>

static const uint16_t LOG_PORT = 23;
static const size_t LOG_HISTORY = 2048;

RemoteLog Log;

static WiFiServer s_server(LOG_PORT);
static WiFiClient s_client;
static bool s_started = false;
static char s_hist[LOG_HISTORY];
static size_t s_head = 0;   // next write position
static bool s_wrapped = false;

static void hist_put(const uint8_t* buf, size_t n) {
    for (size_t i = 0; i < n; i++) {
        s_hist[s_head++] = (char)buf[i];
        if (s_head == LOG_HISTORY) {
            s_head = 0;
            s_wrapped = true;
        }
    }
}

size_t RemoteLog::write(uint8_t c) { return write(&c, 1); }

size_t RemoteLog::write(const uint8_t* buf, size_t n) {
    Serial.write(buf, n);
    hist_put(buf, n);
    if (s_client && s_client.connected()) s_client.write(buf, n);
    return n;
}

void remote_log_begin() {
    if (s_started) return;
    s_server.begin();
    s_server.setNoDelay(true);
    s_started = true;
}

void remote_log_loop() {
    if (!s_started || !s_server.hasClient()) return;
    WiFiClient incoming = s_server.available();
    if (s_client) s_client.stop();   // newest client wins
    s_client = incoming;
    s_client.setNoDelay(true);
    s_client.print("\r\n--- hydropin remote log (history follows) ---\r\n");
    if (s_wrapped) s_client.write((const uint8_t*)s_hist + s_head, LOG_HISTORY - s_head);
    s_client.write((const uint8_t*)s_hist, s_head);
    s_client.print("--- live ---\r\n");
}
