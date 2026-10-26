"""Quick STL inspection for 3D-printed hardware parts: size, bodies, watertightness, volume, print estimate.

    hub/.venv/Scripts/python.exe -I tools/cad/stl_report.py part.stl [more.stl ...]

Pure numpy (binary or ASCII STL). Units are assumed to be millimetres (the STL convention for printing).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np

PLA_DENSITY = 1.24  # g/cm^3


def read_stl(path: Path) -> np.ndarray:
    """Return triangles as (N, 3, 3) float64."""
    data = path.read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n)
            return rec["v"].astype(np.float64)
    verts = [list(map(float, l.split()[1:4])) for l in data.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]
    return np.asarray(verts, dtype=np.float64).reshape(-1, 3, 3)


def weld(tris: np.ndarray, tol: float = 1e-4):
    """Merge coincident vertices -> (vertices (V,3), faces (N,3) int)."""
    flat = tris.reshape(-1, 3)
    key = np.round(flat / tol).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    verts = np.zeros((len(uniq), 3))
    np.add.at(verts, inv, flat)
    verts /= np.bincount(inv)[:, None]
    return verts, inv.reshape(-1, 3)


def components(faces: np.ndarray, n_verts: int) -> np.ndarray:
    """Connected bodies by shared vertices (union-find). Returns a body id per face."""
    parent = np.arange(n_verts)

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b, c in faces:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[rc] = ra
    roots = np.array([find(v) for v in range(n_verts)])
    return np.unique(roots[faces[:, 0]], return_inverse=True)[1]


def signed_volume(tris: np.ndarray) -> float:
    return float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)


def report(path: Path) -> None:
    tris = read_stl(path)
    verts, faces = weld(tris)
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, edge_count = np.unique(edges, axis=0, return_counts=True)
    open_edges = int((edge_count == 1).sum())
    non_manifold = int((edge_count > 2).sum())
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    area = float(0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1).sum())
    body = components(faces, len(verts))
    print(f"\n== {path.name}")
    print(f"triangles {len(tris)}, vertices {len(verts)}")
    print(f"size X {hi[0]-lo[0]:.2f} x Y {hi[1]-lo[1]:.2f} x Z {hi[2]-lo[2]:.2f} mm   (min {np.round(lo, 2)}, max {np.round(hi, 2)})")
    print(f"open edges {open_edges}, non-manifold edges {non_manifold} -> "
          f"{'watertight, printable' if open_edges == 0 and non_manifold == 0 else 'NOT watertight: needs repair'}")
    vol = signed_volume(tris)
    print(f"volume {abs(vol)/1000:.2f} cm^3 ({'outward normals' if vol > 0 else 'inverted normals'}), "
          f"surface {area/100:.1f} cm^2, solid PLA ~{abs(vol)/1000*PLA_DENSITY:.1f} g")
    n_body = body.max() + 1
    print(f"separate bodies: {n_body}")
    for b in range(n_body):
        t = tris[body == b]
        blo, bhi = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
        print(f"  body {b}: {len(t)} tris, size {bhi[0]-blo[0]:.2f} x {bhi[1]-blo[1]:.2f} x {bhi[2]-blo[2]:.2f} mm, "
              f"volume {abs(signed_volume(t))/1000:.2f} cm^3, min {np.round(blo, 1)}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(Path(p))
