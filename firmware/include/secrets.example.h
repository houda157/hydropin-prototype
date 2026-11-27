#pragma once
// Copy to secrets.h (gitignored) and fill in your values.
#define WIFI_SSID "your-ssid"
#define WIFI_PASSWORD "your-password"
#define MQTT_HOST "192.168.1.10"
#define MQTT_PORT 1883
// Optional: protects over-the-air flashing. If set, export the same value as
// HYDROPIN_OTA_PASSWORD before `pio run -e esp32dev_ota -t upload`.
#define OTA_PASSWORD "change-me"
