import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from roboverse.engines.export.package import export_package, import_package
from roboverse.engines.export.ros2 import ros2_package, world_sdf
from roboverse.engines.firmware.codegen import generate_platformio_project, parse_compiler_output
from roboverse.engines.validation import validate_project

STUB = Path(__file__).parent / "arduino_stub"


def test_codegen_uses_pin_map(amr):
    files = generate_platformio_project(amr)
    main = files["src/main.cpp"]
    assert "#define PIN_L_PWM 25" in main and "#define PIN_R_ENC_A 18" in main
    assert "board = esp32dev" in files["platformio.ini"]
    assert "HIL" in files["HIL_PROTOCOL.txt"]


@pytest.mark.skipif(not shutil.which("g++"), reason="g++ not available")
@pytest.mark.parametrize("define", ["-DESP32", ""])
def test_generated_firmware_compiles_against_stub(amr, tmp_path, define):
    src = tmp_path / "main.cpp"
    src.write_text(generate_platformio_project(amr)["src/main.cpp"])
    cmd = ["g++", "-std=c++17", "-fsyntax-only", "-Wall", f"-I{STUB}", str(src)] + ([define] if define else [])
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_compiler_diagnostics_parser():
    log = "src/main.cpp:12:5: error: 'foo' was not declared in this scope\nsrc/main.cpp:3: warning: unused"
    d = parse_compiler_output(log)
    assert d[0] == {"file": "src/main.cpp", "line": 12, "column": 5, "severity": "error",
                    "message": "'foo' was not declared in this scope"}
    assert d[1]["severity"] == "warning"


def test_ros2_package_and_world(amr):
    files = ros2_package(amr)
    names = set(files)
    assert any(n.endswith("package.xml") for n in names) and any(n.endswith("gazebo.launch.py") for n in names)
    yaml = next(v for k, v in files.items() if k.endswith("ros2_controllers.yaml"))
    assert "wheel_separation: 0.34" in yaml
    assert "<include>" in world_sdf(amr)


def test_package_roundtrip_and_tamper_detection(amr, registry):
    amr.preserved["custom_vendor_field"] = {"keep": True}
    blob, manifest = export_package(amr, registry)
    assert manifest["format_version"] == 1
    paths = {f["path"] for f in manifest["files"]}
    assert {"project.json", "robot/robot.urdf", "circuit/netlist.cir", "circuit/netlist.net",
            "cad/chassis_plate.stl", "firmware/src/main.cpp", "sim/config.json"} <= paths
    p2, report, _ = import_package(blob)
    assert report["errors"] == []
    assert p2.model_dump() == amr.model_dump()
    # tamper with a file: the checksum must catch it
    zin = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "sim/config.json":
                data = json.dumps({"dt": 1}).encode()
            z.writestr(n, data)
        z.writestr("vendor/notes.txt", "keep me")
    _, rep2, _ = import_package(out.getvalue())
    assert any("checksum mismatch: sim/config.json" in e for e in rep2["errors"])
    assert "vendor/notes.txt" in rep2["preserved_files"]


def test_full_validation_passes_on_reference(amr, registry):
    res = validate_project(amr, registry, "pre_simulation")
    assert res["summary"]["passed"], [i for i in res["issues"] if i["severity"] in ("error", "critical")]


def test_validation_flags_bad_scenario(amr, registry):
    amr.simulation.scenario.waypoints.append([-5.5, -3.5])  # inside a rack
    amr.firmware.mode = "emulated"
    res = validate_project(amr, registry)
    codes = {i["code"] for i in res["issues"]}
    assert {"S011", "F002"} <= codes and not res["summary"]["passed"]
