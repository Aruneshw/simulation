"""Browser-friendly parametric CAD on top of the Manifold mesh kernel.

Supported: box / cylinder / sphere primitives, sketch extrusion (rectangles,
circles, polygons; additional sketch shapes become holes), boolean union /
difference / intersection, translate / rotate. Parameters are named
dimensions referenced as "$name" or simple expressions like "$width - 2*$wall".

Results are triangle meshes (exact for planar faces, faceted for curved ones).
For B-rep STEP output and fillets/chamfers use the FreeCAD adapter.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any

import numpy as np

from ...schemas.project import CadPart, Feature
from ..mass import MATERIALS, mesh_mass_properties

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


class CadError(ValueError):
    pass


def _eval_expr(expr: str, params: dict[str, float]) -> float:
    """Safe arithmetic evaluator for parameter expressions (no names besides parameters, no calls)."""
    src = expr.replace("$", "")
    try:
        node = ast.parse(src, mode="eval").body
    except SyntaxError as e:
        raise CadError(f"invalid expression '{expr}'") from e

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in params:
                return float(params[n.id])
            if n.id == "pi":
                return math.pi
            raise CadError(f"unknown parameter '{n.id}' in '{expr}'")
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise CadError(f"unsupported syntax in '{expr}'")
    return ev(node)


def resolve(value: Any, params: dict[str, float]) -> Any:
    if isinstance(value, str) and ("$" in value or any(c.isdigit() for c in value)):
        return _eval_expr(value, params)
    if isinstance(value, list):
        return [resolve(v, params) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, params) for k, v in value.items()}
    return value


def _cross_section(shapes, params):
    import manifold3d as m3d  # noqa: PLC0415
    cs = None
    for i, sh in enumerate(shapes):
        p = resolve(sh.params, params)
        if sh.type == "rect":
            c = m3d.CrossSection.square([p["w"], p["h"]], center=True).translate([p.get("cx", 0.0), p.get("cy", 0.0)])
        elif sh.type == "circle":
            c = m3d.CrossSection.circle(p["r"], int(p.get("segments", 48))).translate([p.get("cx", 0.0), p.get("cy", 0.0)])
        elif sh.type == "polygon":
            c = m3d.CrossSection([[tuple(pt) for pt in p["points"]]])
        else:
            raise CadError(f"unsupported sketch shape {sh.type}")
        cs = c if cs is None else (cs - c)  # first shape is the profile, the rest are holes
    if cs is None:
        raise CadError("empty sketch")
    return cs


def build_part(part: CadPart):
    """Evaluate the feature tree and return a manifold3d.Manifold."""
    import manifold3d as m3d  # noqa: PLC0415
    if part.kind != "parametric":
        raise CadError("imported meshes are not parametric; they cannot be regenerated")
    params = dict(part.parameters)
    bodies: dict[str, Any] = {}
    last = None
    for f in part.features:
        p = resolve(f.params, params)
        if f.op == "box":
            b = m3d.Manifold.cube([p["x"], p["y"], p["z"]], center=bool(p.get("center", True)))
        elif f.op == "cylinder":
            b = m3d.Manifold.cylinder(p["h"], p["r"], p.get("r_top", p["r"]), int(p.get("segments", 48)),
                                      bool(p.get("center", True)))
        elif f.op == "sphere":
            b = m3d.Manifold.sphere(p["r"], int(p.get("segments", 48)))
        elif f.op == "extrude":
            b = m3d.Manifold.extrude(_cross_section(f.sketch or [], params), p["height"])
            if p.get("center"):
                b = b.translate([0, 0, -p["height"] / 2])
        elif f.op in ("union", "difference", "intersection"):
            ops = [bodies[o] for o in f.operands if o in bodies]
            if len(ops) < 2:
                raise CadError(f"{f.id}: boolean needs two existing operands, got {f.operands}")
            b = ops[0]
            for o in ops[1:]:
                b = b + o if f.op == "union" else (b - o if f.op == "difference" else b ^ o)
        elif f.op in ("translate", "rotate"):
            src = bodies.get(f.operands[0]) if f.operands else last
            if src is None:
                raise CadError(f"{f.id}: nothing to transform")
            b = src.translate(p["v"]) if f.op == "translate" else src.rotate(p["deg"])
        else:
            raise CadError(f"unknown op {f.op}")
        if f.params.get("at") is not None and f.op not in ("translate", "rotate"):
            b = b.translate(resolve(f.params["at"], params))
        bodies[f.id] = b
        last = b
    if part.result:
        if part.result not in bodies:
            raise CadError(f"result feature '{part.result}' not found")
        return bodies[part.result]
    if last is None:
        raise CadError("part has no features")
    return last


def mesh_arrays(manifold) -> tuple[np.ndarray, np.ndarray]:
    mesh = manifold.to_mesh()
    v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    f = np.asarray(mesh.tri_verts, dtype=np.int64)
    return v, f


def part_report(part: CadPart) -> dict:
    """Mesh + mass properties for the viewer and the robot model."""
    man = build_part(part)
    v, f = mesh_arrays(man)
    density = MATERIALS.get(part.material, 1000.0)
    mp = mesh_mass_properties(v, f, density)
    lo, hi = v.min(axis=0), v.max(axis=0)
    return {"id": part.id, "kind": part.kind, "material": part.material, "density": density,
            "volume_m3": mp["volume"], "kernel_volume_m3": float(man.volume()), "mass_kg": mp["mass"],
            "center_of_mass": mp["com"], "inertia": mp["inertia"], "bbox": [lo.tolist(), hi.tolist()],
            "triangles": int(len(f)), "genus": int(man.genus()),
            "mesh": {"positions": np.round(v, 6).ravel().tolist(), "indices": f.ravel().tolist()},
            "note": "Mass properties computed from the tessellated solid; curved faces are faceted."}


def interference(parts: list[tuple[str, Any]], tol: float = 1e-9) -> list[dict]:
    """Pairwise interference volume between placed manifolds [(name, manifold), ...]."""
    out = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i][1], parts[j][1]
            inter = a ^ b
            vol = float(inter.volume())
            if vol > tol:
                out.append({"a": parts[i][0], "b": parts[j][0], "volume_m3": vol})
    return out


def clearance(parts: list[tuple[str, Any]]) -> list[dict]:
    """Axis-aligned bounding-box gap between parts (conservative lower bound of true clearance)."""
    res = []
    boxes = []
    for name, m in parts:
        v, _ = mesh_arrays(m)
        boxes.append((name, v.min(axis=0), v.max(axis=0)))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            n1, lo1, hi1 = boxes[i]
            n2, lo2, hi2 = boxes[j]
            gap = np.maximum(0, np.maximum(lo1 - hi2, lo2 - hi1))
            res.append({"a": n1, "b": n2, "aabb_gap_m": float(np.linalg.norm(gap))})
    return res


def placed(part: CadPart, xyz, rpy_deg=(0, 0, 0)):
    return build_part(part).rotate(list(rpy_deg)).translate(list(xyz))


def example_parts() -> list[CadPart]:
    plate = CadPart(id="chassis_plate", name="Chassis plate", material="aluminium",
                    parameters={"length": 0.40, "width": 0.30, "thickness": 0.004, "hole_r": 0.0025, "inset": 0.02},
                    features=[Feature(id="profile", op="extrude", params={"height": "$thickness"}, sketch=[
                        {"type": "rect", "params": {"w": "$length", "h": "$width"}},
                        {"type": "circle", "params": {"r": "$hole_r", "cx": "$length/2-$inset", "cy": "$width/2-$inset"}},
                        {"type": "circle", "params": {"r": "$hole_r", "cx": "-$length/2+$inset", "cy": "$width/2-$inset"}},
                        {"type": "circle", "params": {"r": "$hole_r", "cx": "$length/2-$inset", "cy": "-$width/2+$inset"}},
                        {"type": "circle", "params": {"r": "$hole_r", "cx": "-$length/2+$inset", "cy": "-$width/2+$inset"}},
                        {"type": "rect", "params": {"w": 0.06, "h": 0.04, "cx": 0, "cy": 0}},
                    ])])
    bracket = CadPart(id="motor_bracket", name="Motor L-bracket", material="aluminium",
                      parameters={"w": 0.045, "t": 0.003, "h": 0.045, "bore": 0.006},
                      features=[Feature(id="base", op="box", params={"x": "$w", "y": "$w", "z": "$t", "center": False}),
                                Feature(id="upright", op="box", params={"x": "$t", "y": "$w", "z": "$h", "center": False}),
                                Feature(id="l", op="union", operands=["base", "upright"]),
                                Feature(id="bore", op="cylinder", params={"h": 0.02, "r": "$bore", "center": True}),
                                Feature(id="bore_r", op="rotate", params={"deg": [0, 90, 0]}, operands=["bore"]),
                                Feature(id="bore_p", op="translate", params={"v": [0.0015, "$w/2", "$h*0.6"]}, operands=["bore_r"]),
                                Feature(id="final", op="difference", operands=["l", "bore_p"])], result="final")
    wheel = CadPart(id="wheel_100", name="Wheel 100 mm", material="polyurethane",
                    parameters={"r": 0.05, "width": 0.032, "hub_r": 0.004},
                    features=[Feature(id="tyre", op="extrude", params={"height": "$width", "center": True}, sketch=[
                        {"type": "circle", "params": {"r": "$r", "segments": 64}},
                        {"type": "circle", "params": {"r": "$hub_r", "segments": 24}}])])
    return [plate, bracket, wheel]
