"""Portable project package (.rvproj = zip) with a versioned manifest.

Layout:
  manifest.json            format version, app version, file list with sha256, dependencies
  project.json             the full shared project model (source of truth)
  robot/robot.urdf|.sdf|.xacro
  circuit/netlist.cir      SPICE (supported subset; unsupported parts listed as comments)
  circuit/netlist.net      KiCad netlist for Pcbnew
  cad/<part>.stl           tessellated parametric parts (source = feature tree in project.json)
  firmware/...             generated PlatformIO project + user sources
  sim/config.json          reproducible simulation configuration
  results/<run>.csv        telemetry of stored runs
  assets/<id>/<filename>   original imported files, byte-for-byte
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Optional

from ... import __version__
from ...library.registry import LIBRARY_VERSION, Registry
from ...schemas.project import SCHEMA_VERSION, Project
from ..cad.mesh_io import to_stl_ascii
from ..cad.parametric import CadError, build_part, mesh_arrays
from ..circuit.spice import to_kicad_netlist, to_spice
from ..description import to_sdf, to_urdf, to_xacro
from ..firmware.codegen import generate_platformio_project
from ..integrations import tool_status

FORMAT = "roboverse-project"
FORMAT_VERSION = 1


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def export_package(project: Project, registry: Registry, assets: Optional[list[dict]] = None,
                   runs: Optional[list[dict]] = None) -> tuple[bytes, dict]:
    files: dict[str, bytes] = {}
    report = {"warnings": [], "skipped": []}
    files["project.json"] = project.model_dump_json(indent=2).encode()
    if project.robot.links:
        files["robot/robot.urdf"] = to_urdf(project.robot, project.preserved.get("urdf")).encode()
        files["robot/robot.sdf"] = to_sdf(project.robot).encode()
        files["robot/robot.xacro"] = to_xacro(project.robot).encode()
    if project.circuit.instances:
        cir, skipped = to_spice(project.circuit, registry, project.name)
        files["circuit/netlist.cir"] = cir.encode()
        files["circuit/netlist.net"] = to_kicad_netlist(project.circuit, registry, project.name).encode()
        for s in skipped:
            report["skipped"].append(f"SPICE: {s['instance']} ({s['component']}) has no circuit model; kept in project.json and KiCad netlist")
    for part in project.cad.parts:
        if part.kind != "parametric":
            continue
        try:
            v, f = mesh_arrays(build_part(part))
            files[f"cad/{part.id}.stl"] = to_stl_ascii(v, f, part.id).encode()
        except CadError as e:
            report["warnings"].append(f"CAD part {part.id}: {e}")
    for path, content in generate_platformio_project(project).items():
        files[f"firmware/{path}"] = content.encode()
    files["sim/config.json"] = json.dumps(project.simulation.model_dump(), indent=2).encode()
    for r in runs or []:
        if r.get("telemetry_csv"):
            files[f"results/{r['id']}.csv"] = r["telemetry_csv"].encode()
            files[f"results/{r['id']}.json"] = json.dumps({"metrics": r.get("metrics"), "events": r.get("events")}, indent=2).encode()
    for a in assets or []:
        files[f"assets/{a['id']}/{a['filename']}"] = base64.b64decode(a["content"])
    used = sorted({i.component_id for i in project.circuit.instances} |
                  {a.component_ref for a in project.robot.actuators} |
                  {s.component_ref for s in project.robot.sensors if s.component_ref})
    deps = []
    for cid in used:
        c = registry.get(cid)
        deps.append({"component": cid, "version": c.version if c else None, "found": c is not None,
                     "support_status": c.support_status.value if c else None})
        if c is None:
            report["warnings"].append(f"component '{cid}' is not in the library; the package references it by id only")
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION, "schema_version": SCHEMA_VERSION,
        "app": {"name": "RoboVerse Studio", "version": __version__}, "library_version": LIBRARY_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {"name": project.name, "type": project.type.value},
        "files": [{"path": p, "sha256": _sha(b), "bytes": len(b)} for p, b in sorted(files.items())],
        "dependencies": {"components": deps,
                         "tools": {k: {"available": v["available"], "required_for": v["used_for"]}
                                   for k, v in tool_status().items()}},
        "export_report": report,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for p, b in files.items():
            z.writestr(p, b)
    return buf.getvalue(), manifest


def migrate(data: dict) -> tuple[dict, list[str]]:
    """Upgrade older project documents to the current schema."""
    notes = []
    v = data.get("schema_version", 0)
    if v < 1:
        data.setdefault("bindings", [])
        data.setdefault("preserved", {})
        data["schema_version"] = 1
        notes.append("migrated schema 0 -> 1 (added bindings, preserved)")
    return data, notes


def import_package(blob: bytes) -> tuple[Project, dict, list[dict]]:
    """Returns (project, report, assets). Verifies checksums; unknown files are preserved."""
    report = {"warnings": [], "errors": [], "preserved_files": []}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = set(z.namelist())
        if "manifest.json" not in names or "project.json" not in names:
            raise ValueError("not a RoboVerse package (manifest.json / project.json missing)")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"unknown package format '{manifest.get('format')}'")
        if manifest.get("format_version", 0) > FORMAT_VERSION:
            report["warnings"].append("package was written by a newer RoboVerse version; some data may be ignored")
        listed = {f["path"]: f for f in manifest.get("files", [])}
        for p, meta in listed.items():
            if p not in names:
                report["errors"].append(f"missing file: {p}")
            elif _sha(z.read(p)) != meta["sha256"]:
                report["errors"].append(f"checksum mismatch: {p}")
        data, notes = migrate(json.loads(z.read("project.json")))
        report["warnings"] += notes
        project = Project.model_validate(data)
        assets = []
        for n in names:
            if n.startswith("assets/") and not n.endswith("/"):
                _, aid, fn = n.split("/", 2)
                assets.append({"id": aid, "filename": fn, "content": base64.b64encode(z.read(n)).decode()})
            elif n not in listed and n != "manifest.json":
                report["preserved_files"].append(n)
                project.preserved.setdefault("package_extra_files", {})[n] = base64.b64encode(z.read(n)).decode()
    return project, report, assets
