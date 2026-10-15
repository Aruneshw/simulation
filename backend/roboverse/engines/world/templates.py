"""Environment templates with real collision geometry."""
from __future__ import annotations

import math

from ...schemas.project import CollisionProps, MotionProfile, Pose, World, WorldObject

_counter = {"n": 0}


def _id(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']}"


def obj(kind, name, size, xyz, yaw=0.0, shape="box", color="#8a96a8", **kw) -> WorldObject:
    return WorldObject(id=kw.pop("id", None) or _id(kind[:3] + "_"), name=name, kind=kind, shape=shape, size=list(size),
                       pose=Pose(xyz=list(xyz), rpy=[0, 0, yaw]), color=color, **kw)


def _walls(x0, y0, x1, y1, h=2.5, t=0.15) -> list[WorldObject]:
    w, d = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [obj("wall", "Wall N", [w + t, t, h], [cx, y1, 0], color="#c9ced6"),
            obj("wall", "Wall S", [w + t, t, h], [cx, y0, 0], color="#c9ced6"),
            obj("wall", "Wall E", [t, d + t, h], [x1, cy, 0], color="#c9ced6"),
            obj("wall", "Wall W", [t, d + t, h], [x0, cy, 0], color="#c9ced6")]


def _floor(x0, y0, x1, y1, color="#e7e9ee") -> WorldObject:
    return obj("floor", "Floor", [x1 - x0, y1 - y0, 0.01], [(x0 + x1) / 2, (y0 + y1) / 2, -0.01], shape="plane", color=color)


def warehouse() -> World:
    objs = [_floor(-10, -7, 10, 7), *_walls(-10, -7, 10, 7)]
    for row, y in enumerate((-3.5, 0.5, 4.5)):
        for col, x in enumerate((-5.5, -1.5, 2.5)):
            objs.append(obj("rack", f"Rack {row}{col}", [2.7, 1.1, 2.0], [x, y, 0], color="#d98e04"))
    objs += [
        obj("loading_zone", "Loading dock", [3.0, 2.0, 0.01], [7.5, -5.0, 0], shape="plane", color="#facc15"),
        obj("charging_station", "Charger", [0.4, 0.3, 0.3], [-8.8, -5.5, 0], id="dock_1", color="#22c55e",
            props={"charge_power_w": 120.0, "dock_pose": [-8.2, -5.5, math.pi]}),
        obj("box", "Pallet", [1.2, 0.8, 0.15], [6.5, 3.0, 0], color="#a16207"),
        obj("human", "Worker", [0.25, 0.25, 1.75], [0, -1.5, 0], shape="cylinder", color="#3b82f6", static=False,
            motion=MotionProfile(waypoints=[[-6, -1.5], [5, -1.5]], speed=0.6)),
        obj("robot_start", "Start", [0.3, 0.3, 0.01], [-8.0, -5.5, 0], shape="marker", color="#10b981", id="start"),
        obj("goal", "Pick A", [0.3, 0.3, 0.01], [7.5, -4.8, 0], shape="marker", color="#ef4444", id="goal_pick"),
    ]
    return World(template="warehouse", bounds=[-10.5, -7.5, 10.5, 7.5], objects=objs)


def factory_floor() -> World:
    objs = [_floor(-12, -8, 12, 8, "#dcdfe4"), *_walls(-12, -8, 12, 8, h=4)]
    for i, x in enumerate((-7, -1, 5)):
        objs.append(obj("workstation", f"Cell {i + 1}", [2.0, 1.2, 1.0], [x, 3.5, 0], color="#64748b"))
        objs.append(obj("table", f"Bench {i + 1}", [1.6, 0.8, 0.9], [x, -3.5, 0], color="#94a3b8"))
    objs += [obj("box", "Conveyor", [8.0, 0.6, 0.8], [0, 0, 0], color="#475569"),
             obj("charging_station", "Charger", [0.4, 0.3, 0.3], [-11.0, -6.5, 0], id="dock_1", color="#22c55e",
                 props={"dock_pose": [-10.4, -6.5, math.pi]}),
             obj("robot_start", "Start", [0.3, 0.3, 0.01], [-10, -6.5, 0], shape="marker", id="start")]
    return World(template="factory_floor", bounds=[-12.5, -8.5, 12.5, 8.5], objects=objs)


def indoor_logistics() -> World:
    objs = [_floor(-8, -6, 8, 6), *_walls(-8, -6, 8, 6)]
    objs += [obj("wall", "Corridor wall A", [8.0, 0.15, 2.5], [-2, 1.5, 0], color="#c9ced6"),
             obj("wall", "Corridor wall B", [8.0, 0.15, 2.5], [2, -1.5, 0], color="#c9ced6"),
             obj("door", "Door", [0.9, 0.05, 2.0], [-6.5, 1.5, 0], color="#b45309",
                 collision=CollisionProps(enabled=False), props={"open": True}),
             obj("robot_start", "Start", [0.3, 0.3, 0.01], [-7, -5, 0], shape="marker", id="start")]
    return World(template="indoor_logistics", bounds=[-8.5, -6.5, 8.5, 6.5], objects=objs)


def outdoor_terrain() -> World:
    objs = [_floor(-15, -15, 15, 15, "#8db27a")]
    for i, (x, y, r) in enumerate([(-6, 4, 0.4), (3, -5, 0.6), (8, 6, 0.5), (-2, -9, 0.35), (10, -2, 0.5)]):
        objs.append(obj("cylinder", f"Tree {i + 1}", [r, r, 4.0], [x, y, 0], shape="cylinder", color="#3f6212"))
    objs += [obj("ramp", "Ramp 10deg", [3.0, 1.5, 0.5], [0, 6, 0], color="#a8a29e", props={"incline_deg": 10}),
             obj("box", "Rock", [1.0, 0.8, 0.5], [5, 1, 0], color="#78716c"),
             obj("robot_start", "Start", [0.3, 0.3, 0.01], [-12, -12, 0], shape="marker", id="start")]
    return World(template="outdoor_terrain", bounds=[-15, -15, 15, 15], objects=objs)


def laboratory() -> World:
    objs = [_floor(-4, -4, 4, 4, "#f1f5f9"), *_walls(-4, -4, 4, 4, h=2.8)]
    objs += [obj("table", "Lab bench", [2.0, 0.8, 0.9], [0, 3.2, 0], color="#94a3b8"),
             obj("box", "Test block", [0.3, 0.3, 0.3], [1.5, 0, 0], color="#f97316"),
             obj("robot_start", "Start", [0.3, 0.3, 0.01], [-3, -3, 0], shape="marker", id="start")]
    return World(template="laboratory", bounds=[-4.5, -4.5, 4.5, 4.5], objects=objs)


def obstacle_course() -> World:
    objs = [_floor(-6, -4, 6, 4), *_walls(-6, -4, 6, 4, h=0.6)]
    for i, (x, y) in enumerate([(-3, 1.5), (-3, -1.5), (0, 0), (2.5, 2), (2.5, -2), (4, 0.5)]):
        objs.append(obj("box", f"Block {i + 1}", [0.6, 0.6, 0.5], [x, y, 0], yaw=0.3 * i, color="#f97316"))
    objs += [obj("cylinder", "Pillar", [0.3, 0.3, 1.0], [-1, -2.5, 0], shape="cylinder", color="#e11d48"),
             obj("robot_start", "Start", [0.3, 0.3, 0.01], [-5, 0, 0], shape="marker", id="start"),
             obj("goal", "Finish", [0.3, 0.3, 0.01], [5.2, -2.8, 0], shape="marker", id="goal_finish")]
    return World(template="obstacle_course", bounds=[-6.5, -4.5, 6.5, 4.5], objects=objs)


TEMPLATES = {"warehouse": warehouse, "factory_floor": factory_floor, "indoor_logistics": indoor_logistics,
             "outdoor_terrain": outdoor_terrain, "laboratory": laboratory, "obstacle_course": obstacle_course}


def make_world(name: str) -> World:
    _counter["n"] = 0
    return TEMPLATES[name]()
