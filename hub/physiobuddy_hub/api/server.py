"""FastAPI app: live WebSocket state, control endpoints, optional debug video, built web UI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..pipeline import RecordingOff
from ..straps.calibrate import collect_samples

STATIC_DIR = Path(__file__).parent / "static"
WS_MAX_HZ = 30.0


class SideBody(BaseModel):
    side: str


class ExerciseBody(BaseModel):
    id: str
    target: Optional[float] = None


class TargetBody(BaseModel):
    target: float


class PauseBody(BaseModel):
    paused: bool


class AutodetectBody(BaseModel):
    enabled: bool


class RecordStartBody(BaseModel):
    subject_id: str
    side: str = "right"
    consent: bool = False
    protocol: str = "full"


def create_app(pipeline, status: dict) -> FastAPI:
    app = FastAPI(title="Auri Hub", version=__version__)

    @app.get("/api/status")
    def get_status():
        version, state = pipeline.latest_state()
        body = {
            **status,
            "hub_version": __version__,
            "side": pipeline.side,
            "frames_processed": version,
            "fps": state["fps"] if state else 0.0,
            "debug_video": pipeline.debug_video,
            "camera_preview": bool(getattr(pipeline.source, "preview", False)),
            "pose_smoothing": getattr(pipeline, "pose_smoothing", "light"),
        }
        straps = pipeline.strap_status()
        if straps is not None:
            body["straps"] = straps
        return body

    @app.post("/api/side")
    def set_side(body: SideBody):
        if body.side not in ("right", "left"):
            return JSONResponse({"ok": False, "reason": "side must be right|left"}, status_code=400)
        pipeline.set_side(body.side)
        return {"ok": True, "side": body.side}

    @app.get("/api/exercises")
    def list_exercises():
        from ..core.coach import EXERCISES

        return [{"id": e.id, "name": e.name, "metric": e.metric, "target": e.target, "hold_s": e.hold_s,
                 "instructions": e.instructions} for e in EXERCISES.values()]

    @app.post("/api/exercise")
    def set_exercise(body: ExerciseBody):
        try:
            return {"ok": True, "coach": pipeline.set_exercise(body.id, body.target)}
        except ValueError as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)

    @app.post("/api/target")
    def set_target(body: TargetBody):
        if not 10 <= body.target <= 180:
            return JSONResponse({"ok": False, "reason": "target must be 10-180 deg"}, status_code=400)
        pipeline.set_target(body.target)
        return {"ok": True, "target": body.target}

    @app.post("/api/coach/reset")
    def reset_coach():
        pipeline.reset_coach()
        return {"ok": True}

    @app.post("/api/coach/pause")
    def pause_coach(body: PauseBody):
        """Safety pause (pain / "stop"): no rep can be counted until resumed."""
        coach = pipeline.set_paused(body.paused)
        return {"ok": True, "paused": coach["user_paused"]}

    @app.post("/api/autodetect")
    def autodetect(body: AutodetectBody):
        """Let PB-MotionNet pick the exercise from what the patient is doing (needs an exported model)."""
        return {"ok": True, **pipeline.set_autodetect(body.enabled)}

    @app.post("/api/record/start")
    def record_start(body: RecordStartBody):
        """Guided volunteer recording (keypoints only). Requires the volunteer's written consent."""
        try:
            return {"ok": True, **pipeline.record_start(body.subject_id, body.side, body.consent, body.protocol)}
        except RecordingOff as exc:
            return JSONResponse({"ok": False, "enabled": False, "reason": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)

    @app.post("/api/record/{action}")
    def record_step(action: str):
        if action not in ("next", "prev", "stop"):
            return JSONResponse({"ok": False, "reason": "action must be next|prev|stop"}, status_code=404)
        try:
            return {"ok": True, **pipeline.record_step(action)}
        except RecordingOff as exc:
            return JSONResponse({"ok": False, "enabled": False, "reason": str(exc)}, status_code=409)

    @app.get("/api/record/status")
    def record_status():
        return pipeline.record_status()

    @app.post("/api/straps/reconnect")
    def strap_reconnect():
        """Drop the BLE sessions so they reconnect. Does not touch the camera thread."""
        link = pipeline.strap_source() or getattr(pipeline, "phone", None)
        if link is None:
            return JSONResponse({"ok": False, "reason": "straps are off"}, status_code=409)
        reconnect = getattr(link, "request_reconnect", None)
        if reconnect is not None:
            reconnect()
        return {"ok": True}

    @app.get("/api/straps/calibration")
    def strap_calibration():
        link = pipeline.strap_source() or getattr(pipeline, "phone", None)
        if link is None:
            return {"enabled": False, "state": "none", "time": None, "sensors": []}
        return {"enabled": True, **pipeline.calibration_view()}

    @app.post("/api/straps/calibrate/npose")
    async def strap_npose():
        link = pipeline.strap_source() or getattr(pipeline, "phone", None)
        if link is None:
            return JSONResponse({"ok": False, "reason": "straps are off"}, status_code=409)
        return pipeline.finish_npose(await collect_samples(link, 3.0))

    @app.post("/api/straps/calibrate/raise")
    async def strap_raise():
        link = pipeline.strap_source() or getattr(pipeline, "phone", None)
        if link is None:
            return JSONResponse({"ok": False, "reason": "straps are off"}, status_code=409)
        return pipeline.finish_raise(await collect_samples(link, 4.0))

    @app.post("/api/calibrate/rest")
    async def calibrate_rest(seconds: float = 2.0):
        """Patient stands relaxed, arms at sides, looking forward. Sets the shrug baseline."""
        pipeline.start_rest_capture()
        await asyncio.sleep(max(0.5, min(seconds, 5.0)))
        return pipeline.rest_capture_result()

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket):
        """The phone forwards raw strap samples. Angles are not computed here."""
        await ws.accept()
        try:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict):
                    pipeline.phone.push(msg)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        await ws.accept()
        last = -1
        try:
            while True:
                version, state = pipeline.latest_state()
                if state is not None and version != last:
                    await ws.send_json(state)
                    last = version
                else:
                    await asyncio.sleep(1.0 / WS_MAX_HZ)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/api/camera/preview.jpg")
    async def camera_preview_jpg(after: int = -1):
        """One JPEG for the frame the skeleton was measured on. Not recorded.

        The browser pulls the newest frame and drops anything older, so a slow
        decode cannot build a queue the way a multipart MJPEG stream does."""
        if not getattr(pipeline.source, "preview", False):
            return JSONResponse({"ok": False, "reason": "camera preview is off"}, status_code=404)
        meta = await asyncio.to_thread(pipeline.wait_preview, after, 1.0)
        if not meta or not meta.get("jpeg"):
            return Response(status_code=204)
        headers = {
            "X-Auri-Frame": str(meta["frame"]),
            "Cache-Control": "no-store",
        }
        if meta.get("t_ms") is not None:
            headers["X-Auri-Time"] = str(meta["t_ms"])
        return Response(content=meta["jpeg"], media_type="image/jpeg", headers=headers)

    @app.get("/api/camera/preview.mjpg")
    async def camera_preview():
        """Downscaled webcam JPEG. Not recorded, and not used for angles."""
        if not getattr(pipeline.source, "preview", False):
            return JSONResponse({"ok": False, "reason": "camera preview is off"}, status_code=404)

        async def gen():
            last = None
            while True:
                jpeg = pipeline.latest_preview()
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/debug/stream.mjpg")
    async def debug_stream():
        """Annotated colour video - only when started with --debug-video (privacy: off by default)."""
        if not pipeline.debug_video:
            return JSONResponse({"ok": False, "reason": "start hub with --debug-video"}, status_code=404)

        async def gen():
            last = None
            while True:
                jpeg = pipeline.latest_jpeg()
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(1.0 / 20)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    else:
        @app.get("/")
        def no_ui():
            return HTMLResponse(
                "<h3>Auri hub is running</h3><p>Web UI not built yet: "
                "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>. "
                "Live data: <code>/ws/live</code>, status: <a href='/api/status'>/api/status</a>.</p>")

    return app
