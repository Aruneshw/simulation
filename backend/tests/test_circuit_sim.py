import math

import pytest

from roboverse.engines.circuit.mna import simulate
from roboverse.engines.circuit.spice import parse_ascii_raw, to_kicad_netlist, to_spice


def divider(cb):
    cb.add("V1", "source.dc_voltage", 0, 0, voltage=10.0)
    cb.add("R1", "passive.resistor", 0, 0, resistance=1000.0)
    cb.add("R2", "passive.resistor", 0, 0, resistance=3000.0)
    cb.wire("V1.+", "R1.1", "VIN"); cb.wire("R1.2", "R2.1", "MID"); cb.wire("R2.2", "V1.-")
    return cb


def test_divider_op(cb, registry):
    res = simulate(divider(cb).c, registry, "op")
    assert res["status"] == "ok" and res["engine"] == "builtin-mna"
    assert res["nodes"]["MID"] == pytest.approx(7.5, abs=1e-6)
    assert res["elements"]["V1"]["i"] == pytest.approx(10 / 4000, rel=1e-6)


def test_rc_time_constant(cb, registry):
    cb.add("V1", "source.dc_voltage", 0, 0, voltage=5.0)
    cb.add("R1", "passive.resistor", 0, 0, resistance=1000.0)
    cb.add("C1", "passive.capacitor", 0, 0, capacitance=1e-6)
    cb.wire("V1.+", "R1.1"); cb.wire("R1.2", "C1.1", "VC"); cb.wire("C1.2", "V1.-")
    res = simulate(cb.c, registry, "tran", t_stop=5e-3, dt=1e-6, probes=["VC"])
    w = res["waveforms"]
    i = min(range(len(w["t"])), key=lambda k: abs(w["t"][k] - 1e-3))
    assert w["VC"][i] == pytest.approx(5 * (1 - math.exp(-1)), rel=0.01)  # one time constant
    assert w["VC"][-1] == pytest.approx(5 * (1 - math.exp(-5)), rel=0.01)


def test_diode_forward_drop(cb, registry):
    cb.add("V1", "source.dc_voltage", 0, 0, voltage=5.0)
    cb.add("R1", "passive.resistor", 0, 0, resistance=430.0)
    cb.add("D1", "diode.1n4148", 0, 0)
    cb.wire("V1.+", "R1.1"); cb.wire("R1.2", "D1.A", "A"); cb.wire("D1.K", "V1.-")
    res = simulate(cb.c, registry, "op")
    assert 0.6 < res["nodes"]["A"] < 0.8  # ~10 mA through a 1N4148


def test_battery_internal_resistance(cb, registry):
    cb.add("B", "battery.lipo_3s_2200", 0, 0)
    cb.add("R", "passive.resistor", 0, 0, resistance=1.0)
    cb.wire("B.+", "R.1", "VBAT"); cb.wire("R.2", "B.-")
    res = simulate(cb.c, registry, "op")
    v = res["nodes"]["VBAT"]
    assert v == pytest.approx(11.1 * 1.0 / 1.03, rel=1e-4)


def test_unsupported_parts_reported_not_faked(cb, registry):
    divider(cb)
    cb.add("Q1", "bjt.2n2222a", 0, 0)
    res = simulate(cb.c, registry, "op")
    assert any(s["instance"] == "Q1" for s in res["skipped"])
    net, skipped = to_spice(cb.c, registry)
    assert "NOT EXPORTED: Q1" in net and skipped


def test_spice_and_kicad_export(cb, registry):
    divider(cb)
    net, _ = to_spice(cb.c, registry)
    assert "RR1 VIN MID 1000" in net and "VV1 VIN 0 DC 10" in net and net.strip().endswith(".end")
    k = to_kicad_netlist(cb.c, registry)
    assert k.count("(") == k.count(")") and '(name "MID")' in k and '(ref "R1")' in k


def test_parse_ngspice_raw():
    raw = """Title: x
Plotname: Transient Analysis
Flags: real
No. Variables: 2
No. Points: 2
Variables:
	0	time	time
	1	v(out)	voltage
Values:
 0	0.000000e+00
	1.000000e+00
 1	1.000000e-03
	2.500000e+00
"""
    d = parse_ascii_raw(raw)
    assert d["time"] == [0.0, 1e-3] and d["v(out)"] == [1.0, 2.5]
