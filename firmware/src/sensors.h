#pragma once
#include <Arduino.h>

struct SensorSnapshot {
    float flow_main_lpm;
    float flow_l1_lpm;
    float flow_l2_lpm;
    float flow_l3_lpm;
    float pressure_bar;
    uint32_t pulses_main;
    uint32_t pulses_l1;
    uint32_t pulses_l2;
    uint32_t pulses_l3;
    int16_t pressure_adc;
    bool clipped;
};

void sensors_begin();
SensorSnapshot sensors_read();

extern volatile uint32_t g_pulses_main;
extern volatile uint32_t g_pulses_l1;
extern volatile uint32_t g_pulses_l2;
extern volatile uint32_t g_pulses_l3;
