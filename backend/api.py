"""REST + WebSocket endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from detection.replay import build_replay
from hydropin import config
from hydropin.messages import MessageError

from . import storage
from .ingest import ingest_message

router = APIRouter()


def _db(request: Request) -> str:
    return request.app.state.db_path


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    listener = getattr(request.app.state, "mqtt_listener", None)
    return {
        "ok": True,
        "db": request.app.state.db_path,
        "detector": request.app.state.detector is not None,
        "bench_detector": request.app.state.bench is not None,
        "mqtt": {
            "enabled": listener is not None,
            "connected": bool(listener and listener.connected),
            "received": int(getattr(request.app.state, "mqtt_received", 0)),
        },
    }


@router.post("/api/ingest")
def ingest(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return ingest_message(
            payload,
            db_path=_db(request),
            detector=request.app.state.detector,
            detector_lock=request.app.state.detector_lock,
            send_notifications=request.app.state.notify,
            bench=request.app.state.bench,
        )
    except MessageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/readings")
def readings(
    request: Request,
    limit: int = 500,
    since: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    with storage.db_session(_db(request)) as conn:
        return storage.query_readings(conn, limit=limit, since=since, device=device)


@router.get("/api/alerts")
def alerts(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    with storage.db_session(_db(request)) as conn:
        return storage.query_alerts(conn, limit=limit)


@router.get("/api/runs")
def runs(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    with storage.db_session(_db(request)) as conn:
        return storage.list_runs(conn, limit=limit)


@router.post("/api/runs")
def start_run(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    label = str(payload.get("label", "none"))
    if label not in config.LABELS:
        raise HTTPException(status_code=422, detail=f"label must be one of {config.LABELS}")
    leak = payload.get("measured_leak_lpm")
    with storage.db_session(_db(request)) as conn:
        run_id = storage.create_run(
            conn,
            label,
            str(payload.get("notes", "")),
            opening=payload.get("opening"),
            measured_leak_lpm=float(leak) if leak not in (None, "") else None,
            blind=bool(payload.get("blind", False)),
        )
    return {"id": run_id, "label": label, "started": True}


@router.post("/api/runs/{run_id}/meta")
def run_meta(run_id: int, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Fill in run metadata afterwards (blind test: the label is entered after the run)."""
    if "label" in payload and payload["label"] not in config.LABELS:
        raise HTTPException(status_code=422, detail=f"label must be one of {config.LABELS}")
    with storage.db_session(_db(request)) as conn:
        ok = storage.update_run(conn, run_id, **payload)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found or nothing to update")
    return {"id": run_id, "updated": True}


@router.post("/api/runs/{run_id}/onset")
def mark_onset(
    run_id: int,
    request: Request,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    ts = str(payload.get("ts") or storage.utc_now())
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid ISO-8601 ts: {ts}") from exc
    with storage.db_session(_db(request)) as conn:
        ok = storage.set_run_onset(conn, run_id, ts)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found")
    return {"id": run_id, "onset_ts": ts, "marked": True}


@router.post("/api/runs/{run_id}/stop")
def stop_run(run_id: int, request: Request) -> dict[str, Any]:
    with storage.db_session(_db(request)) as conn:
        ok = storage.stop_run(conn, run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found or already stopped")
    return {"id": run_id, "stopped": True}


@router.get("/api/export.csv")
def export_csv(request: Request, limit: int = 100000) -> Response:
    with storage.db_session(_db(request)) as conn:
        body = storage.readings_csv(conn, limit=limit)
    stamp = storage.utc_now().replace(":", "").replace("-", "")[:15]
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="hydropin_{stamp}.csv"'},
    )


# --- rev 1 bench: processed frames, events, baseline ----------------------
def _bench(request: Request):
    bench = request.app.state.bench
    if bench is None:
        raise HTTPException(status_code=503, detail="bench detector disabled")
    return bench


@router.get("/api/state")
def state(request: Request) -> dict[str, Any]:
    """Latest processed frame; state OFFLINE when no message for 3 s."""
    frame = _bench(request).state_at(storage.utc_now())
    if frame is None:
        return {"state": "OFFLINE", "frame": None}
    return {"state": frame["state"], "frame": frame}


@router.get("/api/frames")
def frames(request: Request, since_id: int = 0, limit: int = 600, run_id: int | None = None) -> list[dict[str, Any]]:
    with storage.db_session(_db(request)) as conn:
        return storage.query_frames(conn, since_id=since_id, limit=limit, run_id=run_id)


@router.post("/api/events")
def add_event(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    type_ = str(payload.get("type", ""))
    tap = payload.get("tap")
    if tap is not None and tap not in ("L1", "L2", "L3"):
        raise HTTPException(status_code=422, detail="tap must be L1, L2 or L3")
    ts = str(payload.get("ts") or storage.utc_now())
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid ISO-8601 ts: {ts}") from exc
    with storage.db_session(_db(request)) as conn:
        run = storage.active_run(conn)
        run_id = payload.get("run_id") or (run["id"] if run else None)
        try:
            ev_id = storage.insert_event(conn, type_, ts=ts, tap=tap, run_id=run_id, notes=str(payload.get("notes", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # a tap opened during a labelled run is the leak onset (keeps Talel's label inheritance working)
        if type_ == "leak_on" and run and not run.get("onset_ts") and run_id == run["id"]:
            storage.set_run_onset(conn, run["id"], ts)
    return {"id": ev_id, "type": type_, "ts": ts, "tap": tap, "run_id": run_id}


@router.get("/api/events")
def events(request: Request, run_id: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
    with storage.db_session(_db(request)) as conn:
        return storage.list_events(conn, run_id=run_id, limit=limit)


@router.get("/api/leaks")
def leaks(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    """Leak episodes, newest first, with status open | checking | fixed (farmer app)."""
    with storage.db_session(_db(request)) as conn:
        return storage.list_leaks(conn, limit=limit)


@router.post("/api/leaks/{leak_id}/fixed")
def leak_fixed(leak_id: int, request: Request) -> dict[str, Any]:
    """The farmer says the leak is fixed; the sensors confirm it when the bench is back to HEALTHY."""
    with storage.db_session(_db(request)) as conn:
        row = storage.mark_leak_fixed(conn, leak_id, storage.utc_now())
    if row is None:
        raise HTTPException(status_code=404, detail="leak not found")
    return row


@router.post("/api/baseline/reset")
def baseline_reset(request: Request) -> dict[str, Any]:
    """Re-learn the healthy baseline (after any valve change): SETTLING -> LEARNING -> HEALTHY."""
    _bench(request).reset_baseline()
    return {"reset": True}


@router.get("/api/runs/{run_id}/replay")
def run_replay(run_id: int, request: Request) -> dict[str, Any]:
    """One recorded run in the replay format the static dashboard plays (contract/api.md)."""
    with storage.db_session(_db(request)) as conn:
        run = storage.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        fr = storage.query_frames(conn, run_id=run_id, limit=1_000_000)
        ev = storage.list_events(conn, run_id=run_id)
    if not fr:
        raise HTTPException(status_code=404, detail="run has no frames")
    meta = {k: run.get(k) for k in ("opening", "measured_leak_lpm", "blind", "notes", "started_ts", "stopped_ts")}
    return build_replay(fr, ev, run_id=f"bench_run_{run_id}", label=run["label"], simulation=False,
                        source="bench", meta=meta)


@router.websocket("/ws")
async def ws_frames(websocket: WebSocket) -> None:
    """Processed frames as they arrive: {"type": "frames", "frames": [...], "state": "..."}."""
    await websocket.accept()
    last_id = 0
    first = True
    try:
        while True:
            with storage.db_session(websocket.app.state.db_path) as conn:
                rows = storage.query_frames(conn, since_id=0 if first else last_id, limit=240 if first else 600)
            first = False
            if rows:
                last_id = rows[-1]["id"]
            bench = websocket.app.state.bench
            cur = bench.state_at(storage.utc_now()) if bench is not None else None
            await websocket.send_json(
                {"type": "frames" if rows else "tick", "frames": rows, "state": cur["state"] if cur else "OFFLINE"}
            )
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception:
        return


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    last_ts: str | None = None
    try:
        while True:
            with storage.db_session(websocket.app.state.db_path) as conn:
                rows = storage.query_readings(conn, limit=200, since=last_ts)
                latest_alert = storage.query_alerts(conn, limit=1)
            if rows:
                last_ts = rows[-1]["ts"]
            await websocket.send_json(
                {
                    "type": "readings" if rows else "tick",
                    "data": rows,
                    "latest_alert": latest_alert[0] if latest_alert else None,
                }
            )
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception:
        return
