"""Mesh import/export (STL ASCII/binary, OBJ). Imported meshes are geometry only:
they are flagged non-parametric and are never presented as editable solids."""
from __future__ import annotations

import struct

import numpy as np


def to_stl_ascii(vertices: np.ndarray, faces: np.ndarray, name: str = "part") -> str:
    out = [f"solid {name}"]
    for f in faces:
        a, b, c = vertices[f[0]], vertices[f[1]], vertices[f[2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        n = n / ln if ln > 0 else n
        out.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n    outer loop")
        for p in (a, b, c):
            out.append(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}")
        out.append("    endloop\n  endfacet")
    out.append(f"endsolid {name}")
    return "\n".join(out) + "\n"


def to_obj(vertices: np.ndarray, faces: np.ndarray, name: str = "part") -> str:
    lines = [f"o {name}"] + [f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in vertices]
    lines += [f"f {f[0] + 1} {f[1] + 1} {f[2] + 1}" for f in faces]
    return "\n".join(lines) + "\n"


def parse_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Parse ASCII or binary STL and weld duplicate vertices."""
    tris: list[list[float]] = []
    head = data[:512].lstrip().lower()
    is_ascii = head.startswith(b"solid") and b"facet" in data[:2048].lower()
    if is_ascii:
        for line in data.decode("utf-8", "replace").splitlines():
            parts = line.strip().split()
            if parts and parts[0] == "vertex":
                tris.append([float(x) for x in parts[1:4]])
    else:
        if len(data) < 84:
            raise ValueError("file too short to be an STL")
        n = struct.unpack("<I", data[80:84])[0]
        if len(data) < 84 + n * 50:
            raise ValueError("binary STL truncated")
        arr = np.frombuffer(data, dtype=np.uint8, count=n * 50, offset=84).reshape(n, 50)
        verts = arr[:, 12:48].copy().view("<f4").reshape(n, 3, 3)
        tris = verts.reshape(-1, 3).astype(np.float64).tolist()
    if not tris or len(tris) % 3:
        raise ValueError("no triangles found")
    pts = np.asarray(tris)
    uniq, inv = np.unique(np.round(pts, 9), axis=0, return_inverse=True)
    return uniq, inv.reshape(-1, 3)


def parse_obj(text: str) -> tuple[np.ndarray, np.ndarray]:
    verts, faces = [], []
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            verts.append([float(x) for x in p[1:4]])
        elif p[0] == "f":
            idx = [int(x.split("/")[0]) for x in p[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not faces:
        raise ValueError("no faces found")
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def mesh_check(vertices: np.ndarray, faces: np.ndarray) -> dict:
    """Watertightness: every edge shared by exactly two faces with opposite orientation."""
    edges = {}
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            edges[(int(a), int(b))] = edges.get((int(a), int(b)), 0) + 1
    boundary = sum(1 for (a, b) in edges if (b, a) not in edges)
    nonmanifold = sum(1 for v in edges.values() if v > 1)
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    size = (hi - lo)
    return {"vertices": int(len(vertices)), "triangles": int(len(faces)), "watertight": boundary == 0 and nonmanifold == 0,
            "open_edges": boundary, "non_manifold_edges": nonmanifold, "bbox_size": size.tolist(),
            "unit_hint": "mm?" if size.max() > 5 else "m"}
