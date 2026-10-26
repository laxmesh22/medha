"""Slice an STL with a horizontal plane and draw the 2D cross-section to scale (1 mm grid), for measuring.

    hub/.venv/Scripts/python.exe -I tools/cad/stl_section.py part.stl z_mm out.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from stl_report import read_stl  # noqa: E402


def section(tris: np.ndarray, z: float) -> np.ndarray:
    """Segments (M, 2, 2) where the plane z cuts the triangles."""
    segs = []
    for t in tris:
        d = t[:, 2] - z
        pts = []
        for i in range(3):
            a, b = t[i], t[(i + 1) % 3]
            da, db = d[i], d[(i + 1) % 3]
            if (da < 0) != (db < 0):
                s = da / (da - db)
                pts.append(a[:2] + s * (b[:2] - a[:2]))
        if len(pts) == 2:
            segs.append(pts)
    return np.asarray(segs)


def main():
    stl, z, out = Path(sys.argv[1]), float(sys.argv[2]), Path(sys.argv[3])
    tris = read_stl(stl)
    segs = section(tris, z)
    lo = segs.reshape(-1, 2).min(0) - 3
    hi = segs.reshape(-1, 2).max(0) + 3
    px = 12  # pixels per mm
    w, h = (np.ceil((hi - lo) * px)).astype(int)
    img = np.full((h, w, 3), 255, np.uint8)
    for gx in range(int(lo[0]), int(hi[0]) + 1):
        x = int((gx - lo[0]) * px)
        cv2.line(img, (x, 0), (x, h), (225, 225, 225) if gx % 10 else (170, 170, 170), 1)
    for gy in range(int(lo[1]), int(hi[1]) + 1):
        y = h - int((gy - lo[1]) * px)
        cv2.line(img, (0, y), (w, y), (225, 225, 225) if gy % 10 else (170, 170, 170), 1)
    for a, b in segs:
        pa = (int((a[0] - lo[0]) * px), h - int((a[1] - lo[1]) * px))
        pb = (int((b[0] - lo[0]) * px), h - int((b[1] - lo[1]) * px))
        cv2.line(img, pa, pb, (20, 60, 200), 2)
    cv2.putText(img, f"{stl.stem} section z={z} mm  (grid 1 mm, bold 10 mm)", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.imwrite(str(out), img)
    print(f"{len(segs)} segments, extent {np.round(hi - lo - 6, 2)} mm, origin {np.round(lo + 3, 2)}")


if __name__ == "__main__":
    main()
