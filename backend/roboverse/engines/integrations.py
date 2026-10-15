"""External engineering tool detection and environment health.

Every integration is optional. Status reflects what is actually installed; the
UI never presents an unavailable engine as working.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys

TOOLS = {
    "mujoco": {"kind": "python", "module": "mujoco", "used_for": "3D rigid-body physics backend", "license": "Apache-2.0",
               "install": "pip install mujoco"},
    "manifold3d": {"kind": "python", "module": "manifold3d", "used_for": "parametric CAD booleans/extrusion", "license": "Apache-2.0",
                   "install": "pip install manifold3d"},
    "ngspice": {"kind": "binary", "bin": "ngspice", "used_for": "full SPICE circuit simulation (BJT/MOSFET/op-amp models)",
                "license": "BSD-3-Clause (mostly)", "install": "apt install ngspice / brew install ngspice"},
    "kicad-cli": {"kind": "binary", "bin": "kicad-cli", "used_for": "schematic/PCB ERC, DRC and fabrication outputs",
                  "license": "GPL-3.0 (separate process)", "install": "https://www.kicad.org/download/"},
    "freecad": {"kind": "binary", "bin": "freecadcmd", "alt": ["FreeCADCmd", "freecad"], "used_for": "B-rep CAD, STEP export",
                "license": "LGPL-2.0+ (separate process)", "install": "https://www.freecad.org/downloads.php"},
    "gazebo": {"kind": "binary", "bin": "gz", "used_for": "Gazebo Sim (export target; run the generated ROS 2 package)",
               "license": "Apache-2.0", "install": "https://gazebosim.org/docs"},
    "ros2": {"kind": "binary", "bin": "ros2", "used_for": "ROS 2 middleware, Nav2, MoveIt 2", "license": "Apache-2.0",
             "install": "https://docs.ros.org"},
    "webots": {"kind": "binary", "bin": "webots", "used_for": "alternative robot simulator (adapter slot)", "license": "Apache-2.0",
               "install": "https://cyberbotics.com"},
    "pybullet": {"kind": "python", "module": "pybullet", "used_for": "alternative physics backend (adapter slot)", "license": "zlib",
                 "install": "pip install pybullet"},
    "platformio": {"kind": "binary", "bin": "pio", "alt": ["platformio"], "used_for": "embedded firmware builds",
                   "license": "Apache-2.0", "install": "pip install platformio"},
    "qemu-system-arm": {"kind": "binary", "bin": "qemu-system-arm", "used_for": "MCU emulation (not validated for listed boards)",
                        "license": "GPL-2.0 (separate process)", "install": "apt install qemu-system-arm"},
    "opencv": {"kind": "python", "module": "cv2", "used_for": "computer-vision lab", "license": "Apache-2.0",
               "install": "pip install opencv-python-headless"},
    "open3d": {"kind": "python", "module": "open3d", "used_for": "point-cloud processing", "license": "MIT",
               "install": "pip install open3d"},
}


def _version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        txt = (out.stdout or out.stderr).strip().splitlines()
        return txt[0][:120] if txt else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def tool_status() -> dict:
    res = {}
    for name, t in TOOLS.items():
        entry = {"used_for": t["used_for"], "license": t["license"], "install": t["install"], "available": False, "version": None}
        if t["kind"] == "python":
            spec = importlib.util.find_spec(t["module"])
            if spec is not None:
                entry["available"] = True
                try:
                    mod = __import__(t["module"])
                    entry["version"] = getattr(mod, "__version__", None)
                except Exception:  # noqa: BLE001
                    entry["available"] = False
        else:
            path = shutil.which(t["bin"]) or next((shutil.which(a) for a in t.get("alt", []) if shutil.which(a)), None)
            if path:
                entry["available"] = True
                entry["path"] = path
        res[name] = entry
    return res


def system_resources() -> dict:
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "cpu_count": os.cpu_count()}
    try:
        import psutil  # noqa: PLC0415
        vm = psutil.virtual_memory()
        du = psutil.disk_usage(os.getcwd())
        info.update({"cpu_percent": psutil.cpu_percent(interval=None), "memory_total_gb": round(vm.total / 1e9, 2),
                     "memory_used_percent": vm.percent, "disk_free_gb": round(du.free / 1e9, 2)})
    except ImportError:
        pass
    from .perception import compute_capabilities  # noqa: PLC0415
    info["compute"] = compute_capabilities()
    return info
