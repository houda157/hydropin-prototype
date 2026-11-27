"""Simulated bench rev 1 (the bench as built): F0 flow + PT1 (branch A) + PT2 (branch B), taps L1-L3.

    python -m simulator.bench_rev1 --list
    python -m simulator.bench_rev1 --scenario leak_L1 --duration 180 --out data/sim/leak_L1.json
    python -m simulator.bench_rev1 --scenario baseline --realtime --publish     # to the MQTT broker
    python -m simulator.bench_rev1 --scenario leak_L2 --realtime --post http://localhost:8000   # no broker

Messages use the frozen rev 1 contract (contract/api.md): flow_main = F0, pressure = PT1,
pressure_b = PT2, flow_l1/l2/l3 = 0. Values go through the real quantization chain
(pulses over the 2 s window, ADS1115 counts), so the data is as coarse as the hardware.

Starter physics (to be tuned on the real bench; ROLE 2 brief, CONTEXT §3, Houda's bench twin):
- healthy F0 1.5 L/min, PT1 1.00 bar, PT2 1.00 bar; slow 12 V supply wander moves both pressures together;
- a leak raises F0 by its own flow (8-30 %) and lowers both pressures: L1 lowers PT1 about twice as much as PT2;
  L2 and L3 lower PT2 more than PT1 (and look almost the same);
- Gaussian sensor noise; ripple, dropout, pump restart, Wi-Fi gap and unplugged sensors as stress cases.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from hydropin import config
from hydropin.messages import make_message

# --- healthy operating point and leak response (assumptions; tune with bench data) ---------------
F0_LPM = 1.50
PT1_BAR = 1.00
PT2_BAR = 1.00
# pressure drop per L/min of leak (bar per L/min), per tap: (PT1, PT2)
DROP_PER_LPM = {"L1": (0.20, 0.10), "L2": (0.06, 0.16), "L3": (0.06, 0.15)}
LEAK_LPM = {"small": 0.15, "medium": 0.30, "large": 0.50}
NOISE_P_BAR = 0.006
NOISE_F_LPM = 0.015
WANDER_P_BAR = 0.015          # 12 V adapter: common-mode, slow
WANDER_TAU_S = 60.0


@dataclass(frozen=True)
class BenchScenario:
    name: str
    label: str = "none"
    duration_s: float = 180.0
    tap: str | None = None              # "L1" | "L2" | "L3"
    leak_size: str = "medium"
    leak_start_s: float = 80.0
    leak_stop_s: float | None = None
    ripple: float = 0.0                 # bar, pump ripple (common mode)
    dropout_prob: float = 0.0           # repeated sample (stale reading)
    pump_off: tuple[float, float] | None = None     # (off at, on again at)
    wifi_gap: tuple[float, float] | None = None     # no messages in this window
    unplug: tuple[str, float] | None = None          # ("PT1"|"PT2", from t)
    seed: int = 7
    notes: str = ""


SCENARIOS: dict[str, BenchScenario] = {
    "baseline": BenchScenario("baseline", notes="Healthy bench: noise and supply wander only."),
    "leak_L1": BenchScenario("leak_L1", "leak_L1", tap="L1", notes="Tap L1 opened at 80 s (branch A)."),
    "leak_L2": BenchScenario("leak_L2", "leak_L2", tap="L2", notes="Tap L2 opened at 80 s (branch B, before PT2)."),
    "leak_L3": BenchScenario("leak_L3", "leak_L3", tap="L3", notes="Tap L3 opened at 80 s (branch B, after PT2)."),
    "ripple": BenchScenario("ripple", ripple=0.02, notes="Pump ripple: every alarm is a false alarm."),
    "dropout": BenchScenario("dropout", dropout_prob=0.08, notes="8 % stale readings."),
    "pump_restart": BenchScenario("pump_restart", pump_off=(70.0, 90.0), duration_s=220.0,
                                  notes="Pump off 70-90 s, then on again: re-settle and re-learn, no alarm."),
    "wifi_gap": BenchScenario("wifi_gap", wifi_gap=(100.0, 108.0), notes="No messages for 8 s."),
    "unplug_PT2": BenchScenario("unplug_PT2", unplug=("PT2", 100.0), notes="PT2 unplugged at 100 s: fault, not a leak."),
    "unplug_PT1": BenchScenario("unplug_PT1", unplug=("PT1", 100.0), notes="PT1 unplugged at 100 s: fault, not a leak."),
}
LEAK_SCENARIOS = ("leak_L1", "leak_L2", "leak_L3")
CLEAN_SCENARIOS = ("baseline", "ripple", "dropout", "pump_restart", "wifi_gap")
FAULT_SCENARIOS = ("unplug_PT2", "unplug_PT1")


def list_scenarios() -> list[str]:
    return list(SCENARIOS)


def build(name: str, **overrides) -> BenchScenario:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; choose from {list_scenarios()}")
    sc = SCENARIOS[name]
    return replace(sc, **{k: v for k, v in overrides.items() if v is not None})


def simulate(sc: BenchScenario, device: str = config.SIM_DEVICE,
             start: datetime | None = None) -> list[dict]:
    """Messages (rev 1 contract) for one scenario, one every 0.5 s."""
    rng = np.random.default_rng(sc.seed)
    dt = config.SAMPLE_PERIOD_S
    n = int(round(sc.duration_s / dt))
    t0 = start or datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)
    window = max(1, int(round(config.FLOW_MEASURE_WINDOW_S / dt)))
    hist: deque[float] = deque(maxlen=window)
    wander = 0.0
    a = math.exp(-dt / WANDER_TAU_S)
    msgs: list[dict] = []
    last = None
    leak_lpm = LEAK_LPM[sc.leak_size]
    for i in range(n):
        t = i * dt
        wander = a * wander + math.sqrt(1 - a * a) * rng.normal(0.0, WANDER_P_BAR)
        pump_on = not (sc.pump_off and sc.pump_off[0] <= t < sc.pump_off[1])
        leaking = bool(sc.tap) and t >= sc.leak_start_s and (sc.leak_stop_s is None or t < sc.leak_stop_s)
        if pump_on:
            # after a restart the pressures and flow ramp back over ~3 s
            ramp = 1.0
            if sc.pump_off and t >= sc.pump_off[1]:
                ramp = min(1.0, (t - sc.pump_off[1]) / 3.0)
            f = F0_LPM * (1 + 0.6 * wander) * ramp
            p1 = PT1_BAR * ramp + wander
            p2 = PT2_BAR * ramp + wander
            if leaking:
                d1, d2 = DROP_PER_LPM[sc.tap]
                f += leak_lpm
                p1 -= d1 * leak_lpm
                p2 -= d2 * leak_lpm
            if sc.ripple:
                r = sc.ripple * math.sin(2 * math.pi * 0.37 * t)
                p1 += r
                p2 += r
                f *= 1 + 0.5 * r
        else:
            f, p1, p2 = 0.0, 0.0, 0.0
        f = max(0.0, f + rng.normal(0.0, NOISE_F_LPM) * (f > 0))
        p1 = p1 + rng.normal(0.0, NOISE_P_BAR)
        p2 = p2 + rng.normal(0.0, NOISE_P_BAR)
        if sc.unplug and t >= sc.unplug[1]:
            if sc.unplug[0] == "PT1":
                p1 = 0.0 + abs(rng.normal(0.0, 0.002))       # 0-10 V sensor unplugged: 0 V -> 0 bar
            else:
                p2 = -1.0 + abs(rng.normal(0.0, 0.002))      # -1..1.6 bar sensor at 0 V -> -1 bar
        p1 = min(max(p1, config.PRESSURE_RANGE_BAR[0]), config.PRESSURE_RANGE_BAR[1])
        p2 = min(max(p2, config.PRESSURE_B_RANGE_BAR[0]), config.PRESSURE_B_RANGE_BAR[1])

        # quantization through the real chain
        hist.append(f)
        win_s = len(hist) * dt
        pulses = config.flow_lpm_to_pulses(sum(hist) / len(hist), win_s)
        adc1 = config.pressure_bar_to_adc(p1)
        adc2 = config.pressure_b_bar_to_adc(p2)
        f_cal = config.calibrate_flow(config.pulses_to_flow_lpm(pulses, win_s))
        p1_cal = config.adc_to_pressure_bar(adc1)
        p2_cal = config.adc_to_pressure_b_bar(adc2)
        raw = {"flow_main_pulses": pulses, "flow_l1_pulses": 0, "flow_l2_pulses": 0, "flow_l3_pulses": 0,
               "pressure_adc": adc1, "pressure_b_adc": adc2}
        dropout = False
        if last is not None and rng.random() < sc.dropout_prob:
            f_cal, p1_cal, p2_cal, raw = last[0], last[1], last[2], dict(last[3])
            dropout = True
        last = (f_cal, p1_cal, p2_cal, raw)
        if sc.wifi_gap and sc.wifi_gap[0] <= t < sc.wifi_gap[1]:
            continue                                   # lost on Wi-Fi: seq jumps
        ts = (t0 + timedelta(seconds=t)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        msgs.append(make_message(
            device=device, seq=i, flows_lpm={"main": f_cal, "l1": 0.0, "l2": 0.0, "l3": 0.0},
            pressure_bar=p1_cal, pressure_b_bar=p2_cal, ts=ts, ts_device_ms=int(t * 1000),
            label=sc.label if leaking else "none", scenario=f"rev1_{sc.name}", dropout=dropout,
            ripple=sc.ripple > 0, raw=raw))
    return msgs


def events_for(sc: BenchScenario) -> list[dict]:
    """Ground-truth events for scoring (the detector never reads them)."""
    ev = []
    if sc.tap:
        ev.append({"t_s": sc.leak_start_s, "type": "leak_on", "tap": sc.tap})
        if sc.leak_stop_s is not None:
            ev.append({"t_s": sc.leak_stop_s, "type": "leak_off", "tap": sc.tap})
    if sc.pump_off:
        ev += [{"t_s": sc.pump_off[0], "type": "pump_off"}, {"t_s": sc.pump_off[1], "type": "pump_on"}]
    return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--scenario", default="baseline")
    ap.add_argument("--leak-size", choices=list(LEAK_LPM))
    ap.add_argument("--duration", type=float)
    ap.add_argument("--start", type=float, default=0.0, help="skip the first N seconds")
    ap.add_argument("--speed", type=float, default=1.0, help="real-time factor with --realtime")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", help="write the messages as a JSON array")
    ap.add_argument("--realtime", action="store_true")
    ap.add_argument("--publish", action="store_true", help="publish over MQTT")
    ap.add_argument("--broker", default=config.MQTT_HOST)
    ap.add_argument("--port", type=int, default=config.MQTT_PORT)
    ap.add_argument("--device", default=config.SIM_DEVICE)
    ap.add_argument("--post", metavar="URL", help="send to the backend's POST /api/ingest instead of MQTT")
    ap.add_argument("--now", action="store_true", help="timestamps from the wall clock (live demo)")
    a = ap.parse_args(argv)
    if a.list:
        for k, v in SCENARIOS.items():
            print(f"{k:14s} {v.notes}")
        return 0
    sc = build(a.scenario, leak_size=a.leak_size, duration_s=a.duration, seed=a.seed)
    start = datetime.now(timezone.utc) if (a.now or a.post or a.publish) and a.realtime else None
    if start is not None and a.speed != 1.0:
        # the detector's timers (settle, learn, N samples) run on message time, so a fast-forward
        # keeps the simulated spacing and the timestamps run ahead of the wall clock
        print(f"warning: --speed {a.speed:g}: timestamps run ahead of the clock (the live state shows no "
              "OFFLINE until the clock catches up, and a dashboard run stopped early keeps only the "
              "messages before Stop). Use --speed 1 to record a run.", file=sys.stderr)
    msgs = [m for m in simulate(sc, a.device, start=start) if m["ts_device_ms"] >= a.start * 1000]
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(msgs), encoding="utf-8")
    client = None
    if a.publish:
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(a.broker, a.port)
        client.loop_start()
    prev = None
    for m in msgs:
        if a.realtime and prev is not None:
            time.sleep(max(0.0, (m["ts_device_ms"] - prev) / 1000 / a.speed))
        prev = m["ts_device_ms"]
        if client is not None:
            client.publish(config.telemetry_topic(m["device"]), json.dumps(m), qos=1)
        if a.post:
            import urllib.request
            req = urllib.request.Request(config.fast_local_url(a.post.rstrip("/")) + "/api/ingest", data=json.dumps(m).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
    if client is not None:
        client.loop_stop()
        client.disconnect()
    print(f"{sc.name}: {len(msgs)} messages ({sc.notes})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
