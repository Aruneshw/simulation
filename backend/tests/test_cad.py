import math

import numpy as np
import pytest

from roboverse.engines.cad.mesh_io import mesh_check, parse_stl, to_stl_ascii
from roboverse.engines.cad.parametric import CadError, build_part, example_parts, interference, mesh_arrays, part_report, placed
from roboverse.engines.mass import mesh_mass_properties, primitive_inertia
from roboverse.schemas.project import CadPart, Feature


def test_plate_volume_matches_parameters():
    plate = example_parts()[0]
    rep = part_report(plate)
    p = plate.parameters
    expected = p["thickness"] * (p["length"] * p["width"] - 4 * math.pi * p["hole_r"] ** 2 - 0.06 * 0.04)
    assert rep["volume_m3"] == pytest.approx(expected, rel=2e-3)  # holes are faceted polygons
    assert rep["mass_kg"] == pytest.approx(expected * 2700, rel=2e-3)


def test_parametric_update():
    plate = example_parts()[0]
    v1 = build_part(plate).volume()
    plate.parameters["thickness"] *= 2
    assert build_part(plate).volume() == pytest.approx(2 * v1, rel=1e-6)


def test_box_inertia_matches_analytic():
    part = CadPart(id="b", name="b", material="steel", features=[Feature(id="f", op="box", params={"x": 0.2, "y": 0.1, "z": 0.05})])
    v, f = mesh_arrays(build_part(part))
    mp = mesh_mass_properties(v, f, 7850)
    ana = primitive_inertia("box", [0.2, 0.1, 0.05], mp["mass"])
    assert np.allclose(mp["inertia"][:3], ana[:3], rtol=1e-6)
    assert np.allclose(mp["com"], [0, 0, 0], atol=1e-9)


def test_boolean_difference_and_errors():
    br = example_parts()[1]
    rep = part_report(br)
    assert rep["genus"] >= 0 and rep["volume_m3"] > 0
    bad = CadPart(id="x", name="x", features=[Feature(id="u", op="union", operands=["nope"])])
    with pytest.raises(CadError):
        build_part(bad)
    with pytest.raises(CadError):
        build_part(CadPart(id="y", name="y", parameters={"a": 1},
                           features=[Feature(id="f", op="box", params={"x": "$a + __import__('os')", "y": 1, "z": 1})]))


def test_interference():
    plate = example_parts()[0]
    a = placed(plate, [0, 0, 0])
    b = placed(plate, [0.1, 0, 0])
    c = placed(plate, [1.0, 0, 0])
    hits = interference([("a", a), ("b", b), ("c", c)])
    assert [(h["a"], h["b"]) for h in hits] == [("a", "b")]


def test_stl_roundtrip_and_mesh_flag():
    v, f = mesh_arrays(build_part(example_parts()[2]))
    v2, f2 = parse_stl(to_stl_ascii(v, f).encode())
    chk = mesh_check(v2, f2)
    assert chk["watertight"] and chk["triangles"] == len(f)
