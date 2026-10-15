"""Co-simulation subsystems.

Data-exchange contract: each subsystem declares the bus signals it reads
(`inputs`) and writes (`outputs`). The coordinator verifies every input has a
producer and reports whether it is consumed in the same macro step or with a
one-step (zero-order-hold) delay.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from ...library.registry import Registry
from ...schemas.project import Project
from ..nav.navigation import (GridMap, LogOddsMap, OdomEKF, PurePursuit, ScanMatcher, astar, dilate, shortcut,
                              resample, soft_cost)
from ..perception import cluster_scan, score_detections
from ..physics.backends import PhysicsBackend
from ..power.models import Battery, DCMotor, Fuse, HBridge
from ..twin import ActuatorBinding
from ..world.geometry import Obstacle, distance_to, move_dynamic, raycast, rasterize
from .bus import Bus, DelayLine


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass
class SimContext:
    project: Project
    registry: Registry
    rng: np.random.Generator
    obstacles: list[Obstacle]
    backend: PhysicsBackend
    bindings: list[ActuatorBinding]
    start: tuple[float, float, float]
    events: list[dict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    estop: bool = False
    teleop_cmd: Optional[tuple[float, float]] = None
    base_load_w: float = 0.0
    charge_power_w: float = 0.0
    static_map: Optional[GridMap] = None

    def event(self, t: float, kind: str, message: str, severity: str = "info", **data) -> None:
        self.events.append({"t": round(t, 4), "kind": kind, "severity": severity, "message": message, **data})


class Subsystem:
    name = "subsystem"
    rate_hz: Optional[float] = None  # None = every macro step
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    fidelity = ""
    optional = False

    def initialize(self, ctx: SimContext, bus: Bus) -> None:
        self.ctx = ctx

    def step(self, t: float, dt: float, bus: Bus) -> None:  # pragma: no cover - interface
        raise NotImplementedError


# ------------------------------------------------------------------ world --

class WorldSubsystem(Subsystem):
    name = "world"
    outputs = ("world.dynamic",)
    fidelity = "scripted dynamic obstacles (patrol paths)"
    rate_hz = 50

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        self.dyn = [(o, next(ob for ob in ctx.obstacles if ob.id == o.id)) for o in ctx.project.world.objects
                    if o.motion and any(ob.id == o.id for ob in ctx.obstacles)]
        bus.put("world.dynamic", [], 0.0, self.name)

    def step(self, t, dt, bus):
        for o, ob in self.dyn:
            move_dynamic(o, ob, t)
        bus.put("world.dynamic", [{"id": ob.id, "x": ob.cx, "y": ob.cy, "r": ob.r} for _, ob in self.dyn], t, self.name)


# ---------------------------------------------------------------- sensors --

class EncoderSubsystem(Subsystem):
    name = "encoders"
    rate_hz = 200
    fidelity = "quadrature counts quantised to output-shaft CPR"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        self.cpr = {}
        for b in ctx.bindings:
            if b.motor is None or b.encoder_pin is None:
                continue
            cpr = b.motor.rating("encoder_cpr_output")
            sensor = next((s for s in ctx.project.robot.sensors if s.type == "encoder" and s.twin_id == b.twin_id), None)
            if sensor and sensor.params.get("cpr"):
                cpr = cpr or sensor.params["cpr"]
            self.cpr[b.joint] = (cpr or 1024) * ctx.project.robot.drivetrain.gear_ratio
        self.inputs = tuple(f"wheel.angle.{j}" for j in self.cpr)
        self.outputs = tuple(f"enc.{j}" for j in self.cpr)
        for j in self.cpr:
            bus.put(f"enc.{j}", 0, 0.0, self.name)

    def step(self, t, dt, bus):
        for j, cpr in self.cpr.items():
            ang = bus.get(f"wheel.angle.{j}", 0.0)
            bus.put(f"enc.{j}", int(math.floor(ang / (2 * math.pi) * cpr)), t, self.name)


class ImuSubsystem(Subsystem):
    name = "imu"
    inputs = ("truth.twist",)
    outputs = ("imu.gyro_z", "imu.accel_x")
    fidelity = "gyro z / accel x with white noise and constant bias"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        s = next((s for s in ctx.project.robot.sensors if s.type == "imu"), None)
        self.enabled = s is not None
        self.rate_hz = s.rate_hz if s else 100
        noise = ctx.project.simulation.sensor_noise
        self.sigma = (s.noise_std if s else 0.002) if noise else 0.0
        self.bias = float(ctx.rng.normal(0, 0.002)) if noise else 0.0
        bus.put("imu.gyro_z", None, 0.0, self.name)
        bus.put("imu.accel_x", None, 0.0, self.name)

    def step(self, t, dt, bus):
        if not self.enabled:
            return
        tw = bus.get("truth.twist")
        if tw is None:
            return
        n = self.ctx.rng.normal(0, self.sigma, 2) if self.sigma else (0, 0)
        bus.put("imu.gyro_z", tw["w"] + self.bias + n[0], t, self.name)
        bus.put("imu.accel_x", tw["ax"] + n[1] * 10, t, self.name)


class LidarSubsystem(Subsystem):
    name = "lidar"
    inputs = ("truth.pose", "world.dynamic")
    outputs = ("lidar.ranges", "lidar.min_front")
    fidelity = "2D ray casting against collision footprints at sensor height, Gaussian range noise"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        s = next((s for s in ctx.project.robot.sensors if s.type == "lidar"), None)
        self.enabled = s is not None
        self.rate_hz = s.rate_hz if s else 10
        p = s.params if s else {}
        n = int(p.get("beams", 180))
        fov = math.radians(p.get("fov_deg", 360))
        self.angles = np.linspace(-fov / 2, fov / 2, n, endpoint=fov < 2 * math.pi - 1e-6)
        self.r_max = float(p.get("range_max", 12.0))
        self.r_min = float(p.get("range_min", 0.15))
        self.sigma = (s.noise_std if s else 0.0) if ctx.project.simulation.sensor_noise else 0.0
        self.offset = s.pose.xyz if s else [0, 0, 0]
        self.z = 0.2
        if s:
            from ..description import link_world_poses  # noqa: PLC0415
            poses = link_world_poses(ctx.project.robot)
            if s.link in poses:
                lx, ly, lz = poses[s.link][0]
                self.offset = [lx, ly, lz]
                self.z = lz
        bus.put("lidar.ranges", None, 0.0, self.name)
        bus.put("lidar.min_front", math.inf, 0.0, self.name)

    def step(self, t, dt, bus):
        if not self.enabled:
            return
        pose = bus.get("truth.pose")
        x, y, th = pose["x"], pose["y"], pose["theta"]
        ox = x + math.cos(th) * self.offset[0] - math.sin(th) * self.offset[1]
        oy = y + math.sin(th) * self.offset[0] + math.cos(th) * self.offset[1]
        r = raycast(self.ctx.obstacles, ox, oy, self.angles + th, self.r_max, self.z)
        if self.sigma:
            r = r + self.ctx.rng.normal(0, self.sigma, r.shape)
        r = np.clip(r, self.r_min, self.r_max)
        front = np.abs(np.vectorize(wrap)(self.angles)) < 0.45
        bus.put("lidar.ranges", r, t, self.name)
        bus.put("lidar.min_front", float(r[front].min()) if front.any() else math.inf, t, self.name)


# ------------------------------------------------------------ localization --

class LocalizationSubsystem(Subsystem):
    name = "localization"
    rate_hz = 50
    fidelity = ("EKF: wheel odometry prediction + bias-compensated IMU yaw; optional LiDAR likelihood-field "
                "scan matching against the static map for absolute correction")

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        self.wheels = {b.joint: (1 if b.role == "left_wheel" else -1) for b in ctx.bindings if b.encoder_pin}
        self.cpr = {}
        enc = EncoderSubsystem()
        enc.initialize(ctx, Bus())
        self.cpr = enc.cpr
        self.inputs = tuple(f"enc.{j}" for j in self.wheels) + ("imu.gyro_z", "cmd.applied")
        self.outputs = ("est.pose", "est.source")
        self.ekf = OdomEKF(r_yaw=0.004 ** 2)
        self.ekf.reset(*ctx.start)
        self.gyro_bias, self.bias_n = 0.0, 0
        self.prev = {j: 0 for j in self.wheels}
        d = ctx.project.robot.drivetrain
        self.r, self.b = d.wheel_radius, d.wheel_separation
        self.source = "wheel_odometry+imu" if self.wheels else "commanded_velocity (no encoders wired)"
        # map-based correction from LiDAR against the static map (when a LiDAR exists)
        self.matcher, self.last_match, self.matches = None, -1.0, 0
        lid_s = next((x for x in ctx.project.robot.sensors if x.type == "lidar"), None)
        if lid_s is not None and ctx.project.simulation.localization_scan_matching:
            lid = LidarSubsystem()
            lid.initialize(ctx, Bus())
            self.lidar_angles, self.lidar_rmax = lid.angles, lid.r_max
            self.lidar_offset = (lid.offset[0], lid.offset[1])
            b = ctx.project.world.bounds
            static = [o for o in ctx.obstacles if not o.dynamic]
            self.matcher = ScanMatcher(GridMap(rasterize(static, b, 0.05, (lid.z - 0.05, lid.z + 0.05)), (b[0], b[1]), 0.05))
            self.source += "+lidar_scan_matching"
            self.inputs = self.inputs + ("lidar.ranges",)
        bus.put("est.pose", {"x": ctx.start[0], "y": ctx.start[1], "theta": ctx.start[2]}, 0.0, self.name)
        bus.put("est.source", self.source, 0.0, self.name)

    def step(self, t, dt, bus):
        if self.wheels:
            dl = dr = 0.0
            nl = nr = 0
            for j, side in self.wheels.items():
                c = bus.get(f"enc.{j}", 0)
                d = (c - self.prev[j]) / self.cpr[j] * 2 * math.pi * self.r
                self.prev[j] = c
                if side > 0:
                    dl += d
                    nl += 1
                else:
                    dr += d
                    nr += 1
            dl, dr = dl / max(nl, 1), dr / max(nr, 1)
            ds, dth = (dl + dr) / 2, (dr - dl) / self.b
        else:
            cmd = bus.get("cmd.applied") or (0.0, 0.0)
            ds, dth = cmd[0] * dt, cmd[1] * dt
        th0 = float(self.ekf.x[2])
        self.ekf.predict(ds, dth)
        g = bus.get("imu.gyro_z")
        if g is not None:
            cmd = bus.get("cmd.applied") or (0.0, 0.0)
            if abs(cmd[0]) < 1e-3 and abs(cmd[1]) < 1e-3 and abs(ds) < 1e-5:
                # stationary: refine the gyro bias estimate (zero-velocity update)
                self.bias_n += 1
                self.gyro_bias += (g - self.gyro_bias) / min(self.bias_n, 500)
            else:
                # incremental fusion: the gyro measures the heading change over this step
                self.ekf.update_yaw(th0 + (g - self.gyro_bias) * dt)
        if self.matcher is not None and t - self.last_match >= 0.25:
            self.last_match = t
            ranges = bus.get("lidar.ranges")
            if ranges is not None and bus.age("lidar.ranges", t) < 0.15:
                prior = tuple(float(v) for v in self.ekf.x)
                best, s_best, s_prior = self.matcher.match(prior, self.lidar_offset, self.lidar_angles, ranges, self.lidar_rmax)
                if s_best > 0.35 and s_best > s_prior + 0.02:
                    z = np.array(best)
                    H = np.eye(3)
                    R = np.diag([0.05 ** 2, 0.05 ** 2, 0.03 ** 2])
                    innov = z - self.ekf.x
                    innov[2] = wrap(innov[2])
                    S = self.ekf.P + R
                    K = self.ekf.P @ np.linalg.inv(S)
                    self.ekf.x = self.ekf.x + K @ innov
                    self.ekf.P = (np.eye(3) - K @ H) @ self.ekf.P
                    self.matches += 1
        x, y, th = self.ekf.x
        bus.put("est.pose", {"x": float(x), "y": float(y), "theta": float(wrap(th)),
                             "cov_xy": float(self.ekf.P[0, 0] + self.ekf.P[1, 1])}, t, self.name)


# ----------------------------------------------------------------- mission --

class MissionSubsystem(Subsystem):
    name = "mission"
    rate_hz = 10
    inputs = ("est.pose", "truth.pose", "nav.status")
    outputs = ("nav.goal", "mission.state", "mission.estop", "mission.charging", "nav.status")
    fidelity = "scenario sequencer"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        sc = ctx.project.simulation.scenario
        self.goals: list[tuple[float, float]] = []
        if sc.mode == "waypoints":
            self.goals = [(w[0], w[1]) for w in sc.waypoints]
        elif sc.mode in ("goal",) and sc.goal:
            self.goals = [(sc.goal[0], sc.goal[1])]
        self.dock = None
        if sc.return_to_dock or sc.mode == "dock":
            dock = next((o for o in ctx.project.world.objects
                         if o.kind == "charging_station" and (sc.dock_object in (None, o.id))), None)
            if dock:
                dp = dock.props.get("dock_pose", [dock.pose.xyz[0] + 0.6, dock.pose.xyz[1], 0])
                self.dock = (dp[0], dp[1])
                self.charge_power = float(dock.props.get("charge_power_w", 120.0))
                ctx.charge_power_w = self.charge_power
                self.goals.append(self.dock)
            else:
                ctx.event(0.0, "mission", "Dock requested but no charging station in the world", "warning")
        self.idx = 0
        self.state = "idle" if not self.goals else "navigating"
        self.mode = sc.mode
        self.estop_at = sc.estop_at
        ctx.metrics["goals_total"] = len(self.goals)
        ctx.metrics["goals_reached"] = 0
        bus.put("nav.goal", self.goals[0] if self.goals else None, 0.0, self.name)
        bus.put("mission.state", self.state, 0.0, self.name)
        bus.put("mission.estop", False, 0.0, self.name)
        bus.put("mission.charging", False, 0.0, self.name)

    def step(self, t, dt, bus):
        if self.estop_at is not None and t >= self.estop_at and not self.ctx.estop:
            self.ctx.estop = True
            self.ctx.event(t, "estop", "Scripted emergency stop triggered", "warning")
        estop = self.ctx.estop
        bus.put("mission.estop", estop, t, self.name)
        if estop:
            if self.state != "estopped":
                self.prev_state = self.state
            self.state = "estopped"
            bus.put("mission.state", self.state, t, self.name)
            return
        if self.state == "estopped":
            self.state = getattr(self, "prev_state", "idle")
        status = bus.get("nav.status")
        if self.state == "navigating" and status == "arrived":
            g = self.goals[self.idx]
            truth = bus.get("truth.pose")
            err = math.hypot(truth["x"] - g[0], truth["y"] - g[1])
            self.ctx.metrics["goals_reached"] += 1
            is_dock = self.dock is not None and g == self.dock and self.idx == len(self.goals) - 1
            self.ctx.event(t, "goal_reached", f"{'Dock' if is_dock else 'Waypoint'} {self.idx + 1}/{len(self.goals)} reached "
                           f"(true position error {err:.2f} m)", "info", goal=list(g), true_error_m=round(err, 3))
            self.idx += 1
            bus.put("nav.status", "idle", t, self.name)  # acknowledge arrival
            if is_dock:
                self.state = "docked"
                self.ctx.event(t, "charging", f"Docked; charging at {self.charge_power:.0f} W", "info")
            elif self.idx >= len(self.goals):
                self.state = "complete"
                self.ctx.event(t, "mission_complete", "All goals reached", "info")
            else:
                bus.put("nav.goal", self.goals[self.idx], t, self.name)
        elif self.state == "navigating" and status == "failed":
            self.state = "failed"
            self.ctx.event(t, "mission_failed", "Navigation failed (no path)", "error")
        bus.put("mission.state", self.state, t, self.name)
        bus.put("mission.charging", self.state == "docked", t, self.name)
        if self.state in ("complete", "docked", "failed", "idle"):
            bus.put("nav.goal", None, t, self.name)


# -------------------------------------------------------------- navigation --

class PlannerSubsystem(Subsystem):
    name = "planner"
    rate_hz = 2
    inputs = ("nav.goal", "est.pose", "lidar.ranges", "nav.status")
    outputs = ("nav.path", "nav.path_id")
    fidelity = "A* on inflated occupancy grid (static map + live LiDAR marking)"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        rad = ctx.backend.footprint_radius()
        self.res = 0.1
        self.radius = rad
        b = ctx.project.world.bounds
        static = [o for o in ctx.obstacles if not o.dynamic]
        grid = rasterize(static, b, self.res)
        self.base = GridMap(grid, (b[0], b[1]), self.res)
        ctx.static_map = self.base
        self.margin = 0.12  # safety margin beyond the footprint radius
        self.inflated_static = dilate(grid, int(math.ceil((rad + self.margin) / self.res)))
        self.goal = None
        self.path_id = 0
        self.last_plan = -1e9
        lid = next((s for s in ctx.project.robot.sensors if s.type == "lidar"), None)
        fov = math.radians(lid.params.get("fov_deg", 360)) if lid else 2 * math.pi
        n = int(lid.params.get("beams", 180)) if lid else 0
        self.angles = np.linspace(-fov / 2, fov / 2, n, endpoint=fov < 2 * math.pi - 1e-6) if n else None
        self.r_max = float(lid.params.get("range_max", 12.0)) if lid else 12.0
        bus.put("nav.path", None, 0.0, self.name)
        bus.put("nav.path_id", 0, 0.0, self.name)
        self.planned_length = 0.0

    def _plan(self, t, bus, goal):
        pose = bus.get("est.pose")
        grid = self.inflated_static.copy()
        ranges = bus.get("lidar.ranges")
        if ranges is not None and self.angles is not None:
            hits = ranges < self.r_max - 0.05
            xs = pose["x"] + ranges[hits] * np.cos(pose["theta"] + self.angles[hits])
            ys = pose["y"] + ranges[hits] * np.sin(pose["theta"] + self.angles[hits])
            live = np.zeros_like(grid)
            for x, y in zip(xs, ys):
                r, c = self.base.to_cell(x, y)
                if self.base.inside(r, c):
                    live[r, c] = 1
            grid |= dilate(live, int(math.ceil((self.radius + self.margin) / self.res)))
        gm = GridMap(grid, self.base.origin, self.res)
        soft = soft_cost(grid, [(4, 2.0), (2, 6.0)])
        path = astar(gm, (pose["x"], pose["y"]), goal, soft)
        if path is None:
            # goal blocked by live marks: fall back to static map only
            gm = GridMap(self.inflated_static, self.base.origin, self.res)
            soft = soft_cost(gm.grid, [(4, 2.0), (2, 6.0)])
            path = astar(gm, (pose["x"], pose["y"]), goal, soft)
        if path is None:
            self.ctx.event(t, "planner", f"No path to goal {goal}", "error")
            bus.put("nav.path", None, t, self.name)
            return False
        # shortcut only through cells without proximity cost, so the soft-inflated centre line is kept
        path = shortcut(GridMap((grid | (soft > 0)).astype(np.uint8), self.base.origin, self.res), path)
        path[-1] = goal
        path = resample(path, 0.1)
        self.path_id += 1
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
        if self.path_id == 1 or goal != getattr(self, "_measured_goal", None):
            self.planned_length += length
            self._measured_goal = goal
        bus.put("nav.path", path, t, self.name)
        bus.put("nav.path_id", self.path_id, t, self.name)
        self.ctx.metrics["planned_length_m"] = round(self.planned_length, 3)
        return True

    def step(self, t, dt, bus):
        goal = bus.get("nav.goal")
        if goal is None:
            self.goal = None
            return
        status = bus.get("nav.status")
        need = goal != self.goal or (status == "blocked" and t - self.last_plan > 1.0)
        if need:
            self.goal = goal
            self.last_plan = t
            if not self._plan(t, bus, goal):
                bus.put("nav.status", "failed", t, self.name)
            elif status == "blocked":
                self.ctx.event(t, "replan", "Path blocked; replanned around obstacle", "info")


class LocalControllerSubsystem(Subsystem):
    name = "local_controller"
    rate_hz = 20
    inputs = ("est.pose", "nav.path", "nav.path_id", "lidar.min_front", "mission.estop", "mission.state")
    outputs = ("cmd.vel", "nav.status")
    fidelity = "regulated pure pursuit + LiDAR slow-down/stop"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        d = ctx.project.robot.drivetrain
        self.pp = PurePursuit(max_v=min(d.max_speed, 0.8), lookahead=0.4)
        self.idx = 0
        self.path_id = -1
        self.blocked_since = None
        self.anchor, self.anchor_t, self.backoff_until = ctx.start, 0.0, -1.0
        bus.put("cmd.vel", (0.0, 0.0), 0.0, self.name)
        bus.put("nav.status", "idle", 0.0, self.name)

    def step(self, t, dt, bus):
        sc = self.ctx.project.simulation.scenario
        if self.ctx.teleop_cmd is not None or sc.mode in ("teleop", "open_loop"):
            cmd = self.ctx.teleop_cmd if self.ctx.teleop_cmd is not None else tuple(sc.open_loop_cmd)
            bus.put("cmd.vel", (0.0, 0.0) if bus.get("mission.estop") else cmd, t, self.name)
            return
        path = bus.get("nav.path")
        if bus.get("mission.estop") or not path or bus.get("mission.state") != "navigating":
            bus.put("cmd.vel", (0.0, 0.0), t, self.name)
            # keep terminal states latched until the mission manager consumes them
            if not path and bus.get("nav.status") not in ("arrived", "failed"):
                bus.put("nav.status", "idle", t, self.name)
            return
        pid = bus.get("nav.path_id")
        if pid != self.path_id:
            self.path_id, self.idx = pid, 0
        pose = bus.get("est.pose")
        front = bus.get("lidar.min_front", math.inf)
        v, w, self.idx, arrived = self.pp.command((pose["x"], pose["y"], pose["theta"]), path, self.idx, front)
        if arrived:
            bus.put("nav.status", "arrived", t, self.name)
            bus.put("nav.path", None, t, self.name)
            bus.put("cmd.vel", (0.0, 0.0), t, self.name)
            return
        # progress monitor: commanded motion but no displacement => wedged (e.g. against an unseen corner)
        moved = math.hypot(pose["x"] - self.anchor[0], pose["y"] - self.anchor[1]) + abs(wrap(pose["theta"] - self.anchor[2]))
        if moved > 0.08 or (abs(v) < 0.02 and abs(w) < 0.05):
            self.anchor, self.anchor_t = (pose["x"], pose["y"], pose["theta"]), t
        stuck = t - self.anchor_t > 2.5
        if self.backoff_until > t:
            v, w = -0.12, 0.0
        elif stuck:
            self.ctx.event(t, "stuck", "No progress for 2.5 s while commanded to move; backing off and replanning", "warning")
            self.backoff_until = t + 1.0
            self.anchor_t = t + 1.0
            bus.put("nav.status", "blocked", t, self.name)
            v, w = -0.12, 0.0
        elif front < self.pp.stop_dist + 0.05 and v == 0.0:
            self.blocked_since = self.blocked_since or t
            if t - self.blocked_since > 1.5:
                bus.put("nav.status", "blocked", t, self.name)
        else:
            self.blocked_since = None
            bus.put("nav.status", "following", t, self.name)
        bus.put("cmd.vel", (v, w), t, self.name)


# ---------------------------------------------------------------- firmware --

class FirmwareSubsystem(Subsystem):
    name = "firmware"
    fidelity = "behavioural controller model (diff-drive kinematics + per-wheel PI on encoder speed)"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        fw = ctx.project.firmware
        if fw.mode == "emulated":
            raise RuntimeError("Firmware mode 'emulated' requires a validated emulator target (QEMU/Renode); "
                               "none is configured for target '%s'. Use 'behavioral' or 'hal_mock'." % fw.target)
        if fw.mode == "hil":
            raise RuntimeError("Firmware mode 'hil' requires a connected hardware-in-the-loop bridge; none is attached.")
        c = fw.controller
        self.rate_hz = c.loop_hz
        self.kp, self.ki, self.ff = c.kp, c.ki, c.feedforward
        d = ctx.project.robot.drivetrain
        self.r, self.b = d.wheel_radius, d.wheel_separation
        self.max_v, self.max_acc, self.max_dec = d.max_speed, d.max_accel, d.max_decel
        self.link = DelayLine(ctx.project.simulation.comm_latency_ms / 1000.0)
        self.wheels = {}
        enc = EncoderSubsystem()
        enc.initialize(ctx, Bus())
        for b in ctx.bindings:
            if not b.drivable:
                continue
            motor = DCMotor.from_component(b.motor)
            vbus = b.bus_voltage_nominal or motor.v_rated
            self.wheels[b.joint] = {"side": 1 if b.role == "left_wheel" else -1, "ke": motor.ke * d.gear_ratio,
                                    "vbus": vbus, "i": 0.0, "prev": 0, "cpr": enc.cpr.get(b.joint),
                                    "w_meas": 0.0}
        self.inputs = ("cmd.vel", "mission.estop", "elec.bus_v") + tuple(f"enc.{j}" for j in self.wheels)
        self.outputs = ("cmd.applied",) + tuple(f"pwm.{j}" for j in self.wheels)
        self.v_ref = self.w_ref = 0.0
        for j in self.wheels:
            bus.put(f"pwm.{j}", 0.0, 0.0, self.name)
        bus.put("cmd.applied", (0.0, 0.0), 0.0, self.name)
        self.loop_ok = True

    def step(self, t, dt, bus):
        self.link.push(t, bus.get("cmd.vel", (0.0, 0.0)))
        cmd = self.link.pop(t) or (0.0, 0.0)
        estop = bus.get("mission.estop", False)
        v_t, w_t = (0.0, 0.0) if estop else cmd
        v_t = max(-self.max_v, min(self.max_v, v_t))
        dv = v_t - self.v_ref
        lim = (self.max_acc if abs(v_t) > abs(self.v_ref) else self.max_dec) * dt
        self.v_ref += max(-lim, min(lim, dv))
        self.w_ref = w_t
        vbus = bus.get("elec.bus_v") or 0.0
        for j, s in self.wheels.items():
            target = (self.v_ref - s["side"] * self.w_ref * self.b / 2) / self.r
            if s["cpr"]:
                c = bus.get(f"enc.{j}", 0)
                s["w_meas"] = 0.7 * s["w_meas"] + 0.3 * ((c - s["prev"]) / s["cpr"] * 2 * math.pi / dt)
                s["prev"] = c
                err = target - s["w_meas"]
            else:
                err = 0.0  # open loop: no feedback available
            v_bus = vbus if vbus > 1.0 else s["vbus"]
            duty_ff = self.ff * target * s["ke"] / v_bus
            u = duty_ff + (self.kp * err + s["i"]) * s["ke"] / v_bus
            if abs(u) < 1.0 or (u > 0) != (err > 0):  # conditional integration (anti-windup)
                s["i"] += self.ki * err * dt
            if estop:
                s["i"] = 0.0
                u = 0.0
            bus.put(f"pwm.{j}", max(-1.0, min(1.0, u)), t, self.name)
        bus.put("cmd.applied", (self.v_ref, self.w_ref), t, self.name)


# -------------------------------------------------------------- electrical --

class ElectricalSubsystem(Subsystem):
    name = "electrical"
    fidelity = "analytical: Thevenin battery, H-bridge average model, DC motor (R, Kt, Ke), I2t fuse, 1st-order thermal"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        self.ch = {}
        bat_comp = None
        bat_params = {}
        for b in ctx.bindings:
            if not b.drivable:
                ctx.event(0.0, "unbound_actuator", f"{b.joint}: not drivable ({'; '.join(b.issues) or 'incomplete wiring'}) "
                          "- it will receive zero torque", "error")
                continue
            self.ch[b.joint] = {"motor": DCMotor.from_component(b.motor), "drv": HBridge.from_component(b.driver),
                                "binding": b}
            if b.battery is not None and bat_comp is None:
                bat_comp = b.battery
                inst = next((i for i in ctx.project.circuit.instances if i.id == b.battery_instance), None)
                bat_params = inst.params if inst else {}
                self.fuse = Fuse(float(b.fuse_rating)) if b.fuse_rating else None
                self.fuse_id = b.fuse_instance
        self.battery = None
        self.supply_v = None
        if bat_comp is not None and bat_comp.sim_model == "battery:thevenin":
            self.battery = Battery.from_component(bat_comp, soc=float(bat_params.get("soc", 1.0)), params=bat_params)
            self.v_cutoff = bat_comp.rating("v_min") or 0.0
        elif bat_comp is not None:
            self.supply_v = float(bat_params.get("voltage", bat_comp.params.get("voltage", 12.0)))
        if not hasattr(self, "fuse"):
            self.fuse, self.fuse_id = None, None
        self.dg = ctx.project.robot.drivetrain.gear_ratio
        self.eff = ctx.project.robot.power.driver_efficiency
        self.ambient = ctx.project.simulation.ambient_c
        for c in self.ch.values():
            c["motor"].temp_c = self.ambient
        self.cut = False
        self.i_total = 0.0
        self.inputs = ("mission.charging",) + tuple(f"pwm.{j}" for j in self.ch) + tuple(f"wheel.omega.{j}" for j in self.ch)
        self.outputs = ("elec.bus_v", "elec.bus_i", "elec.soc", "elec.state") + tuple(f"torque.{j}" for j in self.ch) + \
            tuple(f"motor.{j}" for j in self.ch)
        v0 = self.battery.terminal_voltage(0) if self.battery else (self.supply_v or 0.0)
        bus.put("elec.bus_v", v0, 0.0, self.name)
        bus.put("elec.bus_i", 0.0, 0.0, self.name)
        bus.put("elec.soc", self.battery.soc if self.battery else None, 0.0, self.name)
        bus.put("elec.state", "ok", 0.0, self.name)
        self.peak_i = 0.0

    def step(self, t, dt, bus):
        charging = bus.get("mission.charging", False)
        if self.battery:
            v_bus = 0.0 if self.cut else self.battery.terminal_voltage(self.i_total)
        else:
            v_bus = 0.0 if self.cut else (self.supply_v or 0.0)
        i_total = 0.0
        for j, c in self.ch.items():
            m, drv = c["motor"], c["drv"]
            duty = bus.get(f"pwm.{j}", 0.0)
            omega_motor = bus.get(f"wheel.omega.{j}", 0.0) * self.dg
            v_term = drv.output_voltage(duty, v_bus, m.current)
            i, tq = m.compute(v_term, omega_motor)
            m.thermal_step(dt, self.ambient)
            ev = drv.check(i, dt)
            if ev:
                self.ctx.event(t, "driver_fault", f"{c['binding'].driver_instance} channel {c['binding'].channel}: "
                               f"current {abs(i):.1f} A > peak rating {drv.i_peak} A for 0.5 s -> output disabled", "error")
            p_elec = v_term * i
            i_total += max(p_elec, 0.0) / max(v_bus * self.eff, 1e-3) if v_bus > 0.5 else 0.0
            bus.put(f"torque.{j}", tq * self.dg, t, self.name)
            bus.put(f"motor.{j}", {"duty": duty, "v": v_term, "i": i, "torque": tq * self.dg,
                                   "rpm": omega_motor * 60 / (2 * math.pi), "temp_c": m.temp_c}, t, self.name)
            if m.temp_c > 100 and not c.get("hot"):
                c["hot"] = True
                self.ctx.event(t, "thermal", f"{c['binding'].motor_instance} winding estimate {m.temp_c:.0f} C "
                               "(analytical estimate, not a safety rating)", "warning")
        if v_bus > 0.5:
            i_total += self.ctx.base_load_w / v_bus
        if charging and self.battery and self.battery.soc < 0.999:
            i_total -= self.ctx.charge_power_w / max(v_bus, 1.0)
        self.i_total = i_total
        self.peak_i = max(self.peak_i, i_total)
        if self.fuse and not self.cut and self.fuse.step(max(i_total, 0.0), dt):
            self.cut = True
            self.ctx.event(t, "fuse_blown", f"Fuse {self.fuse_id} ({self.fuse.rating_a} A) opened at {i_total:.1f} A", "critical")
        if self.battery and not self.cut:
            v_bus = self.battery.step(i_total, dt)
            if v_bus < self.v_cutoff and i_total > 0:
                self.cut = True
                self.ctx.event(t, "battery_cutoff", f"Battery under-voltage cutoff at {v_bus:.2f} V "
                               f"(SoC {self.battery.soc:.1%})", "error")
        bus.put("elec.bus_v", v_bus, t, self.name)
        bus.put("elec.bus_i", i_total, t, self.name)
        bus.put("elec.soc", self.battery.soc if self.battery else None, t, self.name)
        bus.put("elec.state", "cut" if self.cut else ("charging" if charging else "ok"), t, self.name)


# ----------------------------------------------------------------- physics --

class PhysicsSubsystem(Subsystem):
    name = "physics"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        be = ctx.backend
        self.fidelity = be.fidelity
        self.joints = [a.joint for a in ctx.project.robot.actuators if "wheel" in a.role]
        self.inputs = tuple(f"torque.{j}" for j in self.joints) + ("world.dynamic",)
        self.outputs = ("truth.pose", "truth.twist", "truth.contacts") + tuple(f"wheel.omega.{j}" for j in self.joints) + \
            tuple(f"wheel.angle.{j}" for j in self.joints)
        self.in_contact: set[str] = set()
        self.last_contact: dict[str, float] = {}
        self.contact_time = 0.0
        self.collisions = 0
        self._publish(0.0, bus, be.state())

    def _publish(self, t, bus, s):
        bus.put("truth.pose", {"x": s.x, "y": s.y, "theta": s.theta}, t, self.name)
        bus.put("truth.twist", {"v": s.v, "w": s.w, "ax": s.ax}, t, self.name)
        bus.put("truth.contacts", list(s.contacts), t, self.name)
        for j in self.joints:
            bus.put(f"wheel.omega.{j}", s.wheel_omega.get(j, 0.0), t, self.name)
            bus.put(f"wheel.angle.{j}", s.wheel_angle.get(j, 0.0), t, self.name)

    def step(self, t, dt, bus):
        torques = {j: bus.get(f"torque.{j}", 0.0) for j in self.joints}
        s = self.ctx.backend.step(torques, dt)
        now = set(s.contacts)
        for c in now:
            # debounce: a contact that flickers within 1 s is the same collision
            if t - self.last_contact.get(c, -1e9) > 1.0:
                self.collisions += 1
                self.ctx.event(t, "collision", f"Robot collided with '{c}' at {s.x:.2f}, {s.y:.2f}", "warning", obstacle=c)
            self.last_contact[c] = t
        if now:
            self.contact_time += dt
        self.ctx.metrics["contact_time_s"] = round(self.contact_time, 3)
        self.in_contact = now
        self.ctx.metrics["collisions"] = self.collisions
        self._publish(t, bus, s)


# --------------------------------------------------------- mapping / AI --

class MappingSubsystem(Subsystem):
    name = "mapping"
    rate_hz = 2
    inputs = ("lidar.ranges", "est.pose")
    outputs = ("map.version",)
    optional = True
    fidelity = "log-odds occupancy mapping at the estimated pose (not full SLAM)"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        b = ctx.project.world.bounds
        gm = GridMap(np.zeros((int((b[3] - b[1]) / 0.1) + 1, int((b[2] - b[0]) / 0.1) + 1), dtype=np.uint8), (b[0], b[1]), 0.1)
        self.map = LogOddsMap(gm)
        lid = LidarSubsystem()
        lid.initialize(ctx, Bus())
        self.angles, self.r_max = lid.angles, lid.r_max
        self.version = 0
        bus.put("map.version", 0, 0.0, self.name)

    def step(self, t, dt, bus):
        r = bus.get("lidar.ranges")
        if r is None:
            return
        p = bus.get("est.pose")
        self.map.integrate((p["x"], p["y"], p["theta"]), self.angles, r, self.r_max)
        self.version += 1
        bus.put("map.version", self.version, t, self.name)


class PerceptionSubsystem(Subsystem):
    name = "perception"
    rate_hz = 5
    inputs = ("lidar.ranges", "est.pose", "truth.pose")
    outputs = ("perception.detections",)
    optional = True
    fidelity = "LiDAR Euclidean clustering; scored against ground truth"

    def initialize(self, ctx, bus):
        super().initialize(ctx, bus)
        lid = LidarSubsystem()
        lid.initialize(ctx, Bus())
        self.angles, self.r_max = lid.angles, lid.r_max
        self.scores = []
        bus.put("perception.detections", [], 0.0, self.name)

    def step(self, t, dt, bus):
        r = bus.get("lidar.ranges")
        if r is None:
            return
        p = bus.get("est.pose")
        dets = cluster_scan(p["x"], p["y"], p["theta"], self.angles, r, self.r_max)
        tp = bus.get("truth.pose")
        truth = []
        for ob in self.ctx.obstacles:
            d = distance_to(ob, tp["x"], tp["y"])
            if d < self.r_max * 0.5 and ob.kind not in ("wall",):
                truth.append({"x": ob.cx, "y": ob.cy, "radius": ob.r if ob.shape == "circle" else max(ob.hx, ob.hy)})
        self.scores.append(score_detections(dets, truth, match_dist=0.8))
        bus.put("perception.detections", dets, t, self.name)
