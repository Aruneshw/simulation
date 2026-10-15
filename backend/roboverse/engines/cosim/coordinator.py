"""Co-simulation coordinator.

Integration strategy (documented and reported with every run):
- Fixed macro step `dt` (physics + electrical every step); slower subsystems run
  at their own rate on the same clock, aligned to macro-step boundaries.
- Loosely coupled (explicit / Jacobi-style): subsystems exchange values through
  the bus with zero-order hold. Inputs produced *later* in the macro-step order
  are consumed with a one-step delay; the coordinator reports each such edge.
- Initialization sequence: twin resolution -> backend init -> subsystems in
  order -> contract validation -> t = 0 snapshot.
- Error handling: an exception in a required subsystem stops the run with
  status 'error'; optional subsystems (mapping, perception) are disabled and logged.
"""
from __future__ import annotations

import csv
import io
import math
from typing import Callable, Optional

import numpy as np

from ...library.registry import Registry
from ...schemas.project import Project
from ..physics.backends import make_backend
from ..twin import resolve_twin
from ..world.geometry import obstacles_from_world
from .bus import Bus
from .subsystems import (ElectricalSubsystem, EncoderSubsystem, FirmwareSubsystem, ImuSubsystem, LidarSubsystem,
                         LocalControllerSubsystem, LocalizationSubsystem, MappingSubsystem, MissionSubsystem,
                         PerceptionSubsystem, PhysicsSubsystem, PlannerSubsystem, SimContext, Subsystem,
                         WorldSubsystem)

ORDER = [WorldSubsystem, EncoderSubsystem, ImuSubsystem, LidarSubsystem, LocalizationSubsystem, MissionSubsystem,
         PlannerSubsystem, LocalControllerSubsystem, FirmwareSubsystem, ElectricalSubsystem, PhysicsSubsystem,
         MappingSubsystem, PerceptionSubsystem]


def start_pose(project: Project) -> tuple[float, float, float]:
    s = next((o for o in project.world.objects if o.kind == "robot_start"), None)
    return (s.pose.xyz[0], s.pose.xyz[1], s.pose.rpy[2]) if s else (0.0, 0.0, 0.0)


def estimate_base_load(project: Project, registry: Registry) -> float:
    """Electronics load (W) excluding motors, from the circuit power budget."""
    if project.robot.power.base_load_w is not None:
        return project.robot.power.base_load_w
    from ..circuit.compat import check_circuit  # noqa: PLC0415
    budget = check_circuit(project.circuit, registry)["power_budget"]
    b = budget.get("battery")
    if not b:
        return 0.0
    motor_typ = 0.0
    for r in budget["rails"]:
        for ld in r["loads"]:
            if "stall" in ld.get("note", ""):
                motor_typ += ld["typ_a"]
    return max(0.0, (b["current_typ_a"] - motor_typ) * (b["v_nominal"] or 0))


class Coordinator:
    def __init__(self, project: Project, registry: Registry,
                 on_frame: Optional[Callable[[dict], None]] = None, enable_optional: bool = True):
        self.project = project
        self.registry = registry
        self.on_frame = on_frame
        self.enable_optional = enable_optional
        self.cfg = project.simulation
        self.bus = Bus()
        self.t = 0.0
        self.step_n = 0
        self.status = "created"
        self.rows: list[dict] = []
        self.init_report: dict = {}
        self.subs: list[Subsystem] = []
        self._next_t: dict[str, float] = {}
        self._frame_events = 0

    # ------------------------------------------------------------ init --
    def initialize(self) -> dict:
        cfg = self.cfg
        rng = np.random.default_rng(cfg.seed)
        bindings, twin_issues, _ = resolve_twin(self.project, self.registry)
        obstacles = obstacles_from_world(self.project.world)
        backend = make_backend(cfg.physics_backend)
        st = start_pose(self.project)
        backend.initialize(self.project.robot, self.project.world, obstacles, st, cfg.dt)
        refl = {}
        from ..power.models import DCMotor  # noqa: PLC0415
        for b in bindings:
            if b.motor is not None:
                try:
                    refl[b.joint] = DCMotor.from_component(b.motor).inertia * self.project.robot.drivetrain.gear_ratio ** 2
                except ValueError:
                    pass
        backend.set_reflected_inertia(refl)
        self.ctx = SimContext(project=self.project, registry=self.registry, rng=rng, obstacles=obstacles,
                              backend=backend, bindings=bindings, start=st,
                              base_load_w=estimate_base_load(self.project, self.registry))
        sequence = []
        for cls in ORDER:
            sub = cls()
            if sub.optional and not self.enable_optional:
                continue
            try:
                sub.initialize(self.ctx, self.bus)
            except Exception as e:  # noqa: BLE001
                if sub.optional:
                    self.ctx.event(0.0, "subsystem_disabled", f"{sub.name}: {e}", "warning")
                    continue
                self.status = "error"
                raise RuntimeError(f"Initialisation of '{sub.name}' failed: {e}") from e
            self.subs.append(sub)
            self._next_t[sub.name] = 0.0
            sequence.append({"name": sub.name, "rate_hz": sub.rate_hz or round(1 / cfg.dt), "fidelity": sub.fidelity})
        # contract validation
        producers: dict[str, list[str]] = {}
        position = {s.name: i for i, s in enumerate(self.subs)}
        for s in self.subs:
            for o in s.outputs:
                producers.setdefault(o, []).append(s.name)
        edges, missing = [], []
        for s in self.subs:
            for i in s.inputs:
                prods = producers.get(i)
                if not prods:
                    missing.append(f"{s.name} <- {i}")
                    continue
                for p in prods:
                    same = position[p] < position[s.name]
                    edges.append({"signal": i, "from": p, "to": s.name, "coupling": "same_step" if same else "one_step_delay"})
        self.init_report = {
            "strategy": "fixed-step, loosely coupled (explicit), zero-order hold between subsystems",
            "macro_dt": cfg.dt, "backend": backend.name, "backend_fidelity": backend.fidelity,
            "sequence": sequence, "contract": edges, "missing_inputs": missing,
            "twin": [b.to_dict() for b in bindings], "twin_issues": [i.model_dump() for i in twin_issues],
            "start_pose": list(st), "base_load_w": round(self.ctx.base_load_w, 2), "seed": cfg.seed,
            "result_labels": {"physics": "simulation", "electrical": "analytical_model", "sensors": "simulated",
                              "perception": "ai_estimate (compare with ground truth)"},
        }
        if missing:
            self.ctx.event(0.0, "contract", f"Inputs without producer (defaults used): {', '.join(missing)}", "warning")
        self.status = "ready"
        self._snapshot(force=True)
        return self.init_report

    # ------------------------------------------------------------ step --
    def step(self) -> None:
        dt = self.cfg.dt
        self.t = round(self.t + dt, 9)
        self.step_n += 1
        t = self.t
        failed: list[Subsystem] = []
        for s in self.subs:
            if s.rate_hz is None or t + 1e-9 >= self._next_t[s.name]:
                sub_dt = dt if s.rate_hz is None else 1.0 / s.rate_hz
                try:
                    s.step(t, sub_dt, self.bus)
                except Exception as e:  # noqa: BLE001
                    if s.optional:
                        self.ctx.event(t, "subsystem_error", f"{s.name} disabled: {e}", "warning")
                        failed.append(s)
                        continue
                    self.status = "error"
                    self.ctx.event(t, "subsystem_error", f"{s.name}: {type(e).__name__}: {e}", "critical")
                    raise
                if s.rate_hz:
                    self._next_t[s.name] += 1.0 / s.rate_hz
        for s in failed:
            self.subs.remove(s)
        self._snapshot()

    def _snapshot(self, force: bool = False) -> None:
        every = max(1, int(round(1.0 / (self.cfg.telemetry_hz * self.cfg.dt))))
        if not force and self.step_n % every:
            return
        b = self.bus
        tp, est = b.get("truth.pose"), b.get("est.pose")
        tw = b.get("truth.twist")
        row = {"t": round(self.t, 4), "x": tp["x"], "y": tp["y"], "theta": tp["theta"], "v": tw["v"], "w": tw["w"],
               "est_x": est["x"], "est_y": est["y"], "est_theta": est["theta"],
               "loc_err": math.hypot(tp["x"] - est["x"], tp["y"] - est["y"]),
               "bus_v": b.get("elec.bus_v"), "bus_i": b.get("elec.bus_i"), "soc": b.get("elec.soc"),
               "cmd_v": (b.get("cmd.vel") or (0, 0))[0], "cmd_w": (b.get("cmd.vel") or (0, 0))[1],
               "min_front": b.get("lidar.min_front"), "mission": b.get("mission.state"),
               "nav": b.get("nav.status"), "estop": bool(b.get("mission.estop")), "collisions": self.ctx.metrics.get("collisions", 0)}
        motors = {}
        for s in self.subs:
            if isinstance(s, ElectricalSubsystem):
                for j in s.ch:
                    m = b.get(f"motor.{j}")
                    if m:
                        motors[j] = m
                        short = j.replace("_joint", "")
                        row[f"{short}_rpm"] = m["rpm"]
                        row[f"{short}_i"] = m["i"]
                        row[f"{short}_torque"] = m["torque"]
                        row[f"{short}_temp"] = m["temp_c"]
                        row[f"{short}_duty"] = m["duty"]
        self.rows.append(row)
        if self.on_frame:
            frame = {"type": "frame", "t": row["t"], "row": row, "motors": motors,
                     "dynamic": b.get("world.dynamic"), "path": b.get("nav.path"),
                     "events": self.ctx.events[self._frame_events:]}
            self._frame_events = len(self.ctx.events)
            r = b.get("lidar.ranges")
            lid = next((s for s in self.subs if isinstance(s, LidarSubsystem)), None)
            if r is not None and lid is not None:
                k = max(1, len(r) // 90)
                ang = lid.angles[::k] + tp["theta"]
                rr = r[::k]
                frame["scan"] = [[round(tp["x"] + float(d) * math.cos(a), 3), round(tp["y"] + float(d) * math.sin(a), 3),
                                  int(d < lid.r_max - 1e-3)] for a, d in zip(ang, rr)]
            dets = b.get("perception.detections")
            if dets:
                frame["detections"] = dets
            self.on_frame(frame)

    # ------------------------------------------------------------- run --
    def run(self, duration: Optional[float] = None, should_stop: Optional[Callable[[], bool]] = None,
            pace: Optional[Callable[[float], None]] = None) -> dict:
        if self.status == "created":
            self.initialize()
        self.status = "running"
        end = duration if duration is not None else self.cfg.duration
        steps = int(round(end / self.cfg.dt))
        try:
            for _ in range(steps):
                if should_stop and should_stop():
                    self.status = "stopped"
                    break
                self.step()
                if pace:
                    pace(self.t)
                if self.bus.get("mission.state") in ("complete", "docked", "failed") and \
                        self.cfg.scenario.mode not in ("teleop", "open_loop"):
                    # let the robot settle briefly, then finish
                    self._done_at = getattr(self, "_done_at", self.t)
                    if self.t - self._done_at > 1.0:
                        break
            if self.status == "running":
                self.status = "completed"
        except Exception:  # noqa: BLE001
            self.status = "error"
        return self.results()

    # --------------------------------------------------------- results --
    def results(self) -> dict:
        rows = self.rows
        m = dict(self.ctx.metrics)
        if rows:
            dist = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(rows, rows[1:]))
            m["distance_m"] = round(dist, 3)
            m["sim_time_s"] = round(self.t, 3)
            m["loc_error_final_m"] = round(rows[-1]["loc_err"], 4)
            m["loc_rmse_m"] = round(math.sqrt(sum(r["loc_err"] ** 2 for r in rows) / len(rows)), 4)
            if m.get("planned_length_m"):
                m["path_efficiency"] = round(m["planned_length_m"] / dist, 3) if dist > 0 else None
            fronts = [r["min_front"] for r in rows if r["min_front"] is not None and math.isfinite(r["min_front"])]
            m["min_front_clearance_m"] = round(min(fronts), 3) if fronts else None
            temps = [v for r in rows for k, v in r.items() if k.endswith("_temp")]
            m["max_motor_temp_c_estimate"] = round(max(temps), 1) if temps else None
            currs = [r["bus_i"] for r in rows if r["bus_i"] is not None]
            m["peak_bus_current_a"] = round(max(currs), 3) if currs else None
            m["final_soc"] = rows[-1]["soc"]
        for s in self.subs:
            if isinstance(s, ElectricalSubsystem) and s.battery:
                m["energy_wh"] = round(s.battery.energy_wh, 4)
                m["charge_ah"] = round(s.battery.ah_used, 5)
            if isinstance(s, PerceptionSubsystem) and s.scores:
                ps = [x["precision"] for x in s.scores if x["precision"] is not None]
                rc = [x["recall"] for x in s.scores if x["recall"] is not None]
                pe = [x["mean_position_error_m"] for x in s.scores if x["mean_position_error_m"] is not None]
                m["perception"] = {"mean_precision": round(float(np.mean(ps)), 3) if ps else None,
                                   "mean_recall": round(float(np.mean(rc)), 3) if rc else None,
                                   "mean_position_error_m": round(float(np.mean(pe)), 3) if pe else None,
                                   "frames": len(s.scores)}
        m["success"] = (self.status == "completed" and m.get("goals_total", 0) == m.get("goals_reached", 0)
                        and m.get("collisions", 0) == 0)
        return {"status": self.status, "metrics": m, "events": self.ctx.events, "init": self.init_report,
                "telemetry_rows": len(rows)}

    def telemetry_csv(self) -> str:
        if not self.rows:
            return ""
        keys = list(self.rows[0].keys())
        for r in self.rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=keys)
        w.writeheader()
        for r in self.rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
        return buf.getvalue()

    def map_snapshot(self) -> Optional[dict]:
        for s in self.subs:
            if isinstance(s, MappingSubsystem):
                p = s.map.probabilities()
                return {"origin": list(s.map.gm.origin), "resolution": s.map.gm.resolution, "shape": list(p.shape),
                        "data": (np.round(p * 100).astype(int)).ravel().tolist(),
                        "label": "estimated map (log-odds at estimated pose)"}
        return None


def run_headless(project: Project, registry: Registry, duration: Optional[float] = None) -> tuple[dict, str]:
    c = Coordinator(project, registry)
    c.initialize()
    res = c.run(duration)
    return res, c.telemetry_csv()
