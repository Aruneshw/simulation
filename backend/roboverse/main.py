"""RoboVerse Studio API."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .db import (AssetRow, FavoriteRow, ProjectRow, SessionLocal, SimRunRow, UserComponentRow, ValidationReportRow,
                 init_db, new_id)
from .engines.cad.mesh_io import mesh_check, parse_obj, parse_stl, to_obj, to_stl_ascii
from .engines.cad.parametric import CadError, build_part, clearance, interference, mesh_arrays, part_report, placed
from .engines.circuit.compat import check_circuit
from .engines.circuit.mna import simulate as mna_simulate
from .engines.circuit.spice import run_ngspice, to_kicad_netlist, to_spice
from .engines.cosim.coordinator import Coordinator
from .engines.cosim.session import SESSIONS, SimSession
from .engines.description import from_urdf, to_mjcf, to_sdf, to_urdf, to_xacro
from .engines.export.package import export_package, import_package
from .engines.export.ros2 import pkg_name, ros2_package, world_sdf
from .engines.firmware.codegen import build_firmware, generate_platformio_project
from .engines.firmware.targets import target_list
from .engines.integrations import system_resources, tool_status
from .engines.perception import compute_capabilities, zscore_anomalies
from .engines.robot import generate_arm, generate_mobile_robot
from .engines.twin import auto_bind, resolve_twin
from .engines.validation import validate_project
from .engines.world.templates import TEMPLATES as WORLD_TEMPLATES
from .engines.world.templates import make_world
from .library.registry import REGISTRY, import_passives_csv, validate_component
from .samples import TEMPLATES as PROJECT_TEMPLATES
from .samples import blank
from .schemas.library import Component
from .schemas.project import CadPart, Drivetrain, Project, ProjectType

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        for row in db.scalars(select(UserComponentRow)):
            try:
                REGISTRY.add(Component.model_validate(row.data))
            except Exception:  # noqa: BLE001
                continue
    yield


app = FastAPI(title="RoboVerse Studio API", version=__version__,
              description="Design. Connect. Simulate. Validate. Build.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _project_row(db: Session, pid: str) -> ProjectRow:
    row = db.get(ProjectRow, pid)
    if not row:
        raise HTTPException(404, "project not found")
    return row


def _load(row: ProjectRow) -> Project:
    p = Project.model_validate(row.data)
    p.id = row.id
    return p


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def _download(content: bytes | str, filename: str, media: str = "application/octet-stream") -> Response:
    data = content.encode() if isinstance(content, str) else content
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------ system --

@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/system")
def system():
    return {"version": __version__, "resources": system_resources(), "tools": tool_status(),
            "library": REGISTRY.stats(), "sessions_active": sum(1 for s in SESSIONS.sessions.values() if s.status == "running")}


# ----------------------------------------------------------------- library --

def _summary(c: Component, favs: set[str]) -> dict:
    return {"id": c.id, "name": c.name, "category": c.category.value, "manufacturer": c.manufacturer,
            "part_number": c.part_number, "tags": c.tags, "support_status": c.support_status.value, "version": c.version,
            "interfaces": c.interfaces, "symbol": c.symbol, "favorite": c.id in favs, "verified": c.provenance.verified,
            "pins": len(c.pins)}


@app.get("/api/library")
def library(q: str = "", category: Optional[str] = None, status: Optional[str] = None, tag: Optional[str] = None,
            interface: Optional[str] = None, favorites: bool = False, db: Session = Depends(get_db)):
    favs = {r.component_id for r in db.scalars(select(FavoriteRow))}
    items = REGISTRY.search(q, category, status, tag, interface, favs if favorites else None)
    return {"items": [_summary(c, favs) for c in items], "stats": REGISTRY.stats()}


@app.get("/api/library/full")
def library_full():
    """All component definitions (used by the schematic editor for pin layouts)."""
    return [c.model_dump(mode="json") for c in REGISTRY.all()]


@app.get("/api/library/{cid}")
def component(cid: str, version: Optional[str] = None):
    c = REGISTRY.get(cid, version)
    if not c:
        raise HTTPException(404, "component not found")
    return {**c.model_dump(mode="json"), "versions": REGISTRY.versions(cid), "dependency_issues": REGISTRY.dependency_issues(c)}


@app.post("/api/library/import")
def import_components(items: list[dict] = Body(...), source: str = Query("user_import"), db: Session = Depends(get_db)):
    ok, errors = [], {}
    for raw in items:
        c, errs = validate_component(raw, REGISTRY, source)
        if c:
            REGISTRY.add(c)
            db.merge(UserComponentRow(id=c.id, version=c.version, data=c.model_dump(mode="json")))
            ok.append(c.id)
        else:
            errors[raw.get("id", "?")] = errs
    db.commit()
    return {"imported": ok, "errors": errors}


@app.post("/api/library/import/csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8", "replace")
    comps, errs = import_passives_csv(text, REGISTRY)
    for c in comps:
        REGISTRY.add(c)
        db.merge(UserComponentRow(id=c.id, version=c.version, data=c.model_dump(mode="json")))
    db.commit()
    return {"imported": [c.id for c in comps], "errors": errs}


@app.post("/api/library/{cid}/favorite")
def favorite(cid: str, on: bool = True, db: Session = Depends(get_db)):
    row = db.get(FavoriteRow, cid)
    if on and not row:
        db.add(FavoriteRow(component_id=cid))
    if not on and row:
        db.delete(row)
    db.commit()
    return {"id": cid, "favorite": on}


# --------------------------------------------------------------- templates --

@app.get("/api/templates")
def templates():
    return {"projects": [{"id": k, "name": v[0]} for k, v in PROJECT_TEMPLATES.items()],
            "worlds": list(WORLD_TEMPLATES), "project_types": [t.value for t in ProjectType]}


@app.get("/api/world-templates/{name}")
def world_template(name: str):
    if name not in WORLD_TEMPLATES:
        raise HTTPException(404, "unknown world template")
    return make_world(name).model_dump()


# ---------------------------------------------------------------- projects --

class NewProject(BaseModel):
    name: str
    type: ProjectType = ProjectType.amr
    template: Optional[str] = None
    world_template: Optional[str] = None


@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.scalars(select(ProjectRow).order_by(ProjectRow.updated_at.desc())).all()
    return [{"id": r.id, "name": r.name, "type": r.type, "updated_at": r.updated_at.isoformat(),
             "created_at": r.created_at.isoformat(), "description": r.data.get("description", "")} for r in rows]


@app.post("/api/projects")
def create_project(body: NewProject, db: Session = Depends(get_db)):
    if body.template:
        if body.template not in PROJECT_TEMPLATES:
            raise HTTPException(400, "unknown template")
        p = PROJECT_TEMPLATES[body.template][1]()
        p.name = body.name or p.name
    else:
        p = blank(body.name, body.type, body.world_template)
    row = ProjectRow(name=p.name, type=p.type.value, data=p.model_dump(mode="json"))
    db.add(row)
    db.commit()
    return _load(row).model_dump(mode="json")


@app.get("/api/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)):
    return _load(_project_row(db, pid)).model_dump(mode="json")


@app.put("/api/projects/{pid}")
def save_project(pid: str, project: Project, db: Session = Depends(get_db)):
    row = _project_row(db, pid)
    project.id = pid
    row.name, row.type, row.data = project.name, project.type.value, project.model_dump(mode="json")
    db.commit()
    return {"id": pid, "saved": True, "updated_at": row.updated_at.isoformat()}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, db: Session = Depends(get_db)):
    row = _project_row(db, pid)
    for model in (SimRunRow, ValidationReportRow, AssetRow):
        for r in db.scalars(select(model).where(model.project_id == pid)):
            db.delete(r)
    db.delete(row)
    db.commit()
    return {"deleted": pid}


# ---------------------------------------------------------------- analysis --

@app.post("/api/validate")
def validate(project: Project, stage: str = "pre_simulation", db: Session = Depends(get_db)):
    res = validate_project(project, REGISTRY, stage)
    if project.id and db.get(ProjectRow, project.id):
        db.add(ValidationReportRow(project_id=project.id, stage=stage, summary=res["summary"], issues=res["issues"]))
        db.commit()
    return res


@app.get("/api/projects/{pid}/validation-reports")
def validation_reports(pid: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(ValidationReportRow).where(ValidationReportRow.project_id == pid)
                      .order_by(ValidationReportRow.created_at.desc()).limit(50)).all()
    return [{"id": r.id, "stage": r.stage, "summary": r.summary, "created_at": r.created_at.isoformat(),
             "issues": r.issues} for r in rows]


@app.post("/api/circuit/check")
def circuit_check(project: Project):
    return check_circuit(project.circuit, REGISTRY, project.firmware, project.robot.controller_ref)


@app.post("/api/circuit/simulate")
def circuit_simulate(project: Project, analysis: str = "op", engine: str = "builtin", t_stop: float = 1e-3,
                     dt: float = 1e-5, probes: Optional[str] = None):
    if engine == "ngspice":
        net, skipped = to_spice(project.circuit, REGISTRY, project.name, analysis, t_stop, dt)
        return {**run_ngspice(net), "skipped": skipped, "netlist": net}
    if analysis == "tran" and t_stop / dt > 200000:
        raise HTTPException(400, "too many transient steps (max 200k)")
    return mna_simulate(project.circuit, REGISTRY, analysis, t_stop, dt, probes.split(",") if probes else None)


@app.post("/api/twin")
def twin(project: Project):
    b, issues, _ = resolve_twin(project, REGISTRY)
    return {"bindings": [x.to_dict() for x in b], "issues": [i.model_dump() for i in issues]}


@app.post("/api/twin/autobind")
def twin_autobind(project: Project):
    res = auto_bind(project, REGISTRY)
    return {"project": project.model_dump(mode="json"), **res}


class GenerateRobot(BaseModel):
    name: str = "robot"
    drivetrain: Drivetrain = Drivetrain()
    chassis: list[float] = [0.4, 0.3, 0.1]
    chassis_mass: float = 4.0
    wheel_mass: float = 0.15
    motor_ref: str = "motor.pololu_37d_50to1_12v"
    lidar: bool = True
    imu: bool = True
    arm_dof: int = 4


@app.post("/api/robot/generate")
def robot_generate(body: GenerateRobot):
    if body.drivetrain.drive_type == "arm":
        return generate_arm(body.name, body.arm_dof).model_dump()
    return generate_mobile_robot(body.name, body.drivetrain, body.chassis, body.chassis_mass, body.wheel_mass,
                                 body.motor_ref, body.lidar, body.imu).model_dump()


# ---------------------------------------------------------------------- CAD --

@app.post("/api/cad/part")
def cad_part(part: CadPart):
    try:
        return part_report(part)
    except CadError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/cad/assembly-check")
def cad_assembly(project: Project):
    parts = {p.id: p for p in project.cad.parts}
    placed_parts = []
    errors = []
    for item in project.cad.assembly:
        p = parts.get(item.part)
        if not p or p.kind != "parametric":
            errors.append(f"{item.id}: part '{item.part}' missing or not parametric (imported meshes are checked by bounding box only)")
            continue
        try:
            import math as _m  # noqa: PLC0415
            placed_parts.append((item.id, placed(p, item.pose.xyz, [_m.degrees(a) for a in item.pose.rpy])))
        except CadError as e:
            errors.append(f"{item.id}: {e}")
    return {"interference": interference(placed_parts), "clearance": clearance(placed_parts), "errors": errors,
            "note": "Interference volumes are exact mesh booleans; clearance is an AABB lower bound."}


# ------------------------------------------------------------------- export --

EXPORTS = {"urdf", "sdf", "xacro", "mjcf", "spice", "kicad", "world_sdf", "ros2", "firmware", "stl", "obj", "package"}


@app.post("/api/export/{fmt}")
def export(fmt: str, project: Project, part: Optional[str] = None, db: Session = Depends(get_db)):
    if fmt not in EXPORTS:
        raise HTTPException(404, f"unknown export format; available: {sorted(EXPORTS)}")
    base = (project.name or "project").replace(" ", "_")
    if fmt == "urdf":
        return _download(to_urdf(project.robot, project.preserved.get("urdf")), f"{project.robot.name}.urdf", "application/xml")
    if fmt == "sdf":
        return _download(to_sdf(project.robot), f"{project.robot.name}.sdf", "application/xml")
    if fmt == "xacro":
        return _download(to_xacro(project.robot), f"{project.robot.name}.urdf.xacro", "application/xml")
    if fmt == "mjcf":
        return _download(to_mjcf(project.robot, project.world.objects), f"{project.robot.name}.mjcf.xml", "application/xml")
    if fmt == "world_sdf":
        return _download(world_sdf(project), f"{project.world.template or 'world'}.sdf", "application/xml")
    if fmt == "spice":
        net, _ = to_spice(project.circuit, REGISTRY, project.name)
        return _download(net, f"{base}.cir", "text/plain")
    if fmt == "kicad":
        return _download(to_kicad_netlist(project.circuit, REGISTRY, project.name), f"{base}.net", "text/plain")
    if fmt == "ros2":
        return _download(_zip(ros2_package(project)), f"{pkg_name(project)}.zip", "application/zip")
    if fmt == "firmware":
        return _download(_zip(generate_platformio_project(project)), f"{base}_firmware.zip", "application/zip")
    if fmt in ("stl", "obj"):
        cp = next((p for p in project.cad.parts if p.id == part), None)
        if not cp:
            raise HTTPException(404, "part not found")
        try:
            v, f = mesh_arrays(build_part(cp))
        except CadError as e:
            raise HTTPException(400, str(e)) from e
        return _download(to_stl_ascii(v, f, cp.id) if fmt == "stl" else to_obj(v, f, cp.id), f"{cp.id}.{fmt}", "model/stl")
    # package
    assets, runs = [], []
    if project.id:
        assets = [{"id": a.id, "filename": a.filename, "content": a.content}
                  for a in db.scalars(select(AssetRow).where(AssetRow.project_id == project.id))]
        runs = [{"id": r.id, "telemetry_csv": r.telemetry_csv, "metrics": r.metrics, "events": r.events}
                for r in db.scalars(select(SimRunRow).where(SimRunRow.project_id == project.id)).all()[-5:]]
    blob, manifest = export_package(project, REGISTRY, assets, runs)
    return Response(blob, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{base}.rvproj"',
        "X-RoboVerse-Export-Report": json.dumps(manifest["export_report"])[:4000]})


# ------------------------------------------------------------------- import --

@app.post("/api/import/package")
async def import_pkg(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        project, report, assets = import_package(await file.read())
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e)) from e
    row = ProjectRow(name=project.name, type=project.type.value, data=project.model_dump(mode="json"))
    db.add(row)
    db.flush()
    for a in assets:
        db.add(AssetRow(project_id=row.id, filename=a["filename"], kind="original", content=a["content"]))
    db.commit()
    return {"project_id": row.id, "report": report}


@app.post("/api/import/urdf")
async def import_urdf(file: UploadFile = File(...)):
    try:
        robot, report = from_urdf((await file.read()).decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid URDF: {e}") from e
    return {"robot": robot.model_dump(), "report": report}


@app.post("/api/import/mesh")
async def import_mesh(file: UploadFile = File(...), project_id: Optional[str] = Form(None), scale: float = Form(1.0),
                      db: Session = Depends(get_db)):
    data = await file.read()
    name = file.filename or "mesh"
    try:
        v, f = parse_obj(data.decode("utf-8", "replace")) if name.lower().endswith(".obj") else parse_stl(data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    v = v * scale
    check = mesh_check(v, f)
    asset_id = None
    if project_id and db.get(ProjectRow, project_id):
        row = AssetRow(project_id=project_id, filename=name, kind="mesh",
                       meta={"scale": scale, **check}, content=base64.b64encode(data).decode())
        db.add(row)
        db.commit()
        asset_id = row.id
    from .engines.mass import mesh_mass_properties  # noqa: PLC0415
    mp = mesh_mass_properties(v, f, 1000.0) if check["watertight"] else None
    return {"asset_id": asset_id, "kind": "imported_mesh", "editable": False,
            "note": "Imported meshes are triangle geometry only — not editable parametric solids. "
                    "Mass properties are only computed for watertight meshes.",
            "check": check, "mass_properties_at_1000kg_m3": mp,
            "mesh": {"positions": v.round(6).ravel().tolist(), "indices": f.ravel().tolist()} if len(f) < 200000 else None}


@app.get("/api/projects/{pid}/assets")
def list_assets(pid: str, db: Session = Depends(get_db)):
    return [{"id": a.id, "filename": a.filename, "kind": a.kind, "meta": a.meta}
            for a in db.scalars(select(AssetRow).where(AssetRow.project_id == pid))]


# ----------------------------------------------------------------- firmware --

@app.get("/api/firmware/targets")
def fw_targets():
    return target_list()


@app.post("/api/firmware/generate")
def fw_generate(project: Project):
    return generate_platformio_project(project)


@app.post("/api/firmware/build")
def fw_build(project: Project):
    return build_firmware(project)


# --------------------------------------------------------------- simulation --

def _persist(session: SimSession, result: dict) -> None:
    with SessionLocal() as db:
        row = db.get(SimRunRow, session.id)
        if row:
            row.status = result["status"]
            row.metrics = result["metrics"]
            row.events = result["events"][-2000:]
            row.telemetry_csv = session.coord.telemetry_csv()
            row.sim_time = session.coord.t
            db.commit()


class SimRequest(BaseModel):
    project: Project
    force: bool = False  # start even if validation reports errors


@app.post("/api/simulations")
def create_simulation(req: SimRequest, db: Session = Depends(get_db)):
    project = req.project
    validation = validate_project(project, REGISTRY, "pre_simulation")
    if not validation["summary"]["passed"] and not req.force:
        return JSONResponse(status_code=409, content={"detail": "validation failed", "validation": validation})
    run_id = new_id()
    pid = project.id if project.id and db.get(ProjectRow, project.id) else None
    if pid:
        db.add(SimRunRow(id=run_id, project_id=pid, status="created", config=project.simulation.model_dump(mode="json")))
        db.commit()
    try:
        s = SESSIONS.create(run_id, project, REGISTRY, on_finish=_persist if pid else None)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"run_id": run_id, "init": s.init_report, "validation": validation}


class Control(BaseModel):
    action: str
    value: Optional[Any] = None


@app.post("/api/simulations/{run_id}/control")
def control(run_id: str, c: Control):
    s = SESSIONS.get(run_id)
    if not s:
        raise HTTPException(404, "simulation session not found")
    a = c.action
    if a == "start":
        s.start()
    elif a == "pause":
        s.pause()
    elif a == "resume":
        s.resume()
    elif a == "stop":
        s.stop()
    elif a == "reset":
        s.reset()
    elif a == "speed":
        s.set_speed(float(c.value or 1.0))
    elif a == "estop":
        s.estop(bool(c.value))
    elif a == "teleop":
        v = c.value or {}
        s.teleop(v.get("v"), v.get("w")) if v else s.teleop(None, None)
    else:
        raise HTTPException(400, "unknown action")
    return {"run_id": run_id, "status": s.status, "t": s.coord.t}


@app.websocket("/ws/simulations/{run_id}")
async def sim_ws(ws: WebSocket, run_id: str):
    s = SESSIONS.get(run_id)
    await ws.accept()
    if not s:
        await ws.send_json({"type": "error", "message": "session not found"})
        await ws.close()
        return
    q = s.subscribe()
    await ws.send_json({"type": "hello", "status": s.status, "init": s.init_report})

    async def reader():
        while True:
            msg = await ws.receive_json()
            control(run_id, Control(**msg))

    rtask = asyncio.create_task(reader())
    try:
        while True:
            msg = await q.get()
            await ws.send_text(json.dumps(msg, default=float))
            if msg.get("type") == "finished":
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        rtask.cancel()
        s.unsubscribe(q)


@app.get("/api/simulations/{run_id}")
def sim_result(run_id: str, db: Session = Depends(get_db)):
    s = SESSIONS.get(run_id)
    if s:
        return {"run_id": run_id, "status": s.status, "t": s.coord.t, "init": s.init_report,
                **({"metrics": s.result["metrics"], "events": s.result["events"]} if s.result else {})}
    row = db.get(SimRunRow, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return {"run_id": row.id, "status": row.status, "t": row.sim_time, "metrics": row.metrics, "events": row.events,
            "config": row.config}


@app.get("/api/simulations/{run_id}/telemetry.csv")
def sim_csv(run_id: str, db: Session = Depends(get_db)):
    s = SESSIONS.get(run_id)
    csv_text = s.coord.telemetry_csv() if s else (db.get(SimRunRow, run_id).telemetry_csv if db.get(SimRunRow, run_id) else None)
    if csv_text is None:
        raise HTTPException(404, "run not found")
    return PlainTextResponse(csv_text, headers={"Content-Disposition": f'attachment; filename="telemetry_{run_id}.csv"'})


@app.get("/api/simulations/{run_id}/map")
def sim_map(run_id: str):
    s = SESSIONS.get(run_id)
    if not s:
        raise HTTPException(404, "session not found")
    m = s.coord.map_snapshot()
    if not m:
        raise HTTPException(404, "mapping subsystem not active")
    return m


@app.get("/api/projects/{pid}/simulations")
def sim_history(pid: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(SimRunRow).where(SimRunRow.project_id == pid).order_by(SimRunRow.created_at.desc())).all()
    return [{"run_id": r.id, "status": r.status, "metrics": r.metrics, "sim_time": r.sim_time,
             "created_at": r.created_at.isoformat(), "backend": r.config.get("physics_backend")} for r in rows]


@app.get("/api/simulations")
def all_sim_history(db: Session = Depends(get_db)):
    rows = db.scalars(select(SimRunRow).order_by(SimRunRow.created_at.desc()).limit(50)).all()
    names = {p.id: p.name for p in db.scalars(select(ProjectRow))}
    return [{"run_id": r.id, "project_id": r.project_id, "project": names.get(r.project_id), "status": r.status,
             "metrics": r.metrics, "created_at": r.created_at.isoformat()} for r in rows]


@app.post("/api/simulations/headless")
def headless(project: Project, duration: Optional[float] = None):
    """Synchronous run (CI / batch). Returns metrics, events and the telemetry CSV."""
    c = Coordinator(project, REGISTRY)
    try:
        c.initialize()
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    res = c.run(duration)
    return {**res, "telemetry_csv": c.telemetry_csv()}


# --------------------------------------------------------------------- AI --

@app.get("/api/ai/capabilities")
def ai_caps():
    return compute_capabilities()


@app.get("/api/simulations/{run_id}/anomalies")
def anomalies(run_id: str, signal: str = "bus_i", threshold: float = 4.0):
    s = SESSIONS.get(run_id)
    if not s:
        raise HTTPException(404, "session not found")
    rows = s.coord.rows
    series = [r.get(signal) or 0.0 for r in rows]
    idx = zscore_anomalies(series, threshold=threshold)
    return {"signal": signal, "anomalies": [{"t": rows[i]["t"], "value": series[i]} for i in idx],
            "method": "trailing-window z-score", "label": "AI-assisted estimate; verify against events and ground truth"}


# ----------------------------------------------------------------- frontend --

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
