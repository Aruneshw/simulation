"""Built-in circuit solver (Modified Nodal Analysis).

Supports DC operating point and transient analysis (backward Euler with
Newton-Raphson for diodes) for: R, C, L, independent V/I sources (DC and
PULSE), diodes (Shockley), switches, fuses (as resistors) and battery packs
(EMF + internal resistance). Anything else is reported as "not simulated"
rather than silently approximated. Use the ngspice adapter for BJTs, MOSFETs,
op-amp macro-models and anything beyond this subset.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ...library.registry import Registry
from ...schemas.project import Circuit
from .netlist import NetGraph, build_nets

VT = 0.025852  # thermal voltage at 300 K
GMIN = 1e-12


@dataclass
class Element:
    name: str
    kind: str  # R C L V I D SW
    n1: int
    n2: int
    value: float = 0.0
    params: dict = field(default_factory=dict)
    instance: str = ""


@dataclass
class Prepared:
    elements: list[Element]
    node_names: list[str]  # index -> name ; 0 = ground
    skipped: list[dict]
    errors: list[str]


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def prepare(circuit: Circuit, registry: Registry, graph: Optional[NetGraph] = None) -> Prepared:
    g = graph or build_nets(circuit, registry)
    ground_nets = {n.id for n in g.nets if any(p.pin.type == "ground" for p in n.pins)}
    names = ["0"]
    idx: dict[str, int] = {}
    for n in g.nets:
        if n.id in ground_nets:
            idx[n.id] = 0
    # Merge all ground nets only if they are explicitly ground-typed (same reference)
    for n in g.nets:
        if n.id not in idx:
            idx[n.id] = len(names)
            names.append(_sanitize(n.name or n.id) if n.name else n.id)
    elements: list[Element] = []
    skipped: list[dict] = []
    errors: list[str] = []
    if not ground_nets:
        errors.append("No ground reference: add a Ground symbol or a source with a ground pin.")
    extra = 0

    def node(inst: str, pin: str) -> int:
        return idx[g.pin_to_net[(inst, pin)]]

    for inst in circuit.instances:
        comp = g.components.get(inst.id)
        if comp is None:
            continue
        model = comp.sim_model or ""
        p = {**comp.params, **inst.params}
        pins = [pp.id for pp in comp.pins]
        try:
            if model == "spice:R":
                elements.append(Element(inst.id, "R", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p["resistance"]), instance=inst.id))
            elif model == "spice:C":
                elements.append(Element(inst.id, "C", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p["capacitance"]), instance=inst.id))
            elif model == "spice:L":
                elements.append(Element(inst.id, "L", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p["inductance"]), instance=inst.id))
            elif model == "spice:V":
                elements.append(Element(inst.id, "V", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p.get("voltage", 0.0)), instance=inst.id))
            elif model == "spice:VPULSE":
                elements.append(Element(inst.id, "V", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p.get("v1", 0.0)),
                                        {"pulse": {k: float(p[k]) for k in ("v1", "v2", "period", "duty")}}, inst.id))
            elif model == "spice:I":
                elements.append(Element(inst.id, "I", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p["current"]), instance=inst.id))
            elif model == "spice:D":
                elements.append(Element(inst.id, "D", node(inst.id, "A"), node(inst.id, "K"), 0.0,
                                        {"is": float(p.get("is", 1e-14)), "n": float(p.get("n", 1.0))}, inst.id))
            elif model == "spice:SW":
                closed = bool(p.get("closed", True))
                elements.append(Element(inst.id, "R", node(inst.id, pins[0]), node(inst.id, pins[1]),
                                        float(p.get("r_on", 0.01)) if closed else float(p.get("r_off", 1e9)), {"switch": closed}, inst.id))
            elif model == "protection:fuse_i2t":
                elements.append(Element(inst.id, "R", node(inst.id, pins[0]), node(inst.id, pins[1]), float(p.get("r_cold", 0.005)), {"fuse": True}, inst.id))
            elif model == "battery:thevenin":
                # EMF -> internal node -> R_int -> '+' pin
                extra += 1
                internal = len(names)
                names.append(f"{inst.id}_emf")
                v = comp.rating("v_nominal") or 0.0
                elements.append(Element(f"{inst.id}_E", "V", internal, node(inst.id, "-"), float(p.get("voltage", v)), instance=inst.id))
                elements.append(Element(f"{inst.id}_Rint", "R", internal, node(inst.id, "+"), float(p.get("r_internal", 0.05)), instance=inst.id))
            elif model == "spice:GND":
                pass
            else:
                skipped.append({"instance": inst.id, "component": comp.id, "support_status": comp.support_status.value,
                                "reason": f"no built-in circuit model ({model or 'none'})"})
        except KeyError as e:
            errors.append(f"{inst.id}: pin {e} is not connected to any net")
    return Prepared(elements, names, skipped, errors)


def pulse_value(pp: dict, t: float) -> float:
    period, duty = pp["period"], pp["duty"]
    return pp["v2"] if (t % period) < duty * period else pp["v1"]


class MNASolver:
    def __init__(self, prep: Prepared):
        self.p = prep
        self.n = len(prep.node_names) - 1
        self.branch = {}  # element name -> index of branch current unknown
        k = self.n
        for e in prep.elements:
            if e.kind in ("V", "L"):
                self.branch[e.name] = k
                k += 1
        self.size = k

    def _solve(self, t: float, dt: Optional[float], prev: Optional[np.ndarray], guess: np.ndarray) -> np.ndarray:
        x = guess.copy()
        for _ in range(100):
            A = np.zeros((self.size, self.size))
            b = np.zeros(self.size)
            for i in range(self.n):
                A[i, i] += GMIN

            def stamp_g(n1, n2, gval):
                if n1:
                    A[n1 - 1, n1 - 1] += gval
                if n2:
                    A[n2 - 1, n2 - 1] += gval
                if n1 and n2:
                    A[n1 - 1, n2 - 1] -= gval
                    A[n2 - 1, n1 - 1] -= gval

            def stamp_i(n1, n2, ival):  # current ival flowing n1 -> n2 through the element
                if n1:
                    b[n1 - 1] -= ival
                if n2:
                    b[n2 - 1] += ival

            def v(nn, vec):
                return vec[nn - 1] if nn else 0.0

            for e in self.p.elements:
                if e.kind == "R":
                    stamp_g(e.n1, e.n2, 1.0 / max(e.value, 1e-9))
                elif e.kind == "C":
                    if dt:
                        gc = e.value / dt
                        vprev = v(e.n1, prev) - v(e.n2, prev)
                        stamp_g(e.n1, e.n2, gc)
                        stamp_i(e.n1, e.n2, -gc * vprev)
                elif e.kind in ("V", "L"):
                    k = self.branch[e.name]
                    if e.n1:
                        A[e.n1 - 1, k] += 1
                        A[k, e.n1 - 1] += 1
                    if e.n2:
                        A[e.n2 - 1, k] -= 1
                        A[k, e.n2 - 1] -= 1
                    if e.kind == "V":
                        b[k] = pulse_value(e.params["pulse"], t) if "pulse" in e.params else e.value
                    elif dt:
                        A[k, k] -= e.value / dt
                        b[k] = -(e.value / dt) * prev[k]
                elif e.kind == "I":
                    stamp_i(e.n1, e.n2, e.value)
                elif e.kind == "D":
                    is_, nvt = e.params["is"], e.params["n"] * VT
                    vd = v(e.n1, x) - v(e.n2, x)
                    vcrit = nvt * math.log(nvt / (math.sqrt(2) * is_))
                    vd = min(vd, vcrit + 1.0)  # junction limiting to avoid exp overflow
                    ex = math.exp(min(vd / nvt, 80.0))
                    idd = is_ * (ex - 1)
                    gd = is_ * ex / nvt + GMIN
                    stamp_g(e.n1, e.n2, gd)
                    stamp_i(e.n1, e.n2, idd - gd * vd)
            try:
                xn = np.linalg.solve(A, b)
            except np.linalg.LinAlgError as err:
                raise ValueError("Singular circuit matrix (floating node or voltage-source loop)") from err
            has_d = any(e.kind == "D" for e in self.p.elements)
            if not has_d:
                return xn
            # damp large voltage steps for convergence
            step = xn - x
            mx = np.max(np.abs(step[: self.n])) if self.n else 0
            if mx > 0.5:
                xn = x + step * (0.5 / mx)
            if np.max(np.abs(xn - x)) < 1e-9:
                return xn
            x = xn
        return x

    def _report(self, x: np.ndarray, t: float = 0.0) -> dict:
        def v(nn):
            return float(x[nn - 1]) if nn else 0.0
        nodes = {self.p.node_names[i]: round(v(i), 6) for i in range(1, self.n + 1)}
        elems = {}
        for e in self.p.elements:
            vd = v(e.n1) - v(e.n2)
            if e.kind == "R":
                i = vd / max(e.value, 1e-9)
            elif e.kind in ("V", "L"):
                i = -float(x[self.branch[e.name]])  # current delivered out of + terminal
            elif e.kind == "I":
                i = e.value
            elif e.kind == "D":
                i = e.params["is"] * (math.exp(min(vd / (e.params["n"] * VT), 80)) - 1)
            else:
                i = 0.0
            elems[e.name] = {"kind": e.kind, "v": round(vd, 6), "i": float(f"{i:.6g}"), "p": float(f"{vd * i:.6g}")}
        return {"nodes": nodes, "elements": elems}

    def operating_point(self) -> dict:
        x = self._solve(0.0, None, None, np.zeros(self.size))
        return self._report(x)

    def transient(self, t_stop: float, dt: float, probes: Optional[list[str]] = None, max_points: int = 2000) -> dict:
        prev = self._solve(0.0, None, None, np.zeros(self.size))
        # BE transient starts from DC OP except that capacitors start discharged when requested
        steps = int(round(t_stop / dt))
        every = max(1, steps // max_points)
        names = probes or self.p.node_names[1:]
        out = {"t": [], **{n: [] for n in names}}
        idx = {nm: i for i, nm in enumerate(self.p.node_names)}
        x = prev
        for s in range(steps + 1):
            t = s * dt
            if s > 0:
                x = self._solve(t, dt, prev, prev)
                prev = x
            if s % every == 0:
                out["t"].append(round(t, 9))
                for n in names:
                    i = idx.get(n, 0)
                    out[n].append(float(x[i - 1]) if i else 0.0)
        return out


def simulate(circuit: Circuit, registry: Registry, analysis: str = "op", t_stop: float = 1e-3, dt: float = 1e-5,
             probes: Optional[list[str]] = None, initial_zero_caps: bool = True) -> dict:
    prep = prepare(circuit, registry)
    base = {"engine": "builtin-mna", "result_kind": "circuit_solver", "skipped": prep.skipped, "errors": prep.errors,
            "nodes": prep.node_names[1:]}
    if prep.errors:
        return {**base, "status": "error"}
    solver = MNASolver(prep)
    try:
        if analysis == "op":
            return {**base, "status": "ok", "analysis": "op", **solver.operating_point()}
        if initial_zero_caps:
            # transient from rest: solve with all sources at t=0 but capacitors discharged
            res = _transient_from_rest(solver, t_stop, dt, probes)
        else:
            res = solver.transient(t_stop, dt, probes)
        return {**base, "status": "ok", "analysis": "tran", "waveforms": res}
    except ValueError as e:
        return {**base, "status": "error", "errors": [str(e)]}


def _transient_from_rest(solver: MNASolver, t_stop: float, dt: float, probes: Optional[list[str]]) -> dict:
    steps = int(round(t_stop / dt))
    every = max(1, steps // 2000)
    names = probes or solver.p.node_names[1:]
    idx = {nm: i for i, nm in enumerate(solver.p.node_names)}
    prev = np.zeros(solver.size)
    out = {"t": [0.0], **{n: [0.0] for n in names}}
    for s in range(1, steps + 1):
        t = s * dt
        prev = solver._solve(t, dt, prev, prev)
        if s % every == 0:
            out["t"].append(round(t, 9))
            for n in names:
                i = idx.get(n, 0)
                out[n].append(float(prev[i - 1]) if i else 0.0)
    return out
