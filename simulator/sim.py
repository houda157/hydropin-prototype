"""Simulated bench: healthy baseline and leak/ripple/dropout scenarios.

    python -m simulator.sim --list
    python -m simulator.sim --scenario leak_L1 --leak-size medium --duration 120
    python -m simulator.sim --scenario baseline --realtime --publish

Outputs a CSV (contract columns), a dark Plotly HTML report and a terminal
summary. Sensor values go through the real pulse/ADC quantization chain, so the
data is as coarse as the hardware, not artificially smooth.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from hydropin import config
from hydropin.messages import CSV_COLUMNS, make_message, to_row
from simulator.scenarios import LEAK_SIZES_LPM, Scenario, build_scenario, list_scenarios

BASE_BRANCH_FLOW_LPM = {"l1": 0.55, "l2": 0.45, "l3": 0.65}
PRESSURE_ZERO_BAR = 2.2
PRESSURE_DROP_PER_LPM = 0.12
FLOW_NOISE_LPM = 0.015
PRESSURE_NOISE_BAR = 0.012


def simulate(sc: Scenario, device: str = config.DEFAULT_DEVICE) -> tuple[pd.DataFrame, list[dict]]:
    """Run one scenario and return (flat DataFrame, raw message list)."""
    rng = np.random.default_rng(sc.seed)
    dt = config.SAMPLE_PERIOD_S
    n = max(1, int(round(sc.duration_s / dt)))
    base_ts = datetime.now(timezone.utc)
    rows: list[dict] = []
    messages: list[dict] = []
    walk = {c: 0.0 for c in BASE_BRANCH_FLOW_LPM}
    last_raw: dict[str, int] | None = None
    last_vals: dict[str, float] | None = None
    window_samples = max(1, int(round(config.FLOW_MEASURE_WINDOW_S / dt)))
    flow_hist: deque[dict[str, float]] = deque(maxlen=window_samples)

    for i in range(n):
        t = i * dt
        for c in BASE_BRANCH_FLOW_LPM:
            walk[c] = 0.98 * walk[c] + rng.normal(0.0, 0.006)
        slow = 1.0 + 0.05 * math.sin(2 * math.pi * t / 180.0) + 0.02 * math.sin(2 * math.pi * t / 37.0 + 1.0)
        branch = {c: max(0.0, (BASE_BRANCH_FLOW_LPM[c] + walk[c]) * slow) for c in BASE_BRANCH_FLOW_LPM}

        leak = 0.0
        if sc.leak_branch and t >= sc.leak_start_s:
            frac = 1.0 if sc.leak_ramp_s <= 0 else min(1.0, (t - sc.leak_start_s) / sc.leak_ramp_s)
            leak = sc.leak_lpm * frac
            branch[sc.leak_branch] += leak

        main_true = sum(branch.values()) + 0.02
        pressure_true = PRESSURE_ZERO_BAR - PRESSURE_DROP_PER_LPM * main_true

        ripple = sc.ripple_amplitude * (
            math.sin(2 * math.pi * 0.7 * t) + 0.4 * math.sin(2 * math.pi * 3.1 * t + 1.3)
        )
        branch = {c: max(0.0, v + 0.5 * ripple) for c, v in branch.items()}
        main_true = max(0.0, main_true + 1.5 * ripple)
        pressure_true = max(0.0, pressure_true + 0.15 * ripple)

        ns = sc.noise_scale
        true_branch = {c: max(0.0, v + rng.normal(0.0, FLOW_NOISE_LPM * ns)) for c, v in branch.items()}
        true_main = max(0.0, sum(true_branch.values()) + 0.02 + rng.normal(0.0, 0.02 * ns))
        true_pressure = max(0.0, pressure_true + rng.normal(0.0, PRESSURE_NOISE_BAR * ns))

        flow_hist.append({**true_branch, "main": true_main})
        window_s = len(flow_hist) * dt
        raw = {
            f"flow_{c}_pulses": max(
                0,
                int(
                    round(
                        (sum(h[c] for h in flow_hist) / len(flow_hist))
                        / config.FLOW_GAIN
                        * config.FLOW_PULSES_PER_LPM
                        * window_s
                    )
                ),
            )
            for c in config.FLOW_CHANNELS
        }
        raw["pressure_adc"] = config.pressure_bar_to_adc(true_pressure)

        flow_gain = config.FLOW_GAIN * (1.0 + sc.flow_gain_error)
        pressure_gain = config.PRESSURE_GAIN * (1.0 + sc.pressure_gain_error)
        cal_branch = {
            c: config.pulses_to_flow_lpm(raw[f"flow_{c}_pulses"], window_s) * flow_gain
            for c in config.BRANCH_CHANNELS
        }
        cal_main = config.pulses_to_flow_lpm(raw["flow_main_pulses"], window_s) * flow_gain
        # Gain error scales the slope; the sensor offset is additive and is not
        # scaled by a gain error.
        cal_pressure = (
            config.adc_to_sensor_volts(raw["pressure_adc"]) * pressure_gain
            + config.PRESSURE_OFFSET_BAR
        )

        dropout = False
        if last_raw is not None and last_vals is not None and rng.random() < sc.dropout_prob:
            raw = dict(last_raw)
            cal_branch = {c: last_vals[c] for c in config.BRANCH_CHANNELS}
            cal_main = last_vals["main"]
            cal_pressure = last_vals["pressure"]
            dropout = True

        flows = {**cal_branch, "main": cal_main}
        ts = (base_ts + timedelta(seconds=t)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        active_label = sc.label if (sc.leak_branch and t >= sc.leak_start_s) else "none"
        msg = make_message(
            device=device,
            seq=i,
            flows_lpm=flows,
            pressure_bar=cal_pressure,
            ts=ts,
            ts_device_ms=int(t * 1000),
            label=active_label,
            scenario=sc.name,
            dropout=dropout,
            ripple=sc.ripple_amplitude > 0,
            raw=raw,
        )
        messages.append(msg)
        rows.append(to_row(msg))
        last_raw = raw
        last_vals = {**flows, "pressure": cal_pressure}

    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df, messages


def default_paths(sc: Scenario, out: str | None, html: str | None) -> tuple[Path, Path]:
    stem = f"{sc.name}_seed{sc.seed}"
    out_path = Path(out) if out else Path("data") / "raw" / f"{stem}.csv"
    html_path = Path(html) if html else Path("data") / "raw" / f"{stem}.html"
    return out_path, html_path


def save_csv(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["ts"] = out["ts"].dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    out.to_csv(path, index=False)
    return path


def plot_html(df: pd.DataFrame, sc: Scenario, path: Path) -> Path:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    path.parent.mkdir(parents=True, exist_ok=True)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.07,
        subplot_titles=("Flow (L/min, calibrated)", "Pressure (bar, calibrated)"),
    )
    colors = {"main": "#4cc9f0", "l1": "#f72585", "l2": "#b5179e", "l3": "#f8961e"}
    for ch in config.FLOW_CHANNELS:
        fig.add_trace(
            go.Scatter(
                x=df["ts"],
                y=df[f"flow_{ch}_lpm"],
                name=ch.upper(),
                mode="lines",
                line=dict(color=colors[ch], width=1.6 if ch != "main" else 2.2),
            ),
            row=1,
            col=1,
        )
    fig.add_trace(
        go.Scatter(x=df["ts"], y=df["pressure_bar"], name="pressure", line=dict(color="#80ed99", width=1.8)),
        row=2,
        col=1,
    )

    if sc.leak_branch and sc.leak_lpm > 0:
        start = df["ts"].iloc[0] + pd.Timedelta(seconds=sc.leak_start_s)
        fig.add_vrect(
            x0=start,
            x1=df["ts"].iloc[-1],
            fillcolor="#ff006e",
            opacity=0.10,
            line_width=0,
            annotation_text=f"{sc.label} ~{sc.leak_lpm:.2f} L/min",
            annotation_position="top left",
            row=1,
            col=1,
        )
        fig.add_vline(x=start, line_width=1, line_dash="dot", line_color="#ff006e", row=1, col=1)

    drops = int(df["dropout"].sum())
    fig.update_layout(
        template="plotly_dark",
        height=720,
        title=dict(
            text=f"hydropin | {sc.name} | label={sc.label} | {sc.duration_s:.0f}s @ {config.PUBLISH_HZ:.0f} Hz"
            + (f" | {drops} dropouts" if drops else ""),
            x=0.02,
        ),
        legend=dict(orientation="h", y=1.04, x=0.55),
        margin=dict(l=60, r=24, t=80, b=40),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="L/min", row=1, col=1)
    fig.update_yaxes(title_text="bar", row=2, col=1)
    fig.write_html(path, include_plotlyjs="cdn")
    return path


def print_summary(df: pd.DataFrame, sc: Scenario, csv_path: Path, html_path: Path | None) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover
        print(df.describe())
        return

    console = Console()
    console.print()
    console.rule(f"[bold cyan]hydropin simulator[/] | [white]{sc.name}[/] | label={sc.label}")
    console.print(f"[dim]{sc.notes}[/]")

    stats = Table(title="Channel statistics (calibrated)", show_header=True, header_style="bold magenta")
    stats.add_column("channel", style="cyan")
    stats.add_column("mean", justify="right")
    stats.add_column("min", justify="right")
    stats.add_column("max", justify="right")
    stats.add_column("std", justify="right")
    for ch in config.FLOW_CHANNELS:
        col = df[f"flow_{ch}_lpm"]
        stats.add_row(ch.upper(), f"{col.mean():.3f}", f"{col.min():.3f}", f"{col.max():.3f}", f"{col.std():.3f}")
    p = df["pressure_bar"]
    stats.add_row("pressure", f"{p.mean():.3f}", f"{p.min():.3f}", f"{p.max():.3f}", f"{p.std():.3f}")
    console.print(stats)

    meta = Table(show_header=False, box=None)
    meta.add_column("k", style="dim")
    meta.add_column("v")
    meta.add_row("samples", str(len(df)))
    meta.add_row("duration", f"{sc.duration_s:.1f} s @ {config.PUBLISH_HZ:.1f} Hz")
    meta.add_row("dropouts", str(int(df["dropout"].sum())))
    if sc.leak_branch:
        meta.add_row("leak", f"{sc.leak_branch} {sc.leak_lpm:.2f} L/min from t={sc.leak_start_s:.0f}s")
    if sc.flow_gain_error or sc.pressure_gain_error:
        meta.add_row("gain error", f"flow {sc.flow_gain_error:+.0%}, pressure {sc.pressure_gain_error:+.0%}")
    meta.add_row("csv", str(csv_path))
    if html_path:
        meta.add_row("html", str(html_path))
    console.print(meta)

    one_pulse = config.pulses_to_flow_lpm(1, config.SAMPLE_PERIOD_S) * config.FLOW_GAIN
    console.print(
        f"[dim]Reality check: one pulse = {one_pulse:.2f} L/min at {config.PUBLISH_HZ:.0f} Hz, "
        "so leaks below that need a rolling window, not a single sample.[/]"
    )
    console.print()


def publish_messages(messages: list[dict], broker: str, port: int, device: str, realtime: bool) -> None:
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{device}")
    client.connect(broker, port, keepalive=30)
    client.loop_start()
    topic = config.telemetry_topic(device)
    try:
        for msg in messages:
            client.publish(topic, json.dumps(msg), qos=1)
            if realtime:
                time.sleep(config.SAMPLE_PERIOD_S)
        if not realtime:
            time.sleep(1.0)  # let the network loop flush queued QoS 1 packets
    finally:
        client.loop_stop()
        client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hydropin bench simulator")
    parser.add_argument("--scenario", default="baseline")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument("--leak-size", choices=list(LEAK_SIZES_LPM))
    parser.add_argument("--duration", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--out")
    parser.add_argument("--html")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--realtime", action="store_true", help="sleep in real time while printing")
    parser.add_argument("--publish", action="store_true", help="publish messages over MQTT")
    parser.add_argument("--broker", default=config.MQTT_HOST)
    parser.add_argument("--port", type=int, default=config.MQTT_PORT)
    parser.add_argument("--device", default=config.DEFAULT_DEVICE)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for name in list_scenarios():
            print(name)
        return 0

    sc = build_scenario(args.scenario, leak_size=args.leak_size, duration_s=args.duration, seed=args.seed)
    df, messages = simulate(sc, device=args.device)
    out_path, html_path = default_paths(sc, args.out, args.html)
    save_csv(df, out_path)

    if not args.no_html:
        plot_html(df, sc, html_path)
    else:
        html_path = None

    if not args.quiet:
        print_summary(df, sc, out_path, html_path)

    if args.publish:
        publish_messages(messages, args.broker, args.port, args.device, args.realtime)

    if args.realtime and not args.publish and not args.quiet:
        try:
            from rich.live import Live
            from rich.table import Table

            table = Table(title=f"live | {sc.name}")
            table.add_column("t")
            table.add_column("main")
            table.add_column("L1")
            table.add_column("L2")
            table.add_column("L3")
            table.add_column("bar")
            table.add_column("flag")
            with Live(table, refresh_per_second=4) as live:
                for _, row in df.iterrows():
                    flag = "LEAK?" if sc.label != "none" and row["ts"] >= df["ts"].iloc[0] + pd.Timedelta(
                        seconds=sc.leak_start_s
                    ) else ""
                    table.add_row(
                        f"{row['ts'].strftime('%H:%M:%S')}",
                        f"{row['flow_main_lpm']:.2f}",
                        f"{row['flow_l1_lpm']:.2f}",
                        f"{row['flow_l2_lpm']:.2f}",
                        f"{row['flow_l3_lpm']:.2f}",
                        f"{row['pressure_bar']:.2f}",
                        flag,
                    )
                    if len(table.rows) > 12:
                        table.rows.pop(0)
                    live.update(table)
                    time.sleep(config.SAMPLE_PERIOD_S)
        except ImportError:  # pragma: no cover
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
