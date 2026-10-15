"""2.5D world geometry: footprints of collidable objects in the XY plane,
circle-vs-obstacle collision, LiDAR ray casting and occupancy rasterisation.

Objects taller than the robot's sensing/collision height band are obstacles;
floors, zones and markers are not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ...schemas.project import World, WorldObject

NON_OBSTACLE_KINDS = {"floor", "loading_zone", "robot_start", "goal", "camera", "lidar", "charging_station"}


@dataclass
class Obstacle:
    id: str
    kind: str
    shape: str  # box | circle
    cx: float
    cy: float
    hx: float = 0.0  # half extents (box)
    hy: float = 0.0
    yaw: float = 0.0
    r: float = 0.0  # radius (circle)
    z0: float = 0.0
    z1: float = 1.0
    dynamic: bool = False

    def corners(self) -> np.ndarray:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        pts = np.array([[self.hx, self.hy], [-self.hx, self.hy], [-self.hx, -self.hy], [self.hx, -self.hy]])
        R = np.array([[c, -s], [s, c]])
        return pts @ R.T + np.array([self.cx, self.cy])


def obstacles_from_world(world: World, min_height: float = 0.03) -> list[Obstacle]:
    out = []
    for o in world.objects:
        if not o.collision.enabled or o.kind in NON_OBSTACLE_KINDS or o.shape in ("plane", "marker"):
            continue
        z0 = o.pose.xyz[2]
        h = o.size[2]
        if o.kind == "ramp":
            continue  # ramps are traversable surfaces in the planar engine; MuJoCo models them as geometry
        if h < min_height:
            continue
        if o.shape == "cylinder":
            out.append(Obstacle(o.id, o.kind, "circle", o.pose.xyz[0], o.pose.xyz[1], r=o.size[0], z0=z0, z1=z0 + h,
                                dynamic=o.motion is not None))
        else:
            out.append(Obstacle(o.id, o.kind, "box", o.pose.xyz[0], o.pose.xyz[1], o.size[0] / 2, o.size[1] / 2,
                                o.pose.rpy[2], z0=z0, z1=z0 + h, dynamic=o.motion is not None))
    return out


def circle_penetration(ob: Obstacle, x: float, y: float, radius: float) -> tuple[float, float, float]:
    """Return (depth, nx, ny): penetration depth of a circle into the obstacle and push-out normal."""
    if ob.shape == "circle":
        dx, dy = x - ob.cx, y - ob.cy
        d = math.hypot(dx, dy)
        depth = ob.r + radius - d
        if depth <= 0:
            return 0.0, 0.0, 0.0
        return depth, (dx / d if d > 1e-9 else 1.0), (dy / d if d > 1e-9 else 0.0)
    c, s = math.cos(ob.yaw), math.sin(ob.yaw)
    lx = c * (x - ob.cx) + s * (y - ob.cy)
    ly = -s * (x - ob.cx) + c * (y - ob.cy)
    qx = max(-ob.hx, min(ob.hx, lx))
    qy = max(-ob.hy, min(ob.hy, ly))
    dx, dy = lx - qx, ly - qy
    d = math.hypot(dx, dy)
    if d > 1e-9:
        depth = radius - d
        if depth <= 0:
            return 0.0, 0.0, 0.0
        nlx, nly = dx / d, dy / d
    else:  # centre inside the box
        px, py = ob.hx - abs(lx), ob.hy - abs(ly)
        if px < py:
            depth, nlx, nly = px + radius, math.copysign(1, lx), 0.0
        else:
            depth, nlx, nly = py + radius, 0.0, math.copysign(1, ly)
    return depth, c * nlx - s * nly, s * nlx + c * nly


def distance_to(ob: Obstacle, x: float, y: float) -> float:
    if ob.shape == "circle":
        return math.hypot(x - ob.cx, y - ob.cy) - ob.r
    c, s = math.cos(ob.yaw), math.sin(ob.yaw)
    lx = abs(c * (x - ob.cx) + s * (y - ob.cy)) - ob.hx
    ly = abs(-s * (x - ob.cx) + c * (y - ob.cy)) - ob.hy
    out = math.hypot(max(lx, 0), max(ly, 0))
    return out if out > 0 else max(lx, ly)


def raycast(obstacles: list[Obstacle], ox: float, oy: float, angles: np.ndarray, r_max: float, z: float = 0.2) -> np.ndarray:
    """Vectorised 2D ray cast at sensor height z. Returns ranges (r_max where nothing is hit)."""
    dx, dy = np.cos(angles), np.sin(angles)
    best = np.full(angles.shape, r_max)
    for ob in obstacles:
        if not (ob.z0 <= z <= ob.z1):
            continue
        if ob.shape == "circle":
            fx, fy = ox - ob.cx, oy - ob.cy
            b = fx * dx + fy * dy
            cterm = fx * fx + fy * fy - ob.r * ob.r
            disc = b * b - cterm
            ok = disc >= 0
            t = -b - np.sqrt(np.where(ok, disc, 0))
            t = np.where(ok & (t > 0), t, np.inf)
        else:
            # slab test in the box frame
            c, s = math.cos(ob.yaw), math.sin(ob.yaw)
            lx, ly = c * (ox - ob.cx) + s * (oy - ob.cy), -s * (ox - ob.cx) + c * (oy - ob.cy)
            ldx, ldy = c * dx + s * dy, -s * dx + c * dy
            with np.errstate(divide="ignore", invalid="ignore"):
                tx1, tx2 = (-ob.hx - lx) / ldx, (ob.hx - lx) / ldx
                ty1, ty2 = (-ob.hy - ly) / ldy, (ob.hy - ly) / ldy
            tmin = np.maximum(np.minimum(tx1, tx2), np.minimum(ty1, ty2))
            tmax = np.minimum(np.maximum(tx1, tx2), np.maximum(ty1, ty2))
            t = np.where((tmax >= np.maximum(tmin, 0)) & (tmin > 0), tmin, np.inf)
        best = np.minimum(best, t)
    return best


def rasterize(obstacles: list[Obstacle], bounds: list[float], resolution: float, z_band=(0.0, 1.5)) -> np.ndarray:
    """Occupancy grid (rows = y, cols = x), 1 = occupied."""
    x0, y0, x1, y1 = bounds
    w = int(math.ceil((x1 - x0) / resolution))
    h = int(math.ceil((y1 - y0) / resolution))
    grid = np.zeros((h, w), dtype=np.uint8)
    xs = x0 + (np.arange(w) + 0.5) * resolution
    ys = y0 + (np.arange(h) + 0.5) * resolution
    X, Y = np.meshgrid(xs, ys)
    for ob in obstacles:
        if ob.z1 < z_band[0] or ob.z0 > z_band[1]:
            continue
        if ob.shape == "circle":
            grid[(X - ob.cx) ** 2 + (Y - ob.cy) ** 2 <= ob.r ** 2] = 1
        else:
            c, s = math.cos(ob.yaw), math.sin(ob.yaw)
            lx = c * (X - ob.cx) + s * (Y - ob.cy)
            ly = -s * (X - ob.cx) + c * (Y - ob.cy)
            grid[(np.abs(lx) <= ob.hx) & (np.abs(ly) <= ob.hy)] = 1
    return grid


def move_dynamic(world_obj: WorldObject, ob: Obstacle, t: float) -> None:
    """Scripted patrol for dynamic obstacles (humans, carts): piecewise-linear, ping-pong."""
    m = world_obj.motion
    if not m or len(m.waypoints) < 2:
        return
    pts = m.waypoints + m.waypoints[-2:0:-1]
    segs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:] + pts[:1])]
    total = sum(segs) or 1.0
    d = (t * m.speed) % total
    for i, L in enumerate(segs):
        if d <= L:
            a, b = pts[i], pts[(i + 1) % len(pts)]
            f = d / L if L > 0 else 0
            ob.cx, ob.cy = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            return
        d -= L
