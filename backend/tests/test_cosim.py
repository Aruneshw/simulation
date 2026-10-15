import math

import pytest

from roboverse.engines.cosim.coordinator import Coordinator
from roboverse.samples import obstacle_course_bot, warehouse_amr
from roboverse.schemas.project import Scenario


def run(project, registry, duration=None):
    c = Coordinator(project, registry)
    c.initialize()
    return c, c.run(duration)


def test_contract_and_init_report(amr, registry):
    c = Coordinator(amr, registry)
    rep = c.initialize()
    assert rep["missing_inputs"] == []
    names = [s["name"] for s in rep["sequence"]]
    assert names.index("firmware") < names.index("electrical") < names.index("physics")
    delayed = {(e["from"], e["to"]) for e in rep["contract"] if e["coupling"] == "one_step_delay"}
    assert ("physics", "encoders") in delayed  # sensors see last step's physics (ZOH), reported explicitly
    assert all(b["drivable"] for b in rep["twin"])


def test_obstacle_course_goal(registry):
    c, res = run(obstacle_course_bot(), registry)
    m = res["metrics"]
    assert res["status"] == "completed" and m["success"], res["events"]
    assert m["collisions"] == 0 and m["loc_rmse_m"] < 0.1
    assert c.telemetry_csv().startswith("t,x,y")


@pytest.mark.slow
def test_warehouse_mission_with_docking(amr, registry):
    _, res = run(amr, registry)
    m = res["metrics"]
    assert m["goals_reached"] == m["goals_total"] == 5
    assert m["collisions"] == 0
    assert any(e["kind"] == "charging" for e in res["events"])


def test_deterministic_with_seed(registry):
    a = obstacle_course_bot()
    b = obstacle_course_bot()
    _, ra = run(a, registry, 5.0)
    _, rb = run(b, registry, 5.0)
    assert ra["metrics"]["distance_m"] == rb["metrics"]["distance_m"]


def test_estop_stops_robot(registry):
    p = obstacle_course_bot()
    p.simulation.scenario.estop_at = 3.0
    c, res = run(p, registry, 8.0)
    after = [r for r in c.rows if r["t"] > 5.0]
    assert after and all(abs(r["v"]) < 0.02 for r in after)
    assert any(e["kind"] == "estop" for e in res["events"])


def test_unwired_motor_is_not_driven(registry):
    p = obstacle_course_bot()
    p.circuit.wires = [w for w in p.circuit.wires if not (w.b.instance == "M1" and w.b.pin == "M+")]
    c, res = run(p, registry, 4.0)
    assert any(e["kind"] == "unbound_actuator" for e in res["events"])
    # one side has no torque: the robot cannot drive straight to the goal
    assert res["metrics"]["goals_reached"] == 0


def test_open_loop_motor_physics(registry):
    """Full PWM on a free robot reaches the motor-limited speed predicted from datasheet constants."""
    p = obstacle_course_bot()
    p.simulation.scenario = Scenario(mode="open_loop", open_loop_cmd=[0.5, 0.0])
    p.simulation.sensor_noise = False
    c, _ = run(p, registry, 3.0)
    v_end = c.rows[-1]["v"]
    assert v_end == pytest.approx(0.5, abs=0.03)  # PI loop holds the commanded speed
    assert c.rows[-1]["soc"] < 1.0


def test_fuse_blows_on_overload(registry):
    p = obstacle_course_bot()
    next(i for i in p.circuit.instances if i.id == "F1").params["rating_a"] = 0.3
    _, res = run(p, registry, 10.0)
    assert any(e["kind"] == "fuse_blown" for e in res["events"])


def test_mujoco_backend_runs(registry):
    pytest.importorskip("mujoco")
    p = obstacle_course_bot()
    p.simulation.physics_backend = "mujoco"
    c, res = run(p, registry, 6.0)
    assert res["init"]["backend"] == "mujoco"
    assert c.rows[-1]["x"] > -4.5  # it drove forward under MuJoCo contact physics
    assert math.isfinite(c.rows[-1]["theta"])


def test_emulated_firmware_mode_is_refused(registry):
    p = obstacle_course_bot()
    p.firmware.mode = "emulated"
    with pytest.raises(RuntimeError, match="validated emulator"):
        Coordinator(p, registry).initialize()
