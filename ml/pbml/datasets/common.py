"""Shared pieces for public-dataset adapters: download helper, skeleton sequence type, frame conversions.

Every skeleton adapter outputs COCO-17 points in the *RealSense camera frame* (X right, Y down, Z forward,
metres, NaN = invalid), the same convention as ``physiobuddy_hub.datatypes``, so the hub's own
``SkeletonKinematics`` computes angles for public data exactly as it does live.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

PUBLIC_ROOT = Path(__file__).resolve().parents[2] / "data" / "public"
DEFAULT_UP_CAM = np.array([0.0, -1.0, 0.0])  # level camera: world up = -Y


@dataclass
class SkeletonSequence:
    subject: str
    exercise: str                  # PB-MotionNet class id (flexion, abduction, ..., unknown)
    side: str                      # affected/moving side used for kinematics: right | left
    points: np.ndarray             # (T, 17, 3) camera frame metres, NaN invalid
    fps: float
    source: str                    # spar | intellirehab | rehab24 | real
    name: str = ""
    correct: Optional[bool] = None  # dataset correctness label (None = not labelled)
    up_cam: np.ndarray = field(default_factory=lambda: DEFAULT_UP_CAM.copy())
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.points)


def download(url: str, dest: Path, timeout_s: int = 3600) -> Path:
    """Fetch ``url`` to ``dest`` unless it already exists (non-empty).

    Uses the system ``curl`` when available: on Windows it trusts the OS certificate store, which works
    behind TLS-inspecting networks where Python's bundled CA list fails.
    """
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    curl = shutil.which("curl")
    if curl:
        subprocess.run([curl, "-sSL", "--fail", "--retry", "3", "-C", "-", "--max-time", str(timeout_s),
                        "-o", str(tmp), url], check=True)
    else:
        with urllib.request.urlopen(url, timeout=timeout_s) as r, open(tmp, "wb") as fh:
            shutil.copyfileobj(r, fh)
    tmp.replace(dest)
    return dest


def http_range(url: str, start: int, end: int, timeout_s: int = 600) -> bytes:
    """Bytes ``start..end`` (inclusive) of ``url`` via curl (Zenodo supports HTTP range requests)."""
    curl = shutil.which("curl")
    if curl:
        return subprocess.run([curl, "-sSL", "--fail", "--retry", "3", "--max-time", str(timeout_s),
                               "-r", f"{start}-{end}", url], check=True, capture_output=True).stdout
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return r.read()


class RemoteZip:
    """Read selected members of a large remote zip without downloading all of it."""

    def __init__(self, url: str, size: int):
        import struct

        self.url, self.size, self._struct = url, size, struct
        tail = http_range(url, max(0, size - 65558), size - 1)
        i = tail.rfind(b"PK\x05\x06")
        if i < 0:
            raise ValueError("zip end-of-central-directory not found")
        cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
        cd = http_range(url, cd_off, cd_off + cd_size - 1)
        self.entries = {}
        j = 0
        while cd[j:j + 4] == b"PK\x01\x02":
            method = struct.unpack("<H", cd[j + 10:j + 12])[0]
            csize, usize = struct.unpack("<II", cd[j + 20:j + 28])
            n, m, k = struct.unpack("<HHH", cd[j + 28:j + 34])
            off = struct.unpack("<I", cd[j + 42:j + 46])[0]
            self.entries[cd[j + 46:j + 46 + n].decode()] = (method, csize, usize, off)
            j += 46 + n + m + k

    def read(self, name: str) -> bytes:
        import zlib

        method, csize, usize, off = self.entries[name]
        b = http_range(self.url, off, off + 30 + 1024 + csize)
        n, m = self._struct.unpack("<HH", b[26:30])
        data = b[30 + n + m:30 + n + m + csize]
        out = zlib.decompress(data, -15) if method == 8 else data
        if len(out) != usize:
            raise IOError(f"{name}: got {len(out)} of {usize} bytes")
        return out


def to_skeleton3d(points: np.ndarray):
    """(17, 3) array with NaNs -> hub ``Skeleton3D``."""
    from physiobuddy_hub.datatypes import L_HIP, L_SHOULDER, R_HIP, R_SHOULDER, Skeleton3D

    valid = np.all(np.isfinite(points), axis=1)
    torso = [i for i in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP) if valid[i]]
    depth = float(np.median(points[torso, 2])) if torso else None
    return Skeleton3D(points=np.where(valid[:, None], points, np.nan), valid=valid, body_depth_m=depth)


def sequence_angles(seq: SkeletonSequence) -> list:
    """Hub ``CameraAngles`` for every frame (geometry only: the same code path as the live hub)."""
    from physiobuddy_hub.core.skeleton_kin import SkeletonKinematics

    kin = SkeletonKinematics(seq.side)
    return [kin.compute(to_skeleton3d(p), seq.up_cam) for p in seq.points]


def world_to_virtual_camera(points_w: np.ndarray, up_w: np.ndarray, distance_m: float = 2.3,
                            yaw_deg: float = 0.0) -> np.ndarray:
    """Place a virtual D455 in front of the subject (mocap world -> RealSense camera frame).

    The camera sits ``distance_m`` in front of the mid-shoulder of the first valid frame, at shoulder
    height, looking back at the subject; ``yaw_deg`` rotates it around the subject (viewpoint jitter).
    """
    from physiobuddy_hub.datatypes import L_SHOULDER, R_SHOULDER

    up = np.asarray(up_w, float) / np.linalg.norm(up_w)
    ok = np.all(np.isfinite(points_w[:, [L_SHOULDER, R_SHOULDER]]), axis=(1, 2))
    if not ok.any():
        raise ValueError("no frame with both shoulders")
    f0 = points_w[int(np.argmax(ok))]
    right = f0[R_SHOULDER] - f0[L_SHOULDER]
    right = right - np.dot(right, up) * up
    right /= np.linalg.norm(right)
    anterior = np.cross(up, right)
    a = np.radians(yaw_deg)
    anterior = np.cos(a) * anterior + np.sin(a) * np.cross(up, anterior)
    centre = (f0[L_SHOULDER] + f0[R_SHOULDER]) / 2
    cam_pos = centre + distance_m * anterior
    z = -anterior                      # camera looks at the subject
    y = -up                            # image down
    x = np.cross(y, z)                 # image right (= subject's left when facing the camera)
    R = np.vstack([x, y, z])
    return (points_w - cam_pos) @ R.T


def resample(x: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    """Linear resampling along axis 0 (NaN-free input)."""
    n_out = max(2, int(round(len(x) * fs_out / fs_in)))
    t_in = np.arange(len(x)) / fs_in
    t_out = np.arange(n_out) / fs_out
    t_out = t_out[t_out <= t_in[-1]]
    return np.stack([np.interp(t_out, t_in, x[:, j]) for j in range(x.shape[1])], axis=1)
