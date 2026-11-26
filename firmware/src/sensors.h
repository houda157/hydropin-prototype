#pragma once
#include <Arduino.h>

struct SensorSnapshot {
    float flow_main_lpm;
    float pressure_bar;     // PT1, branch A, 0..6 bar
    float pressure_b_bar;   // PT2, branch B, -1..1.6 bar
    uint32_t pulses_main;
    int16_t pressure_adc;
    int16_t pressure_b_adc;
    bool clipped;
};

void sensors_begin();
SensorSnapshot sensors_read();

extern volatile uint32_t g_pulses_main;
