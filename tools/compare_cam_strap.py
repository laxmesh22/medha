"""Compare camera angles with strap angles from the live station.

Subscribes to /ws/live and writes one CSV row per frame. A missing angle is left
blank. It is never written as 0, and it is not included in the paired stats.

Camera elevation is the hub geometry value (the one that drives the avatar).
Flexion and abduction are the webcam engine's values; the hub does not compute
those two names. Strap columns use the same names when the strap payload has them.

    python tools/compare_cam_strap.py --seconds 60
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import socket
import struct
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

ANGLES = ("elevation", "flexion", "abduction")
# Same names on both sides, beyond the three the summary always prints.
EXTRA = (
    "apparent_elevation",
    "plane_of_elevation",
    "elbow_flexion",
    "rotation",
    "trunk_lean_sagittal",
    "trunk_lean_lateral",
    "shrug_index",
)


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _meas(block, key):
    """Return (degrees or None, quality or None). None is unavailable, not zero."""
    if not isinstance(block, dict):
        return None, None
    item = block.get(key)
    if not isinstance(item, dict):
        return None, None
    return _num(item.get("value")), item.get("quality")


def _engine(state, key):
    engine = state.get("auri_cv") if isinstance(state, dict) else None
    if not isinstance(engine, dict):
        return None, None
    value = _num(engine.get(key))
    quality = engine.get("quality") if value is not None else engine.get("quality")
    return value, quality


def frame_row(state: dict) -> dict:
    cam = state.get("angles") if isinstance(state, dict) else None
    straps = (state.get("straps") or {}).get("angles") if isinstance(state, dict) else None
    row = {
        "t_ms": state.get("t_ms") if isinstance(state, dict) else None,
        "frame": state.get("frame") if isinstance(state, dict) else None,
    }
    pairs = {
        "elevation": (_meas(cam, "elevation"), _meas(straps, "elevation")),
        "flexion": (_engine(state, "flexion_deg"), _meas(straps, "flexion")),
        "abduction": (_engine(state, "abduction_deg"), _meas(straps, "abduction")),
    }
    for name in EXTRA:
        pairs[name] = (_meas(cam, name), _meas(straps, name))
    for name, ((cv, cq), (sv, sq)) in pairs.items():
        row[f"cam_{name}"] = cv
        row[f"cam_{name}_quality"] = cq
        row[f"strap_{name}"] = sv
        row[f"strap_{name}_quality"] = sq
    return row


def pearson(xs: list[float], ys: list[float]):
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0.0 or vy <= 0.0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def summarise(rows: list[dict], name: str) -> dict:
    paired = []
    for row in rows:
        t = _num(row.get("t_ms"))
        c = row.get(f"cam_{name}")
        s = row.get(f"strap_{name}")
        if t is None or c is None or s is None:
            continue
        paired.append((t / 1000.0, c, s))
    out = {
        "angle": name,
        "paired": len(paired),
        "mean_diff": None,
        "mean_abs": None,
        "rms": None,
        "max_abs": None,
        "correlation": None,
        "lag_s": None,
    }
    if not paired:
        return out
    diffs = [c - s for _t, c, s in paired]
    out["mean_diff"] = sum(diffs) / len(diffs)
    out["mean_abs"] = sum(abs(d) for d in diffs) / len(diffs)
    out["rms"] = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    out["max_abs"] = max(abs(d) for d in diffs)
    cam = [c for _t, c, s in paired]
    strap = [s for _t, c, s in paired]
    out["correlation"] = pearson(cam, strap)
    out["lag_s"] = _lag(paired)
    return out


def _lag(paired: list[tuple[float, float, float]], max_lag_s: float = 2.0):
    """Lag of the strap behind the camera, in seconds. Positive means the strap is later."""
    if len(paired) < 8:
        return None
    dts = [paired[i][0] - paired[i - 1][0] for i in range(1, len(paired)) if paired[i][0] > paired[i - 1][0]]
    if not dts:
        return None
    dt = sorted(dts)[len(dts) // 2]
    if dt <= 0:
        return None
    span = max(1, int(round(max_lag_s / dt)))
    best = None
    best_lag = None
    cam = [c for _t, c, s in paired]
    strap = [s for _t, c, s in paired]
    for lag in range(-span, span + 1):
        xs, ys = [], []
        for i in range(len(paired)):
            j = i + lag
            if 0 <= j < len(paired):
                xs.append(cam[i])
                ys.append(strap[j])
        score = pearson(xs, ys)
        if score is None:
            continue
        if best is None or score > best:
            best = score
            best_lag = lag * dt
    return best_lag


def _fmt(value, digits=3):
    if value is None:
        return "unavailable"
    return f"{value:.{digits}f}"


def print_summary(stats: list[dict], path: str, seconds: float, frames: int) -> None:
    print(f"csv {path}")
    print(f"seconds {seconds:.1f}  frames {frames}")
    print(f"{'angle':<22} {'paired':>6} {'mean_diff':>12} {'mean_abs':>10} {'rms':>10} {'max_abs':>10} {'corr':>12} {'lag_s':>10}")
    for row in stats:
        print(
            f"{row['angle']:<22} {row['paired']:6d} {_fmt(row['mean_diff']):>12} {_fmt(row['mean_abs']):>10} "
            f"{_fmt(row['rms']):>10} {_fmt(row['max_abs']):>10} {_fmt(row['correlation']):>12} {_fmt(row['lag_s']):>10}"
        )


def _readexact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("websocket closed")
        buf += chunk
    return bytes(buf)


def _send(sock: socket.socket, opcode: int, payload: bytes = b"") -> None:
    mask = os.urandom(4)
    n = len(payload)
    head = bytearray([0x80 | opcode])
    if n < 126:
        head.append(0x80 | n)
    elif n < 65536:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    head += mask
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(head) + body)


def _recv(sock: socket.socket):
    parts = []
    while True:
        b0, b1 = _readexact(sock, 2)
        opcode = b0 & 0x0F
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _readexact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _readexact(sock, 8))[0]
        mask = _readexact(sock, 4) if b1 & 0x80 else None
        data = _readexact(sock, length)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x9:
            _send(sock, 0xA, data)
            continue
        if opcode == 0x8:
            raise ConnectionError("websocket close")
        if opcode == 0xA:
            continue
        parts.append(data)
        if b0 & 0x80:
            return b"".join(parts)


def connect(url: str) -> socket.socket:
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        raise SystemExit(f"unsupported url {url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=5)
    key = __import__("base64").b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("no websocket handshake")
        buf += chunk
    head = buf.split(b"\r\n\r\n", 1)[0].decode("latin1", "replace")
    if "101" not in head.split("\r\n", 1)[0]:
        raise ConnectionError(head.split("\r\n", 1)[0])
    sock.settimeout(2.0)
    return sock


def collect(url: str, seconds: float) -> list[dict]:
    sock = connect(url)
    rows = []
    seen = set()
    end = time.perf_counter() + seconds
    try:
        while time.perf_counter() < end:
            try:
                payload = _recv(sock)
            except socket.timeout:
                continue
            try:
                state = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(state, dict):
                continue
            frame = state.get("frame")
            if frame in seen:
                continue
            seen.add(frame)
            rows.append(frame_row(state))
    finally:
        sock.close()
    return rows


def write_csv(path: str, rows: list[dict]) -> None:
    names = ["t_ms", "frame"]
    for name in ANGLES + EXTRA:
        names += [f"cam_{name}", f"cam_{name}_quality", f"strap_{name}", f"strap_{name}_quality"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {}
            for key in names:
                value = row.get(key)
                out[key] = "" if value is None else value
            writer.writerow(out)


def self_check() -> None:
    rows = []
    for i in range(30):
        cam = math.sin(i / 5.0) * 20.0
        strap = math.sin((i - 2) / 5.0) * 20.0
        rows.append({
            "t_ms": i * 50.0,
            "frame": i,
            "cam_elevation": cam,
            "strap_elevation": strap,
            "cam_flexion": None,
            "strap_flexion": None,
        })
    stat = summarise(rows, "elevation")
    missing = summarise(rows, "flexion")
    if stat["paired"] != 30 or stat["correlation"] is None or stat["correlation"] < 0.9:
        raise SystemExit(f"self-check elevation failed: {stat}")
    if missing["paired"] != 0 or missing["mean_diff"] is not None:
        raise SystemExit(f"self-check kept an unavailable angle: {missing}")
    blank = frame_row({"t_ms": 1, "frame": 1, "angles": None, "straps": None})
    if blank["cam_elevation"] not in (None,) or blank["strap_elevation"] == 0:
        raise SystemExit("self-check wrote a missing angle as a number")
    print("self-check ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="Log camera angles next to strap angles from /ws/live.")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--url", default="ws://127.0.0.1:8012/ws/live")
    parser.add_argument("--out", default="")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    rows = collect(args.url, args.seconds)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = args.out or os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".", f"auri_cam_strap_{stamp}.csv")
    write_csv(path, rows)
    names = list(ANGLES) + ["apparent_elevation"]
    print_summary([summarise(rows, name) for name in names], path, args.seconds, len(rows))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
