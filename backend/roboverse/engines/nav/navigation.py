"""Built-in navigation stack (used when ROS 2 / Nav2 is not available).

- Costmap: static map rasterised from the world + LiDAR obstacle marking, inflated by robot radius.
- Global planner: 8-connected A* on the inflated costmap, then line-of-sight shortcutting.
- Local controller: regulated pure pursuit with LiDAR-based slow-down / stop and replanning.
- Localisation: wheel odometry fused with IMU yaw rate (EKF on [x, y, theta]).
- Mapping: log-odds occupancy mapping from LiDAR at the estimated pose (mapping with
  estimated poses, not full SLAM — the map drifts with odometry error).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


def dilate(grid: np.ndarray, radius_cells: int) -> np.ndarray:
    """Binary dilation with a disc structuring element (pure numpy)."""
    if radius_cells <= 0:
        return grid.copy()
    out = grid.astype(bool).copy()
    h, w = grid.shape
    src = grid.astype(bool)
    for dy in range(-radius_cells, radius_cells + 1):
        for dx in range(-radius_cells, radius_cells + 1):
            if dx * dx + dy * dy > radius_cells * radius_cells:
                continue
            ys = slice(max(0, dy), h + min(0, dy))
            yd = slice(max(0, -dy), h + min(0, -dy))
            xs = slice(max(0, dx), w + min(0, dx))
            xd = slice(max(0, -dx), w + min(0, -dx))
            out[yd, xd] |= src[ys, xs]
    return out.astype(np.uint8)


@dataclass
class GridMap:
    grid: np.ndarray  # 1 = occupied
    origin: tuple[float, float]
    resolution: float

    def to_cell(self, x: float, y: float) -> tuple[int, int]:
        return int((y - self.origin[1]) / self.resolution), int((x - self.origin[0]) / self.resolution)

    def to_world(self, r: int, c: int) -> tuple[float, float]:
        return self.origin[0] + (c + 0.5) * self.resolution, self.origin[1] + (r + 0.5) * self.resolution

    def inside(self, r: int, c: int) -> bool:
        return 0 <= r < self.grid.shape[0] and 0 <= c < self.grid.shape[1]


def astar(gm: GridMap, start: tuple[float, float], goal: tuple[float, float],
          soft: Optional[np.ndarray] = None) -> Optional[list[tuple[float, float]]]:
    """A* over `gm.grid` (hard obstacles). `soft` is an optional per-cell extra cost that keeps
    paths away from obstacles where space allows (soft inflation)."""
    sr, sc = gm.to_cell(*start)
    gr, gc = gm.to_cell(*goal)
    g = gm.grid
    if not gm.inside(sr, sc) or not gm.inside(gr, gc):
        return None
    if g[gr, gc]:
        return None
    nbrs = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
    openq = [(0.0, 0.0, (sr, sc))]
    came: dict[tuple[int, int], tuple[int, int]] = {}
    cost = {(sr, sc): 0.0}
    while openq:
        _, gcost, cur = heapq.heappop(openq)
        if cur == (gr, gc):
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return [gm.to_world(r, c) for r, c in path]
        if gcost > cost.get(cur, math.inf):
            continue
        for dr, dc, w in nbrs:
            nr, nc = cur[0] + dr, cur[1] + dc
            # never enter an occupied cell from free space; when the start lies inside the
            # inflation band the robot may move through occupied cells to escape it
            if not gm.inside(nr, nc) or (g[nr, nc] and not g[cur]):
                continue
            # no corner cutting: a diagonal step needs both orthogonal neighbours free
            if dr and dc and not g[cur] and (g[cur[0] + dr, cur[1]] or g[cur[0], cur[1] + dc]):
                continue
            nc_ = gcost + w * (1.0 + (float(soft[nr, nc]) if soft is not None else 0.0))
            if nc_ < cost.get((nr, nc), math.inf):
                cost[(nr, nc)] = nc_
                came[(nr, nc)] = cur
                h = math.hypot(gr - nr, gc - nc)
                heapq.heappush(openq, (nc_ + h, nc_, (nr, nc)))
    return None


def line_free(gm: GridMap, a: tuple[float, float], b: tuple[float, float]) -> bool:
    n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / (gm.resolution * 0.5)) + 1
    for i in range(n + 1):
        t = i / n
        r, c = gm.to_cell(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        if not gm.inside(r, c) or gm.grid[r, c]:
            return False
    return True


def resample(path: list[tuple[float, float]], step: float = 0.1) -> list[tuple[float, float]]:
    """Densify a polyline so that lookahead selection works on long straight segments."""
    if len(path) < 2:
        return path
    out = [path[0]]
    for a, b in zip(path, path[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / step))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


def soft_cost(grid: np.ndarray, levels: list[tuple[int, float]]) -> np.ndarray:
    """Layered proximity cost from a hard grid: [(radius_cells, cost), ...] (largest radius first)."""
    cost = np.zeros(grid.shape, dtype=np.float32)
    for rad, c in levels:
        cost[dilate(grid, rad).astype(bool)] = c
    cost[grid.astype(bool)] = 0
    return cost


def shortcut(gm: GridMap, path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(path) < 3:
        return path
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not line_free(gm, path[i], path[j]):
            j -= 1
        out.append(path[j])
        i = j
    return out


@dataclass
class PurePursuit:
    lookahead: float = 0.5
    max_v: float = 0.6
    max_w: float = 1.5
    goal_tol: float = 0.15
    slow_dist: float = 0.8
    stop_dist: float = 0.35

    def command(self, pose: tuple[float, float, float], path: list[tuple[float, float]], idx: int,
                min_front: float) -> tuple[float, float, int, bool]:
        x, y, th = pose
        # advance along the path
        while idx < len(path) - 1 and math.hypot(path[idx][0] - x, path[idx][1] - y) < self.lookahead:
            idx += 1
        tx, ty = path[idx]
        dist_goal = math.hypot(path[-1][0] - x, path[-1][1] - y)
        if dist_goal < self.goal_tol:
            return 0.0, 0.0, idx, True
        dx, dy = tx - x, ty - y
        lx = math.cos(th) * dx + math.sin(th) * dy
        ly = -math.sin(th) * dx + math.cos(th) * dy
        ld2 = max(lx * lx + ly * ly, 1e-6)
        curvature = 2 * ly / ld2
        heading_err = math.atan2(ly, lx)
        v = self.max_v
        if abs(heading_err) > 0.9:  # rotate in place toward the path first
            return 0.0, math.copysign(min(self.max_w, 1.2), heading_err), idx, False
        v *= max(0.25, 1 - abs(heading_err) / 1.2)
        v = min(v, max(0.12, dist_goal))  # approach regulation
        if min_front < self.slow_dist:
            v *= max(0.0, (min_front - self.stop_dist) / (self.slow_dist - self.stop_dist))
        w = max(-self.max_w, min(self.max_w, v * curvature if v > 0.05 else 1.5 * heading_err))
        return v, w, idx, False


@dataclass
class OdomEKF:
    """EKF on [x, y, theta]: prediction from wheel odometry, update from integrated IMU yaw."""
    x: np.ndarray = field(default_factory=lambda: np.zeros(3))
    P: np.ndarray = field(default_factory=lambda: np.eye(3) * 1e-4)
    q_trans: float = 0.02  # odometry noise per metre (fraction)
    q_rot: float = 0.05  # per radian
    r_yaw: float = 0.01 ** 2
    imu_yaw: float = 0.0

    def predict(self, ds: float, dth: float) -> None:
        th = self.x[2]
        self.x += np.array([ds * math.cos(th + dth / 2), ds * math.sin(th + dth / 2), dth])
        F = np.array([[1, 0, -ds * math.sin(th + dth / 2)], [0, 1, ds * math.cos(th + dth / 2)], [0, 0, 1]])
        Q = np.diag([(self.q_trans * abs(ds)) ** 2 + 1e-8, (self.q_trans * abs(ds)) ** 2 + 1e-8,
                     (self.q_rot * abs(dth)) ** 2 + 1e-8])
        self.P = F @ self.P @ F.T + Q

    def update_yaw(self, yaw_meas: float) -> None:
        H = np.array([[0, 0, 1.0]])
        y = math.atan2(math.sin(yaw_meas - self.x[2]), math.cos(yaw_meas - self.x[2]))
        S = H @ self.P @ H.T + self.r_yaw
        K = self.P @ H.T / S
        self.x = self.x + (K * y).ravel()
        self.P = (np.eye(3) - K @ H) @ self.P

    def reset(self, x: float, y: float, th: float) -> None:
        self.x = np.array([x, y, th], dtype=float)
        self.imu_yaw = th
        self.P = np.eye(3) * 1e-4


@dataclass
class LogOddsMap:
    gm: GridMap
    logodds: np.ndarray = None  # type: ignore[assignment]
    l_occ: float = 0.85
    l_free: float = -0.4

    def __post_init__(self):
        if self.logodds is None:
            self.logodds = np.zeros(self.gm.grid.shape, dtype=np.float32)

    def integrate(self, pose: tuple[float, float, float], angles: np.ndarray, ranges: np.ndarray, r_max: float) -> None:
        x, y, th = pose
        res = self.gm.resolution
        for a, r in zip(angles[::2], ranges[::2]):
            hit = r < r_max - 1e-3
            n = int(min(r, r_max) / res)
            ca, sa = math.cos(th + a), math.sin(th + a)
            for k in range(n):
                rr, cc = self.gm.to_cell(x + ca * k * res, y + sa * k * res)
                if self.gm.inside(rr, cc):
                    self.logodds[rr, cc] = max(-4.0, self.logodds[rr, cc] + self.l_free)
            if hit:
                rr, cc = self.gm.to_cell(x + ca * r, y + sa * r)
                if self.gm.inside(rr, cc):
                    self.logodds[rr, cc] = min(4.0, self.logodds[rr, cc] + self.l_occ)

    def probabilities(self) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-self.logodds))


def distance_field(grid: np.ndarray, max_cells: int = 12) -> np.ndarray:
    """Approximate Euclidean distance (in cells) to the nearest occupied cell, saturated at max_cells."""
    dist = np.full(grid.shape, float(max_cells), dtype=np.float32)
    occ = grid.astype(bool)
    dist[occ] = 0.0
    for r in range(1, max_cells):
        ring = dilate(occ.astype(np.uint8), r).astype(bool) & (dist > r)
        dist[ring] = float(r)
    return dist


@dataclass
class ScanMatcher:
    """Correlative scan matching on a likelihood field of the static map (map-based localisation,
    comparable in purpose to AMCL's likelihood-field model). Dynamic obstacles are outliers that the
    saturated field tolerates."""
    gm: GridMap
    sigma: float = 0.1
    field_: np.ndarray = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.field_ is None:
            d = distance_field(self.gm.grid) * self.gm.resolution
            self.field_ = np.exp(-(d ** 2) / (2 * self.sigma ** 2)).astype(np.float32)

    def score(self, xs: np.ndarray, ys: np.ndarray) -> float:
        c = ((xs - self.gm.origin[0]) / self.gm.resolution).astype(int)
        r = ((ys - self.gm.origin[1]) / self.gm.resolution).astype(int)
        ok = (r >= 0) & (r < self.field_.shape[0]) & (c >= 0) & (c < self.field_.shape[1])
        return float(self.field_[r[ok], c[ok]].sum() / max(len(xs), 1))

    def match(self, pose: tuple[float, float, float], offset: tuple[float, float], angles: np.ndarray,
              ranges: np.ndarray, r_max: float, lin: float = 0.2, ang: float = 0.08,
              steps: int = 5) -> tuple[tuple[float, float, float], float, float]:
        """Returns (best pose, best score, score at the prior pose)."""
        hit = ranges < r_max - 1e-3
        a, rr = angles[hit][::2], ranges[hit][::2]
        if len(rr) < 20:
            return pose, 0.0, 0.0
        best, best_s = pose, -1.0
        prior_s = 0.0
        for dth in np.linspace(-ang, ang, steps):
            th = pose[2] + dth
            ox = math.cos(th) * offset[0] - math.sin(th) * offset[1]
            oy = math.sin(th) * offset[0] + math.cos(th) * offset[1]
            px = rr * np.cos(th + a) + ox
            py = rr * np.sin(th + a) + oy
            for dx in np.linspace(-lin, lin, steps):
                for dy in np.linspace(-lin, lin, steps):
                    s = self.score(px + pose[0] + dx, py + pose[1] + dy)
                    if dx == 0 and dy == 0 and dth == 0:
                        prior_s = s
                    if s > best_s:
                        best_s, best = s, (pose[0] + dx, pose[1] + dy, th)
        return best, best_s, prior_s
