# Wiring

Bench node: ESP32 DevKit + ADS1115 + one manifold pressure sensor + up to four
YF-S201-class flow sensors (main + branches L1/L2/L3).

## Pin map

| Signal | ESP32 pin | Notes |
|---|---|---|
| Flow main pulse | GPIO 34 | input-only; divider output (no pull-up) |
| Flow L1 pulse | GPIO 35 | input-only; divider output (no pull-up) |
| Flow L2 pulse | GPIO 32 | divider output (no pull-up) |
| Flow L3 pulse | GPIO 33 | divider output (no pull-up) |
| ADS1115 SDA | GPIO 21 | 4.7k pull-up to 3.3 V (module usually has it) |
| ADS1115 SCL | GPIO 22 | 4.7k pull-up to 3.3 V |
| ADS1115 ADDR | GND | address 0x48 |
| Pressure sensor OUT | ADS A0 | through the 3.2 divider |
| Flow sensors VCC | 5 V | do **not** power from 3.3 V |
| Common | GND | ESP32, ADS1115, sensors, pump supply share GND |

## 5 V signals into a 3.3 V ESP32

YF-S201 pulses are at supply level (5 V). Use a divider before the ESP32:

```
sensor OUT --- 10k ---+--- GPIO
                      |
                     18k
                      |
                     GND
```

5 V x 18 / (10 + 18) = 3.21 V, comfortably below the ESP32 3.6 V absolute
maximum. A 10k/20k pair gives 3.33 V and also works, but leaves less margin.
Add 100 nF from the GPIO node to GND if pulses are noisy.

**Do not add a pull-up to the divider node.** With a push-pull sensor it fights
the low level and can keep the GPIO high. If the sensor output is open-collector,
skip the divider entirely and use a 10k pull-up to 3.3 V instead.

## Pressure divider

```
sensor OUT --- 22k ---+--- ADS A0
                      |
                     10k
                      |
                     GND
```

`V_ads = V_sensor x 10 / (22 + 10) = V_sensor / 3.2`, so
`V_sensor = V_ads x 3.2`. At 5 V the ADS pin sees 1.5625 V, safely inside the
ADS1115 `GAIN_ONE` (+/-4.096 V) range. Add 100 nF from A0 to GND; keep the wire
short because the divider source impedance is about 32k.

The firmware applies `bar = V_sensor x 3.0 + offset` (provisional bench gain;
verify with a gauge). If the sensor idles at 0.5 V instead of 0 V, the offset is
not zero: fit it with `python -m tools.calibrate pressure ...` and set
`PRESSURE_OFFSET_BAR` in both config files. Do not hide an offset inside the
gain.

## Noise / power

- Keep flow signal wires away from pump mains wiring; add 100 nF from signal to
  GND at the ESP32 if pulses are noisy.
- Power the pump from its own supply, common ground only at one point.
- Add a flyback diode across a DC pump; do not power a pump from the ESP32 5 V.
- Mount the flow sensor in the direction of the arrow; avoid air pockets.

## ADS1115 channel plan

| ADS channel | Use |
|---|---|
| A0 | manifold pressure |
| A1-A3 | spare (second pressure point, tank level, etc.) |
