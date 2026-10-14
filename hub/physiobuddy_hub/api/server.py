"""FastAPI app: live WebSocket state, control endpoints, optional debug video, built web UI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__

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
    app = FastAPI(title="Physio Buddy Hub", version=__version__)

    @app.get("/api/status")
    def get_status():
        version, state = pipeline.latest_state()
        return {
            **status,
            "hub_version": __version__,
            "side": pipeline.side,
            "frames_processed": version,
            "fps": state["fps"] if state else 0.0,
            "debug_video": pipeline.debug_video,
        }

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
        except ValueError as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)

    @app.post("/api/record/{action}")
    def record_step(action: str):
        if action not in ("next", "prev", "stop"):
            return JSONResponse({"ok": False, "reason": "action must be next|prev|stop"}, status_code=404)
        return {"ok": True, **pipeline.record_step(action)}

    @app.get("/api/record/status")
    def record_status():
        return pipeline.record_status()

    @app.post("/api/calibrate/rest")
    async def calibrate_rest(seconds: float = 2.0):
        """Patient stands relaxed, arms at sides, looking forward. Sets the shrug baseline."""
        pipeline.start_rest_capture()
        await asyncio.sleep(max(0.5, min(seconds, 5.0)))
        return pipeline.rest_capture_result()

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
                await asyncio.sleep(1.0 / WS_MAX_HZ)
        except (WebSocketDisconnect, RuntimeError):
            return

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
                "<h3>Physio Buddy hub is running</h3><p>Web UI not built yet: "
                "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>. "
                "Live data: <code>/ws/live</code>, status: <a href='/api/status'>/api/status</a>.</p>")

    return app
