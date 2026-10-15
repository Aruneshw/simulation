import math

import pytest

from roboverse.engines.power.models import Battery, DCMotor, Fuse, HBridge


def test_motor_constants_reproduce_datasheet(registry):
    comp = registry.get("motor.pololu_37d_50to1_12v")
    m = DCMotor.from_component(comp)
    # stall: zero speed at rated voltage gives stall current and torque
    i, tq = m.compute(12.0, 0.0)
    assert i == pytest.approx(5.5, rel=1e-6)
    assert tq == pytest.approx(2.06, rel=1e-3)
    # no-load: the speed where torque = 0 matches 200 rpm within a few percent
    w = 200 * 2 * math.pi / 60
    i0, tq0 = m.compute(12.0, w)
    assert abs(tq0) < 0.05 and i0 == pytest.approx(0.2, abs=0.05)


def test_battery_discharge_and_sag(registry):
    b = Battery.from_component(registry.get("battery.lifepo4_4s_20ah"))
    v_open = b.terminal_voltage(0)
    assert b.terminal_voltage(10) < v_open
    for _ in range(3600):
        b.step(10.0, 1.0)  # 10 A for 1 h
    assert b.soc == pytest.approx(0.5, abs=0.01)
    assert b.energy_wh > 100


def test_hbridge_drop_and_trip():
    h = HBridge(r_ds_on=0.1, v_drop=2.0, i_peak=3.0)
    assert h.output_voltage(1.0, 12.0, 0.0) == pytest.approx(10.0)
    assert h.check(5.0, 0.3) is None
    assert h.check(5.0, 0.3) == "driver_overcurrent_shutdown" and h.tripped
    assert h.output_voltage(1.0, 12.0, 0.0) == 0.0


def test_fuse_i2t():
    f = Fuse(10.0)
    t = 0.0
    while not f.step(20.0, 0.01):
        t += 0.01
        assert t < 10
    assert 0.5 < t < 5  # 2x overload clears in seconds
    g = Fuse(10.0)
    assert not any(g.step(9.0, 0.01) for _ in range(10000))
