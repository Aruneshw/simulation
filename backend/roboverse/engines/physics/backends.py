"""Physics backend adapters.

New engines (Gazebo via ROS 2 bridge, Webots, PyBullet...) plug in by
implementing `PhysicsBackend` and registering in `BACKENDS`.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ...schemas.project import Robot, World
from ..robot import link_inertia
from ..world.geometry import Obstacle, circle_penetration


@dataclass
class PhysicsState:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    v: float = 0.0  # forward body velocity
    w: float = 0.0  # yaw rate
    ax: float = 0.0  # forward acceleration
    wheel_omega: dict[str, float] = field(default_factory=dict)  # joint -> rad/s (positive = forward)
    wheel_angle: dict[str, float] = field(default_factory=dict)
    contacts: list[str] = field(default_factory=list)  # obstacle ids in contact
    slip: dict[str, bool] = field(default_factory=dict)


class PhysicsBackend(ABC):
    name = "abstract"
    fidelity = ""

    @abstractmethod
    def initialize(self, robot: Robot, world: World, obstacles: list[Obstacle], start: tuple[float, float, float],
                   dt: float) -> None: ...

    @abstractmethod
    def step(self, torques: dict[str, float], dt: float) -> PhysicsState: ...

    @abstractmethod
    def state(self) -> PhysicsState: ...

    def footprint_radius(self) -> float:
        return getattr(self, "radius", 0.3)

    def set_reflected_inertia(self, inertia: dict[str, float]) -> None:
        """Motor rotor inertia reflected through the gearbox to each wheel joint."""
        self.extra_inertia = dict(inertia)


def robot_footprint(robot: Robot) -> tuple[float, float, float]:
    """(length, width, bounding radius) from the base link and wheels."""
    base = next((l for l in robot.links if l.name == robot.base_link), None)
    L, W = (base.geometry.size[0], base.geometry.size[1]) if base and base.geometry and base.geometry.type == "box" else (0.4, 0.3)
    W = max(W, robot.drivetrain.wheel_separation + robot.drivetrain.wheel_width)
    return L, W, 0.5 * math.hypot(L, W)


class PlanarBackend(PhysicsBackend):
    """Built-in planar rigid-body dynamics for differential and skid-steer bases.

    Longitudinal wheel forces from motor torque with Coulomb traction limit;
    rolling resistance; skid-steer lateral scrub moment; reflected wheel and
    rotor inertia; circle-vs-obstacle contact with impulse-free projection.
    """
    name = "builtin_planar"
    fidelity = "2D rigid-body dynamics (planar); no suspension, slopes or 3D contact"

    def initialize(self, robot, world, obstacles, start, dt):
        d = robot.drivetrain
        if d.drive_type not in ("differential", "four_wheel", "tracked"):
            raise ValueError(f"Built-in planar dynamics supports differential/four_wheel/tracked, not '{d.drive_type}'. "
                             "Use the MuJoCo backend or a kinematic test.")
        self.robot = robot
        self.obstacles = obstacles
        self.r = d.wheel_radius
        self.b = d.wheel_separation
        self.mass = sum(l.mass for l in robot.links) + d.payload_kg
        L, W, self.radius = robot_footprint(robot)
        base = next((l for l in robot.links if l.name == robot.base_link), None)
        self.izz = (link_inertia(base)[2] if base else self.mass * (L * L + W * W) / 12) + d.payload_kg * (L * L + W * W) / 12
        self.length = L
        self.wheels = {a.joint: (1 if a.role == "left_wheel" else -1) for a in robot.actuators if "wheel" in a.role}
        self.n_driven = max(1, len(self.wheels))
        self.extra_inertia: dict[str, float] = {}  # reflected rotor inertia per wheel (set by coordinator)
        self.wheel_inertia = {j: next((link_inertia(l)[1] for l in robot.links if f"{l.name}_joint" == j), 1e-4)
                              for j in self.wheels}
        self.mu = d.wheel_friction
        self.crr = d.rolling_resistance
        driven_share = 0.8 if d.drive_type == "differential" else 1.0
        self.normal = self.mass * 9.81 * driven_share / self.n_driven
        self.skid = d.drive_type in ("four_wheel", "tracked")
        self.s = PhysicsState(x=start[0], y=start[1], theta=start[2])
        for j in self.wheels:
            self.s.wheel_omega[j] = 0.0
            self.s.wheel_angle[j] = 0.0

    def step(self, torques, dt):
        s = self.s
        fl = fr = 0.0
        jl = jr = 0.0
        s.slip = {}
        for j, side in self.wheels.items():
            f = torques.get(j, 0.0) / self.r
            limit = self.mu * self.normal
            s.slip[j] = abs(f) > limit
            f = max(-limit, min(limit, f))
            J = self.wheel_inertia[j] + self.extra_inertia.get(j, 0.0)
            if side > 0:
                fl += f
                jl += J
            else:
                fr += f
                jr += J
        m_eff = self.mass + (jl + jr) / self.r ** 2
        i_eff = self.izz + (jl + jr) * (self.b / 2) ** 2 / self.r ** 2
        f_rr = self.crr * self.mass * 9.81 * math.tanh(s.v / 0.02)
        a = (fl + fr - f_rr) / m_eff
        m_scrub = 0.0
        if self.skid:
            m_scrub = 0.3 * self.mu * self.mass * 9.81 * self.length / 4 * math.tanh(s.w / 0.05)
        alpha = ((fr - fl) * self.b / 2 - m_scrub) / i_eff
        s.v += a * dt
        s.w += alpha * dt
        s.ax = a
        nx = s.x + s.v * math.cos(s.theta) * dt
        ny = s.y + s.v * math.sin(s.theta) * dt
        s.theta = math.atan2(math.sin(s.theta + s.w * dt), math.cos(s.theta + s.w * dt))
        contacts = []
        for ob in self.obstacles:
            depth, ux, uy = circle_penetration(ob, nx, ny, self.radius)
            if depth > 0:
                contacts.append(ob.id)
                nx += ux * depth
                ny += uy * depth
                c = math.cos(s.theta) * ux + math.sin(s.theta) * uy  # heading . contact normal
                if s.v * c < 0:  # driving into the obstacle: inelastic stop along the normal
                    s.v = 0.0 if abs(c) > 0.3 else s.v * (1 - abs(c))
        s.x, s.y = nx, ny
        s.contacts = contacts
        for j, side in self.wheels.items():
            om = (s.v - side * s.w * self.b / 2) / self.r
            s.wheel_omega[j] = om
            s.wheel_angle[j] += om * dt
        return s

    def state(self):
        return self.s


class MuJoCoBackend(PhysicsBackend):
    """MuJoCo rigid-body simulation (3D contacts, friction cones) driven by motor torques."""
    name = "mujoco"
    fidelity = "3D rigid-body dynamics with soft contacts (MuJoCo)"

    def initialize(self, robot, world, obstacles, start, dt):
        import mujoco  # noqa: PLC0415

        from ..description import to_mjcf
        self.mj = mujoco
        self.robot = robot
        # the internal timestep must divide the co-simulation macro step exactly, otherwise the
        # physics clock drifts from the coordinator clock
        self.substeps = max(1, math.ceil(dt / 0.002 - 1e-9))
        self.xml = to_mjcf(robot, world.objects, timestep=dt / self.substeps)
        self.model = mujoco.MjModel.from_xml_string(self.xml)
        self.data = mujoco.MjData(self.model)
        _, _, self.radius = robot_footprint(robot)
        self.data.qpos[0:3] = [start[0], start[1], 0.002]
        self.data.qpos[3:7] = [math.cos(start[2] / 2), 0, 0, math.sin(start[2] / 2)]
        mujoco.mj_forward(self.model, self.data)
        self.wheels = [a.joint for a in robot.actuators if "wheel" in a.role]
        self.act_ids = {j: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"m_{j}") for j in self.wheels}
        self.jids = {j: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, j) for j in self.wheels}
        self.obstacle_geoms = {}
        for i in range(self.model.ngeom):
            nm = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
            if nm.startswith("obj_"):
                self.obstacle_geoms[i] = nm[4:]
        self.extra_inertia: dict[str, float] = {}
        self.s = PhysicsState()
        self._prev_v = 0.0
        self._read(dt)

    def _read(self, dt):
        d, m = self.data, self.model
        x, y = float(d.qpos[0]), float(d.qpos[1])
        qw, qx, qy, qz = d.qpos[3:7]
        th = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
        vx, vy = float(d.qvel[0]), float(d.qvel[1])
        v = vx * math.cos(th) + vy * math.sin(th)
        s = self.s
        s.ax = (v - self._prev_v) / dt if dt > 0 else 0.0
        self._prev_v = v
        s.x, s.y, s.theta, s.v, s.w = x, y, th, v, float(d.qvel[5])
        for j in self.wheels:
            jid = self.jids[j]
            s.wheel_omega[j] = float(d.qvel[m.jnt_dofadr[jid]])
            s.wheel_angle[j] = float(d.qpos[m.jnt_qposadr[jid]])
        cs = set()
        for i in range(d.ncon):
            c = d.contact[i]
            for g in (c.geom1, c.geom2):
                if g in self.obstacle_geoms:
                    cs.add(self.obstacle_geoms[g])
        s.contacts = sorted(cs)

    def set_reflected_inertia(self, inertia):
        self.extra_inertia = dict(inertia)
        for j, val in inertia.items():
            if j in self.jids:
                self.model.dof_armature[self.model.jnt_dofadr[self.jids[j]]] = val

    def step(self, torques, dt):
        for j in self.wheels:
            self.data.ctrl[self.act_ids[j]] = torques.get(j, 0.0)
        for _ in range(self.substeps):
            self.mj.mj_step(self.model, self.data)
        self._read(dt)
        return self.s

    def state(self):
        return self.s


def mujoco_available() -> bool:
    try:
        import mujoco  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


BACKENDS = {"builtin_planar": PlanarBackend, "mujoco": MuJoCoBackend}


def make_backend(name: str) -> PhysicsBackend:
    if name == "mujoco" and not mujoco_available():
        raise ValueError("MuJoCo backend selected but the 'mujoco' Python package is not installed")
    cls: Optional[type] = BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown physics backend '{name}'")
    return cls()
