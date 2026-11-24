"""Live Streamlit dashboard.

    streamlit run dashboard/app.py

Polls the FastAPI backend. Works with real ESP32 telemetry over MQTT or with
simulator/replay data posted to /api/ingest.
"""
from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from hydropin import config

st.set_page_config(page_title="hydropin | live", page_icon="H", layout="wide")

API_DEFAULT = os.environ.get("HYDROPIN_API", "http://localhost:8000")
API = st.sidebar.text_input("Backend URL", API_DEFAULT).rstrip("/")
st.sidebar.caption("Start backend: `uvicorn backend.main:app`")


def api_get(path: str, **params):
    try:
        resp = httpx.get(f"{API}{path}", params=params, timeout=3.0)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


health = api_get("/health")
st.title("hydropin | live leak monitor")
if health is None:
    st.error(f"Cannot reach backend at {API}. Start it with `uvicorn backend.main:app`.")
    st.stop()

h1, h2, h3 = st.columns(3)
h1.metric("backend", "online")
h2.metric("detector", "loaded" if health.get("detector") else "baseline missing")
mqtt = health.get("mqtt", {})
h3.metric("MQTT", "connected" if mqtt.get("connected") else ("idle" if not mqtt.get("enabled") else "reconnecting"))

st.sidebar.subheader("Labelled run")
label = st.sidebar.selectbox("Label", config.LABELS, index=0)
notes = st.sidebar.text_input("Notes", "")
st.sidebar.caption("Start the run before the leak. Live samples inherit the label only after you press Mark leak onset.")
c1, c2 = st.sidebar.columns(2)
if c1.button("Start run", use_container_width=True):
    try:
        r = httpx.post(f"{API}/api/runs", json={"label": label, "notes": notes}, timeout=3.0)
        r.raise_for_status()
        st.session_state["run_id"] = r.json()["id"]
        st.sidebar.success(f"run {r.json()['id']} started")
    except Exception as exc:
        st.sidebar.error(f"start failed: {exc}")
if c2.button("Stop run", use_container_width=True):
    run_id = st.session_state.get("run_id")
    if run_id:
        try:
            httpx.post(f"{API}/api/runs/{run_id}/stop", timeout=3.0).raise_for_status()
            st.sidebar.info(f"run {run_id} stopped")
        except Exception as exc:
            st.sidebar.error(f"stop failed: {exc}")
    else:
        st.sidebar.warning("no active run")
if st.sidebar.button("Mark leak onset", use_container_width=True):
    run_id = st.session_state.get("run_id")
    if run_id:
        try:
            r = httpx.post(f"{API}/api/runs/{run_id}/onset", json={}, timeout=3.0)
            r.raise_for_status()
            st.sidebar.success(f"onset marked at {r.json()['onset_ts']}")
        except Exception as exc:
            st.sidebar.error(f"onset failed: {exc}")
    else:
        st.sidebar.warning("start a run first")

st.sidebar.link_button("Download CSV", f"{API}/api/export.csv")
if st.sidebar.button("Refresh alerts"):
    st.rerun()


def _chart(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.08,
        subplot_titles=("Flow (L/min)", "Pressure (bar)"),
    )
    colors = {"main": "#4cc9f0", "l1": "#f72585", "l2": "#b5179e", "l3": "#f8961e"}
    for ch in config.FLOW_CHANNELS:
        fig.add_trace(
            go.Scatter(x=df["ts"], y=df[f"flow_{ch}_lpm"], name=ch.upper(), line=dict(color=colors[ch], width=2)),
            row=1,
            col=1,
        )
    fig.add_trace(
        go.Scatter(x=df["ts"], y=df["pressure_bar"], name="pressure", line=dict(color="#80ed99", width=2)),
        row=2,
        col=1,
    )
    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=50, r=20, t=40, b=30),
        legend=dict(orientation="h", y=1.06),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="L/min", row=1, col=1)
    fig.update_yaxes(title_text="bar", row=2, col=1)
    return fig


@st.fragment(run_every=1.0)
def live_panel() -> None:
    rows = api_get("/api/readings", limit=600)
    alerts = api_get("/api/alerts", limit=1)
    if alerts:
        a = alerts[0]
        st.error(
            f"ALERT | {a.get('branch', '?').upper()} | ~{a.get('leak_lpm_est', 0):.2f} L/min "
            f"| confidence {a.get('confidence', 0):.2f} | {a.get('ts', '')}"
        )
    else:
        st.success("No active alert")

    if not rows:
        st.info("Waiting for telemetry... run the simulator or connect the ESP32.")
        return

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    latest = df.iloc[-1]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("main", f"{latest['flow_main_lpm']:.2f} L/min")
    m2.metric("L1", f"{latest['flow_l1_lpm']:.2f} L/min")
    m3.metric("L2", f"{latest['flow_l2_lpm']:.2f} L/min")
    m4.metric("L3", f"{latest['flow_l3_lpm']:.2f} L/min")
    m5.metric("pressure", f"{latest['pressure_bar']:.2f} bar")
    st.plotly_chart(_chart(df), use_container_width=True, key="live-chart")

    with st.expander("Recent alerts"):
        recent = api_get("/api/alerts", limit=20) or []
        if recent:
            st.dataframe(pd.DataFrame(recent), use_container_width=True, hide_index=True)
        else:
            st.write("none")


live_panel()
