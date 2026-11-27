#pragma once
#include <Arduino.h>

// Print sink that mirrors everything to USB Serial and to one telnet client
// on port 23. The last LOG_HISTORY bytes are replayed on connect so boot
// messages are visible even if you attach late.
//   nc 10.48.156.208 23
//   pio device monitor -e esp32dev_ota
class RemoteLog : public Print {
public:
    size_t write(uint8_t c) override;
    size_t write(const uint8_t* buf, size_t n) override;
};

extern RemoteLog Log;

void remote_log_begin();   // call once WiFi is up
void remote_log_loop();    // call every loop
