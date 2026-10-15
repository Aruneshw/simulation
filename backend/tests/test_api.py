import time

import pytest
from fastapi.testclient import TestClient

from roboverse.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_system_and_library(client):
    s = client.get("/api/system").json()
    assert s["tools"]["manifold3d"]["available"] is True
    assert "gpu" in s["resources"]["compute"]
    lib = client.get("/api/library", params={"q": "lidar"}).json()
    assert any(i["id"] == "sensor.rplidar_a1" for i in lib["items"])
    assert client.get("/api/library/driver.l298n").json()["datasheet"].startswith("https://")


def test_project_lifecycle(client):
    p = client.post("/api/projects", json={"name": "API AMR", "template": "obstacle_course"}).json()
    pid = p["id"]
    assert client.get(f"/api/projects/{pid}").json()["name"] == "API AMR"
    p["description"] = "edited"
    assert client.put(f"/api/projects/{pid}", json=p).json()["saved"]
    assert any(x["id"] == pid for x in client.get("/api/projects").json())
    v = client.post("/api/validate", json=p).json()
    assert v["summary"]["passed"]
    assert client.get(f"/api/projects/{pid}/validation-reports").json()
    urdf = client.post("/api/export/urdf", json=p)
    assert urdf.status_code == 200 and b"<robot" in urdf.content
    pkg = client.post("/api/export/package", json=p)
    assert pkg.status_code == 200
    imp = client.post("/api/import/package", files={"file": ("x.rvproj", pkg.content, "application/zip")}).json()
    assert imp["report"]["errors"] == []
    assert client.delete(f"/api/projects/{pid}").json()["deleted"] == pid


def test_circuit_endpoints(client):
    p = client.post("/api/projects", json={"name": "c", "template": "warehouse_amr_faulty"}).json()
    res = client.post("/api/circuit/check", json=p).json()
    assert any(i["code"] == "E010" for i in res["issues"])
    sim = client.post("/api/circuit/simulate", json=p, params={"analysis": "op"}).json()
    assert sim["engine"] == "builtin-mna" and sim["skipped"]  # MCU/driver are not circuit-simulated
    blocked = client.post("/api/simulations", json={"project": p})
    assert blocked.status_code == 409  # validation gate before simulation


def test_live_simulation_over_websocket(client):
    p = client.post("/api/projects", json={"name": "ws", "template": "obstacle_course"}).json()
    p["simulation"]["real_time_factor"] = 0  # as fast as possible
    r = client.post("/api/simulations", json={"project": p}).json()
    run = r["run_id"]
    assert r["init"]["backend"] == "builtin_planar"
    with client.websocket_connect(f"/ws/simulations/{run}") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post(f"/api/simulations/{run}/control", json={"action": "start"})
        frames, finished = 0, None
        while True:
            m = ws.receive_json()
            if m["type"] == "frame":
                frames += 1
                assert "row" in m and "x" in m["row"]
            if m["type"] == "finished":
                finished = m
                break
    assert frames > 10 and finished["result"]["metrics"]["success"]
    for _ in range(20):
        hist = client.get(f"/api/projects/{p['id']}/simulations").json()
        if hist and hist[0]["status"] == "completed":
            break
        time.sleep(0.1)
    assert hist[0]["metrics"]["goals_reached"] == 1
    csv_text = client.get(f"/api/simulations/{run}/telemetry.csv").text
    assert csv_text.startswith("t,")


def test_cad_and_robot_generation(client):
    part = {"id": "p", "name": "p", "features": [{"id": "b", "op": "box", "params": {"x": 0.1, "y": 0.1, "z": 0.1}}]}
    rep = client.post("/api/cad/part", json=part).json()
    assert abs(rep["volume_m3"] - 1e-3) < 1e-9 and rep["mesh"]["indices"]
    robot = client.post("/api/robot/generate", json={"drivetrain": {"drive_type": "four_wheel"}}).json()
    assert len(robot["actuators"]) == 4
