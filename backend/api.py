"""REST + WebSocket endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

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
    with storage.db_session(_db(request)) as conn:
        run_id = storage.create_run(conn, label, str(payload.get("notes", "")))
    return {"id": run_id, "label": label, "started": True}


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
