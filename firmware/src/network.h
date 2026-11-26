#pragma once
#include <Arduino.h>

bool network_begin();
void network_loop();
bool network_publish(const char* payload);
bool network_connected();
void iso8601_now(char* out, size_t n);
