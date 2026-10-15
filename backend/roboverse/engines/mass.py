"""Mass properties for primitives and triangle meshes."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

# kg/m^3 — typical handbook values
MATERIALS = {
    "aluminium": 2700.0, "steel": 7850.0, "stainless": 8000.0, "abs": 1050.0, "pla": 1240.0, "petg": 1270.0,
    "nylon": 1150.0, "acrylic": 1180.0, "plywood": 600.0, "mdf": 750.0, "rubber": 1100.0, "polyurethane": 1200.0,
    "carbon_fiber": 1600.0, "copper": 8960.0, "fr4": 1850.0,
}


def primitive_volume(gtype: str, size: list[float]) -> float:
    if gtype == "box":
        return size[0] * size[1] * size[2]
    if gtype == "cylinder":
        return math.pi * size[0] ** 2 * size[2]
    if gtype == "sphere":
        return 4.0 / 3.0 * math.pi * size[0] ** 3
    return 0.0


def primitive_inertia(gtype: str, size: list[float], mass: float) -> list[float]:
    """[ixx, iyy, izz, ixy, ixz, iyz] about the centroid. Cylinder axis = z."""
    if gtype == "box":
        x, y, z = size
        return [mass / 12 * (y * y + z * z), mass / 12 * (x * x + z * z), mass / 12 * (x * x + y * y), 0, 0, 0]
    if gtype == "cylinder":
        r, h = size[0], size[2]
        i = mass / 12 * (3 * r * r + h * h)
        return [i, i, mass / 2 * r * r, 0, 0, 0]
    if gtype == "sphere":
        i = 2 / 5 * mass * size[0] ** 2
        return [i, i, i, 0, 0, 0]
    return [1e-6, 1e-6, 1e-6, 0, 0, 0]


def mesh_mass_properties(vertices: np.ndarray, faces: np.ndarray, density: float) -> dict:
    """Volume, centroid and inertia tensor of a closed, consistently oriented triangle mesh
    via signed tetrahedra (divergence theorem)."""
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    cross = np.cross(v1, v2)
    vol6 = np.einsum("ij,ij->i", v0, cross)
    volume = vol6.sum() / 6.0
    if abs(volume) < 1e-15:
        return {"volume": 0.0, "mass": 0.0, "com": [0, 0, 0], "inertia": [0] * 6, "watertight_estimate": False}
    com = ((v0 + v1 + v2) * vol6[:, None]).sum(axis=0) / (24.0 * volume)
    # second moments using canonical tetrahedron integrals
    def integ(a, b):
        return (vol6 / 120.0 * (
            2 * (v0[:, a] * v0[:, b] + v1[:, a] * v1[:, b] + v2[:, a] * v2[:, b])
            + v0[:, a] * v1[:, b] + v0[:, b] * v1[:, a] + v0[:, a] * v2[:, b] + v0[:, b] * v2[:, a]
            + v1[:, a] * v2[:, b] + v1[:, b] * v2[:, a])).sum()
    xx, yy, zz = integ(0, 0), integ(1, 1), integ(2, 2)
    xy, xz, yz = integ(0, 1), integ(0, 2), integ(1, 2)
    sign = 1.0 if volume > 0 else -1.0
    m = density * abs(volume)
    rho = density * sign
    ixx = rho * (yy + zz) - m * (com[1] ** 2 + com[2] ** 2)
    iyy = rho * (xx + zz) - m * (com[0] ** 2 + com[2] ** 2)
    izz = rho * (xx + yy) - m * (com[0] ** 2 + com[1] ** 2)
    ixy = -(rho * xy - m * com[0] * com[1])
    ixz = -(rho * xz - m * com[0] * com[2])
    iyz = -(rho * yz - m * com[1] * com[2])
    return {"volume": float(abs(volume)), "mass": float(m), "com": [float(c) for c in com],
            "inertia": [float(ixx), float(iyy), float(izz), float(ixy), float(ixz), float(iyz)],
            "watertight_estimate": True}


def inertia_valid(inertia: list[float]) -> Optional[str]:
    ixx, iyy, izz = inertia[:3]
    if min(ixx, iyy, izz) <= 0:
        return "principal moments must be positive"
    eps = 1e-12
    if ixx + iyy < izz - eps or ixx + izz < iyy - eps or iyy + izz < ixx - eps:
        return "violates triangle inequality (physically impossible)"
    return None
