# Wiring (bench rev 1)

ESP32 DevKit + ADS1115 + **one** flow sensor (main) + **two** pressure sensors
(PT1 branch A, PT2 branch B). This is the wiring from
`hydropin_bench_wiring.pdf` rev 1.

## Pin map

| Signal | ESP32 pin | Notes |
|---|---|---|
| Flow main pulse | GPIO 27 | divider output, no pull-up |
| ADS1115 SDA | GPIO 21 | 4.7k pull-up to 3.3 V (module usually has it) |
| ADS1115 SCL | GPIO 22 | 4.7k pull-up to 3.3 V |
| ADS1115 ADDR | GND | address 0x48 |
| PT1 OUT (0..6 bar) | ADS A0 | through 20k/10k divider |
| PT2 OUT (-1..1.6 bar) | ADS A1 | through 20k/10k divider |
| Flow VCC | +5 V | do **not** power from 3.3 V |
| PT1/PT2 supply | +24 V | sensor electronics only; never into the divider/ADS |
| Logic ground | GND | ESP32, ADS1115, PT1/PT2 pin 2, flow black wire |
| Pump ground | GNDPWR | isolated from logic GND |

## Power

- **PS1 12 V 3 A** -> pump M1. Its negative is **GNDPWR**, isolated from logic
  GND to keep motor noise out of the ADC.
- **PS2 24 V 1 A** -> PT1/PT2 supply (+24 V, GND).
- **PS3 5 V USB** -> ESP32 + flow sensor.
- Tie all logic grounds (PS2 GND, PS3 GND, ESP32 GND, ADS GND, flow GND) at one
  point. Do **not** tie GNDPWR to logic GND.
- Flyback diode across the pump; never power the pump from the ESP32 5 V.

## Flow sensor (main)

Brass Hall flow sensor G1/2, 5 V supply, pulse output:

```
sensor OUT --- R5 10k ---+--- GPIO27
                         |
                         R6 20k (two 10k in series)
                         |
                         GND
```

`V_gpio = 5 V x 20 / (10 + 20) = 3.33 V`. This is safe for the ESP32 3.6 V
absolute maximum, but close; keep the divider exact and add 100 nF from GPIO27
to GND if pulses are noisy. **Do not add a pull-up** on the divider node.

The firmware counts pulses over a 2 s window and applies the provisional
`FLOW_GAIN = 1.5`. Calibrate `FLOW_K_PULSES_PER_LITRE` and `FLOW_GAIN` with a
measured volume before trusting L/min.

## Pressure sensors

Both are 0-10 V transmitters powered from +24 V, scaled by the same 20k/10k
divider:

```
sensor OUT --- R1/R3 20k ---+--- ADS A0/A1
                            |
                            R2/R4 10k
                            |
                            GND
```

`V_ads = V_sensor x 10 / (20 + 10) = V_sensor / 3.0`, so
`V_sensor = V_ads x 3.0`. At 10 V the ADS pin sees 3.333 V, inside the ADS1115
`GAIN_ONE` (+/-4.096 V) range. Add 100 nF from A0/A1 to GND.

### PT1 (branch A) — 0..6 bar
`bar = 0.0 + 0.6 x V_sensor` (6 bar over 10 V). With the divider:
`bar = 1.8 x V_ads`. Firmware constants:
`PRESSURE_DIVIDER=3.0`, `PRESSURE_GAIN=0.6`, `PRESSURE_OFFSET_BAR=0.0`.

### PT2 (branch B) — -1..1.6 bar
`bar = -1.0 + 0.26 x V_sensor` (2.6 bar span over 10 V). With the divider:
`bar = -1.0 + 0.78 x V_ads`. Firmware constants:
`PRESSURE_B_DIVIDER=3.0`, `PRESSURE_B_GAIN=0.26`,
`PRESSURE_B_OFFSET_BAR=-1.0`.

If PT2 is the **4-20 mA** version instead: pin 1 to +24 V, pin 2 through a 150 Ω
resistor to GND, tap ADC_A1 at pin 2, and remove R3/R4. That is a different
calibration and is not enabled in the current firmware.

## ADS1115 channel plan

| ADS channel | Use |
|---|---|
| A0 | PT1, branch A, 0..6 bar |
| A1 | PT2, branch B, -1..1.6 bar |
| A2/A3 | free (third sensor later) |

## Critical warnings

1. Never connect +24 V directly to R1-R4 or the ADS1115.
2. Never feed 5 V or 4.4 V directly into an ESP32 GPIO.
3. The current detector/ML expects branch **flow** shares (L1/L2/L3). This bench
   has branch **pressure** sensors, not branch flow sensors. Until you add
   branch flow sensors or retrain on PT1/PT2, the live detector is a connectivity
   and data-quality test, not a validated branch-localisation result.
