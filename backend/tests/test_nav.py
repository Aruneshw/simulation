import math

import numpy as np

from roboverse.engines.nav.navigation import GridMap, astar, dilate, resample
from roboverse.engines.world.geometry import Obstacle, circle_penetration, rasterize, raycast
from roboverse.engines.world.templates import make_world


def test_raycast_box_and_circle():
    obs = [Obstacle("b", "box", "box", 5, 0, 0.5, 0.5), Obstacle("c", "cylinder", "circle", 0, 3, r=1.0)]
    r = raycast(obs, 0, 0, np.array([0.0, math.pi / 2, math.pi]), 20.0)
    assert r[0] == np.float64(4.5) or abs(r[0] - 4.5) < 1e-9
    assert abs(r[1] - 2.0) < 1e-9
    assert r[2] == 20.0


def test_penetration_normal():
    ob = Obstacle("b", "box", "box", 0, 0, 1, 1)
    d, nx, ny = circle_penetration(ob, 1.2, 0, 0.3)
    assert abs(d - 0.1) < 1e-9 and nx == 1.0 and ny == 0.0


def test_astar_routes_around_wall():
    grid = np.zeros((50, 50), dtype=np.uint8)
    grid[10:50, 25] = 1
    gm = GridMap(grid, (0, 0), 0.1)
    path = astar(gm, (0.5, 4.5), (4.5, 4.5))
    assert path is not None
    assert min(p[1] for p in path) < 1.0  # had to go around the bottom of the wall
    for x, y in resample(path, 0.05):
        r, c = gm.to_cell(x, y)
        assert grid[r, c] == 0


def test_world_templates_have_collision_geometry():
    for name in ("warehouse", "factory_floor", "obstacle_course"):
        w = make_world(name)
        from roboverse.engines.world.geometry import obstacles_from_world
        obs = obstacles_from_world(w)
        assert obs and rasterize(obs, w.bounds, 0.1).sum() > 0
    assert dilate(np.eye(5, dtype=np.uint8), 1).sum() > 5
