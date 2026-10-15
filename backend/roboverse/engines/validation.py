"""Unified design validation — runs before simulation and before export."""
from __future__ import annotations

import math

from ..library.registry import Registry
from ..schemas.issues import Issue, sort_issues, summarize
from ..schemas.project import Project
from .circuit.compat import CompatibilityEngine
from .firmware.targets import TARGETS
from .physics.backends import mujoco_available, robot_footprint
from .robot import validate_robot
from .twin import resolve_twin
from .world.geometry import circle_penetration, obstacles_from_world


def validate_world(project: Project) -> list[Issue]:
    issues: list[Issue] = []

    def add(code, sev, title, msg, refs=(), fix=""):
        issues.append(Issue(code=code, severity=sev, domain="world", title=title, message=msg, refs=list(refs), fix=fix))

    w = project.world
    ids = [o.id for o in w.objects]
    for d in {i for i in ids if ids.count(i) > 1}:
        add("W001", "error", "Duplicate object id", f"Object id '{d}' is used more than once.", [d])
    x0, y0, x1, y1 = w.bounds
    if x1 <= x0 or y1 <= y0:
        add("W002", "error", "Invalid world bounds", f"bounds = {w.bounds}")
    for o in w.objects:
        if any(s <= 0 for s in o.size) and o.shape not in ("plane", "marker"):
            add("W003", "error", "Non-positive object size", f"'{o.name}' has size {o.size}.", [o.id])
        if not (x0 <= o.pose.xyz[0] <= x1 and y0 <= o.pose.xyz[1] <= y1):
            add("W004", "warning", "Object outside world bounds", f"'{o.name}' at {o.pose.xyz[:2]} is outside the planning area.", [o.id],
                "Move it inside or enlarge the bounds.")
        if o.shape == "mesh" and not o.mesh_ref:
            add("W005", "error", "Mesh object without mesh", f"'{o.name}' has no mesh asset.", [o.id])
        if o.motion and len(o.motion.waypoints) < 2:
            add("W006", "warning", "Dynamic obstacle without path", f"'{o.name}' needs at least two patrol waypoints.", [o.id])
    starts = [o for o in w.objects if o.kind == "robot_start"]
    if project.robot.links and project.type.value in ("amr", "agv", "custom"):
        if not starts:
            add("W010", "warning", "No robot start position", "The robot will start at the origin.", fix="Add a 'Robot start' marker.")
        else:
            obs = obstacles_from_world(w)
            _, _, rad = robot_footprint(project.robot)
            s = starts[0]
            for ob in obs:
                if circle_penetration(ob, s.pose.xyz[0], s.pose.xyz[1], rad)[0] > 0:
                    add("W011", "error", "Robot starts inside an obstacle",
                        f"Start pose overlaps '{ob.id}' (robot footprint radius {rad:.2f} m).", [s.id, ob.id],
                        "Move the start marker to free space.")
    return issues


def validate_simulation(project: Project) -> list[Issue]:
    issues: list[Issue] = []

    def add(code, sev, title, msg, refs=(), fix=""):
        issues.append(Issue(code=code, severity=sev, domain="simulation", title=title, message=msg, refs=list(refs), fix=fix))

    cfg = project.simulation
    if cfg.dt <= 0 or cfg.dt > 0.02:
        add("S001", "error" if cfg.dt <= 0 else "warning", "Timestep out of range",
            f"dt = {cfg.dt} s. Motor/drive dynamics need dt <= 10 ms for a stable explicit coupling.", fix="Use 1-5 ms.")
    fw_rate = project.firmware.controller.loop_hz
    if fw_rate * cfg.dt > 1.0 + 1e-9:
        add("S002", "warning", "Controller faster than physics step",
            f"Controller loop {fw_rate} Hz cannot run faster than the macro step ({1 / cfg.dt:.0f} Hz); it will be limited.")
    if abs((1.0 / fw_rate) / cfg.dt - round((1.0 / fw_rate) / cfg.dt)) > 1e-6:
        add("S003", "info", "Controller period not a multiple of dt",
            "The controller will be scheduled at the nearest macro-step boundary (jitter up to dt).")
    if cfg.physics_backend == "mujoco" and not mujoco_available():
        add("S004", "error", "MuJoCo not installed", "The selected physics backend is unavailable.", fix="pip install mujoco, or use builtin_planar.")
    if cfg.physics_backend == "builtin_planar" and project.robot.drivetrain.drive_type not in ("differential", "four_wheel", "tracked"):
        add("S005", "error", "Drive type unsupported by built-in dynamics",
            f"'{project.robot.drivetrain.drive_type}' is not modelled by the planar engine.", fix="Use the MuJoCo backend.")
    sc = cfg.scenario
    w = project.world
    x0, y0, x1, y1 = w.bounds
    pts = list(sc.waypoints) + ([sc.goal] if sc.goal else [])
    obs = obstacles_from_world(w)
    _, _, rad = robot_footprint(project.robot) if project.robot.links else (0, 0, 0.3)
    for p in pts:
        if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
            add("S010", "error", "Goal outside world", f"Goal {p} is outside the world bounds.")
        for ob in obs:
            if not ob.dynamic and circle_penetration(ob, p[0], p[1], rad)[0] > 0:
                add("S011", "error", "Goal inside an obstacle", f"Goal {p} overlaps '{ob.id}'; the robot cannot reach it.", [ob.id],
                    "Move the waypoint to free space.")
    if sc.mode in ("waypoints", "goal") and not pts and not sc.return_to_dock:
        add("S012", "warning", "Scenario has no goals", "Add waypoints or a goal, or use teleop mode.")
    if sc.return_to_dock and not any(o.kind == "charging_station" for o in w.objects):
        add("S013", "error", "No charging station", "return_to_dock is enabled but the world has no charging station.")
    if cfg.duration <= 0:
        add("S014", "error", "Duration must be positive", f"duration = {cfg.duration}")
    _ = math
    return issues


def validate_firmware(project: Project, registry: Registry) -> list[Issue]:
    issues: list[Issue] = []
    fw = project.firmware
    t = TARGETS.get(fw.target)
    if not t:
        issues.append(Issue(code="F001", severity="error", domain="firmware", title="Unknown firmware target",
                            message=f"Target '{fw.target}' is not registered.", fix="Choose a supported target."))
        return issues
    if fw.mode not in t.modes:
        issues.append(Issue(code="F002", severity="error", domain="firmware", title="Execution mode not validated for target",
                            message=f"Target {t.name} supports {', '.join(t.modes)}; '{fw.mode}' is not a validated execution "
                                    "environment for it. A successful build does not prove the firmware runs correctly.",
                            fix=f"Use one of: {', '.join(t.modes)}."))
    ctrl = project.robot.controller_ref
    if ctrl:
        inst = next((i for i in project.circuit.instances if i.id == ctrl), None)
        comp = registry.get(inst.component_id) if inst else None
        if comp and comp.params.get("firmware_target") and comp.params["firmware_target"] != fw.target and \
                not (fw.target == "esp32" and comp.params["firmware_target"] == "esp32"):
            issues.append(Issue(code="F003", severity="warning", domain="firmware", title="Firmware target differs from controller board",
                                message=f"Controller {ctrl} is a {comp.name} ({comp.params['firmware_target']}) but firmware targets '{fw.target}'.",
                                refs=[ctrl], fix="Select the matching firmware target."))
        if comp:
            pins = {p.id: p for p in comp.pins}
            used: dict[str, str] = {}
            for a in fw.pin_map:
                p = pins.get(a.pin)
                if not p:
                    continue
                if a.pin in used:
                    issues.append(Issue(code="F004", severity="error", domain="firmware", title="Pin assigned twice",
                                        message=f"{a.pin} is used by '{used[a.pin]}' and '{a.channel}'.", refs=[ctrl]))
                used[a.pin] = a.channel
                need = {"pwm": "pwm", "adc": "adc", "uart_tx": "uart_tx", "uart_rx": "uart_rx", "i2c_sda": "i2c", "i2c_scl": "i2c",
                        "can_tx": "can", "can_rx": "can"}.get(a.function)
                if need and p.capabilities and need not in p.capabilities:
                    issues.append(Issue(code="F005", severity="error" if need in ("adc",) else "warning", domain="firmware",
                                        title="Pin lacks the configured function",
                                        message=f"Channel '{a.channel}' uses {a.pin} as {a.function}, but the pin supports "
                                                f"{', '.join(p.capabilities)}.", refs=[ctrl],
                                        fix=f"Move '{a.channel}' to a pin with {need}."))
    if fw.controller.loop_hz > t.max_loop_hz:
        issues.append(Issue(code="F006", severity="warning", domain="firmware", title="Control loop rate optimistic",
                            message=f"{fw.controller.loop_hz} Hz exceeds the {t.max_loop_hz} Hz this platform template is validated for."))
    return issues


def validate_project(project: Project, registry: Registry, stage: str = "pre_simulation") -> dict:
    issues: list[Issue] = []
    if project.robot.links:
        issues += validate_robot(project.robot, registry)
    eng = CompatibilityEngine(project.circuit, registry, project.firmware, project.robot.controller_ref)
    issues += eng.run()
    issues += validate_world(project)
    issues += validate_firmware(project, registry)
    if project.robot.actuators:
        _, twin_issues, _ = resolve_twin(project, registry)
        issues += twin_issues
    if stage == "pre_simulation":
        issues += validate_simulation(project)
    if stage == "pre_export":
        for part in project.cad.parts:
            if part.kind == "imported_mesh" and not part.mesh_ref:
                issues.append(Issue(code="X001", severity="error", domain="export", title="Imported part without mesh",
                                    message=f"Part '{part.name}' is marked imported_mesh but has no mesh asset.", refs=[part.id]))
        for inst in project.circuit.instances:
            comp = registry.get(inst.component_id)
            if comp and not comp.footprint and comp.category.value not in ("batteries", "motors_actuators", "dev_boards", "sbc",
                                                                         "sensors", "mechanical", "wheels_gearboxes"):
                issues.append(Issue(code="X002", severity="info", domain="export", title="No PCB footprint",
                                    message=f"{inst.id} ({comp.name}) has no KiCad footprint; PCB import will need manual assignment.",
                                    refs=[inst.id]))
    issues = sort_issues(issues)
    return {"stage": stage, "summary": summarize(issues), "issues": [i.model_dump() for i in issues],
            "power_budget": eng.power_budget()}
