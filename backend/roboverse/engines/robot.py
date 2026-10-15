"""Robot designer: generate kinematic structures from drive parameters, and
validate robot models (links, joints, frames, mass, drivetrain sizing)."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from ..library.registry import Registry
from ..schemas.issues import Issue, SpecRef
from ..schemas.project import (Actuator, Drivetrain, Geometry, Joint, JointLimits, Link, Pose, Robot, Sensor)
from .mass import MATERIALS, inertia_valid, primitive_inertia


def link_inertia(link: Link) -> list[float]:
    if link.inertia:
        return link.inertia
    if link.geometry and link.geometry.type != "mesh" and link.mass > 0:
        return primitive_inertia(link.geometry.type, link.geometry.size, link.mass)
    return [1e-6, 1e-6, 1e-6, 0, 0, 0]


def generate_mobile_robot(name: str, drive: Drivetrain, chassis: list[float], chassis_mass: float,
                          wheel_mass: float = 0.15, motor_ref: str = "motor.pololu_37d_50to1_12v",
                          lidar: bool = True, imu: bool = True) -> Robot:
    """Build links/joints/actuators for a wheeled base following REP-103 (x forward, y left, z up)."""
    L, W, H = chassis
    r, w = drive.wheel_radius, drive.wheel_width
    # base_link sits at axle height; the chassis box is raised to keep ~30% of the wheel radius as ground clearance.
    zc = max(0.0, H / 2 - 0.7 * r)
    links = [Link(name="base_footprint"),
             Link(name="base_link", geometry=Geometry(type="box", size=[L, W, H]), mass=chassis_mass,
                  origin=Pose(xyz=[0, 0, zc]), material="aluminium", color="#5b6b82")]
    joints = [Joint(name="base_footprint_joint", type="fixed", parent="base_footprint", child="base_link",
                    origin=Pose(xyz=[0, 0, r]))]
    actuators: list[Actuator] = []
    half = drive.wheel_separation / 2
    wheel_positions: list[tuple[str, float, float, str]] = []
    dt = drive.drive_type
    if dt in ("differential", "tracked"):
        wheel_positions = [("left_wheel", 0.0, half, "left_wheel"), ("right_wheel", 0.0, -half, "right_wheel")]
    elif dt in ("four_wheel", "mecanum", "ackermann"):
        dx = L * 0.35
        wheel_positions = [("front_left_wheel", dx, half, "left_wheel"), ("front_right_wheel", dx, -half, "right_wheel"),
                           ("rear_left_wheel", -dx, half, "left_wheel"), ("rear_right_wheel", -dx, -half, "right_wheel")]
    for wname, x, y, role in wheel_positions:
        parent = "base_link"
        if dt == "ackermann" and wname.startswith("front"):
            steer = wname.replace("wheel", "steer")
            links.append(Link(name=steer, geometry=Geometry(type="cylinder", size=[0.01, 0.01, 0.02]), mass=0.05))
            joints.append(Joint(name=f"{steer}_joint", type="revolute", parent="base_link", child=steer,
                                origin=Pose(xyz=[x, y, 0.0]), axis=[0, 0, 1],
                                limits=JointLimits(lower=-drive.max_steering_angle, upper=drive.max_steering_angle,
                                                   effort=5, velocity=2)))
            parent, x, y = steer, 0.0, 0.0
        links.append(Link(name=wname, geometry=Geometry(type="cylinder", size=[r, r, w]), mass=wheel_mass,
                          material="rubber", origin=Pose(rpy=[math.pi / 2, 0, 0]), color="#222831"))
        joints.append(Joint(name=f"{wname}_joint", type="continuous", parent=parent, child=wname,
                            origin=Pose(xyz=[x, y, 0.0]), axis=[0, 1, 0],
                            limits=JointLimits(effort=10, velocity=30)))
        if dt != "ackermann" or wname.startswith("rear"):
            actuators.append(Actuator(id=f"act_{wname}", twin_id=f"twin_{wname}_motor", joint=f"{wname}_joint",
                                      component_ref=motor_ref, role=role))
    # support caster for differential drives
    if dt in ("differential",):
        cr = min(0.025, r)
        cz = -r + cr  # base_link sits r above the floor
        links.append(Link(name="caster", geometry=Geometry(type="sphere", size=[cr, cr, cr]), mass=0.05,
                          material="nylon", color="#888888"))
        joints.append(Joint(name="caster_joint", type="fixed", parent="base_link", child="caster",
                            origin=Pose(xyz=[-L * 0.4, 0, cz])))
    sensors: list[Sensor] = []
    if lidar:
        links.append(Link(name="laser", geometry=Geometry(type="cylinder", size=[0.035, 0.035, 0.04]), mass=0.17,
                          material="abs", color="#111111"))
        joints.append(Joint(name="laser_joint", type="fixed", parent="base_link", child="laser",
                            origin=Pose(xyz=[L * 0.25, 0, zc + H / 2 + 0.02])))
        sensors.append(Sensor(id="lidar", twin_id="twin_lidar", type="lidar", link="laser", rate_hz=10, noise_std=0.01,
                              component_ref="sensor.rplidar_a1",
                              params={"beams": 180, "range_max": 12.0, "range_min": 0.15, "fov_deg": 360}))
    if imu:
        links.append(Link(name="imu_link", geometry=Geometry(type="box", size=[0.02, 0.016, 0.003]), mass=0.005))
        joints.append(Joint(name="imu_joint", type="fixed", parent="base_link", child="imu_link",
                            origin=Pose(xyz=[0, 0, zc])))
        sensors.append(Sensor(id="imu", twin_id="twin_imu", type="imu", link="imu_link", rate_hz=100,
                              noise_std=0.002, component_ref="sensor.mpu6050_gy521"))
    for a in actuators:
        sensors.append(Sensor(id=f"enc_{a.joint.replace('_joint', '')}", twin_id=a.twin_id, type="encoder",
                              link=a.joint.replace("_joint", ""), rate_hz=100, params={"cpr": 3200}))
    return Robot(name=name, links=links, joints=joints, drivetrain=drive, actuators=actuators, sensors=sensors)


def generate_arm(name: str, dof: int = 4, link_len: float = 0.15, base_mass: float = 1.0) -> Robot:
    links = [Link(name="base_link", geometry=Geometry(type="cylinder", size=[0.08, 0.08, 0.05]), mass=base_mass)]
    joints: list[Joint] = []
    actuators: list[Actuator] = []
    parent = "base_link"
    for i in range(dof):
        ln = f"link_{i + 1}"
        links.append(Link(name=ln, geometry=Geometry(type="box", size=[0.04, 0.04, link_len]), mass=0.2,
                          origin=Pose(xyz=[0, 0, link_len / 2])))
        axis = [0, 0, 1] if i == 0 else [0, 1, 0]
        joints.append(Joint(name=f"joint_{i + 1}", type="revolute", parent=parent, child=ln,
                            origin=Pose(xyz=[0, 0, 0.05 if i == 0 else link_len]), axis=axis,
                            limits=JointLimits(lower=-math.pi / 2, upper=math.pi / 2, effort=2.0, velocity=1.5)))
        actuators.append(Actuator(id=f"act_joint_{i + 1}", twin_id=f"twin_joint_{i + 1}", joint=f"joint_{i + 1}",
                                  component_ref="servo.sg90", role="arm"))
        parent = ln
    return Robot(name=name, links=links, joints=joints, drivetrain=Drivetrain(drive_type="arm"), actuators=actuators)


# ------------------------------------------------------------ validation --

def robot_mass(robot: Robot) -> float:
    return sum(l.mass for l in robot.links) + robot.drivetrain.payload_kg


def validate_robot(robot: Robot, registry: Registry) -> list[Issue]:
    issues: list[Issue] = []

    def add(code, sev, title, msg, refs=(), fix="", specs=(), connection=None):
        issues.append(Issue(code=code, severity=sev, domain="robot", title=title, message=msg, refs=list(refs),
                            fix=fix, specs=list(specs), connection=connection))

    names = [l.name for l in robot.links]
    link_set = set(names)
    for n in {n for n in names if names.count(n) > 1}:
        add("R001", "error", "Duplicate link name", f"Link '{n}' is defined more than once.", [n], "Rename one of the links.")
    jnames = [j.name for j in robot.joints]
    for n in {n for n in jnames if jnames.count(n) > 1}:
        add("R002", "error", "Duplicate joint name", f"Joint '{n}' is defined more than once.", [n], "Rename one of the joints.")
    if not robot.links:
        add("R000", "error", "Robot has no links", "A robot needs at least a base link.", fix="Generate a base from the designer.")
        return issues
    if robot.base_link not in link_set:
        add("R003", "error", "Missing base link", f"The configured base link '{robot.base_link}' does not exist.",
            fix="Create a link named base_link or change the base link setting.")
    children = defaultdict(list)
    parents_of = defaultdict(list)
    for j in robot.joints:
        conn = f"{j.parent} -> {j.child} via {j.name}"
        for end in (j.parent, j.child):
            if end not in link_set:
                add("R004", "error", "Joint references a missing link", f"Joint '{j.name}' references link '{end}', which does not exist.",
                    [j.name], "Create the link or fix the joint's parent/child.", connection=conn)
        if j.parent == j.child:
            add("R005", "error", "Joint connects a link to itself", f"'{j.name}' has parent == child.", [j.name], connection=conn)
        children[j.parent].append(j.child)
        parents_of[j.child].append(j.name)
        if j.type != "fixed":
            norm = math.sqrt(sum(a * a for a in j.axis))
            if norm < 1e-9:
                add("R006", "error", "Zero-length joint axis", f"'{j.name}' has axis {j.axis}.", [j.name],
                    "Set a unit axis, e.g. [0, 1, 0] for a wheel.", connection=conn)
            elif abs(norm - 1) > 1e-3:
                add("R007", "warning", "Joint axis not normalised", f"'{j.name}' axis length is {norm:.3f}; URDF consumers normalise inconsistently.",
                    [j.name], "Normalise the axis vector.", connection=conn)
        if j.type in ("revolute", "prismatic"):
            if not j.limits:
                add("R008", "error", "Missing joint limits", f"{j.type} joint '{j.name}' requires limits.", [j.name],
                    "Add lower/upper/effort/velocity limits.", connection=conn)
            elif j.limits.lower >= j.limits.upper:
                add("R009", "error", "Invalid joint limits", f"'{j.name}': lower ({j.limits.lower}) >= upper ({j.limits.upper}).",
                    [j.name], "Swap or correct the limits.", connection=conn)
        if j.limits and (j.limits.effort <= 0 or j.limits.velocity <= 0) and j.type != "fixed":
            add("R010", "warning", "Non-positive effort/velocity limit", f"'{j.name}' cannot move with effort={j.limits.effort}, velocity={j.limits.velocity}.",
                [j.name], connection=conn)
    for child, js in parents_of.items():
        if len(js) > 1:
            add("R011", "error", "Link has multiple parents (kinematic loop)",
                f"Link '{child}' is the child of {', '.join(js)}. URDF requires a tree; closed chains need SDF or constraints.",
                [child, *js], "Remove one joint or model the loop with a mate constraint.")
    roots = [n for n in link_set if not parents_of.get(n)]
    if len(roots) > 1:
        add("R012", "error", "Disconnected assembly", f"Multiple root links: {', '.join(sorted(roots))}. Every link except the root must be attached by a joint.",
            sorted(roots), "Attach the floating links to the robot with fixed or moving joints.")
    # reachability / cycles
    root = next((r for r in roots if r in ("base_footprint", robot.base_link)), roots[0] if roots else None)
    seen, stack = set(), [root] if root else []
    while stack:
        n = stack.pop()
        if n in seen:
            add("R013", "error", "Cycle in kinematic tree", f"Link '{n}' is reachable twice.", [n])
            continue
        seen.add(n)
        stack += children.get(n, [])
    for n in link_set - seen:
        if n not in roots:
            add("R014", "error", "Unreachable link", f"Link '{n}' is not connected to the root '{root}'.", [n])
    # geometry & mass
    total_mass = 0.0
    for l in robot.links:
        total_mass += l.mass
        if l.geometry and l.geometry.type == "mesh" and not l.geometry.mesh_ref:
            add("R020", "error", "Mesh geometry without file", f"Link '{l.name}' uses mesh geometry but no mesh asset is set.",
                [l.name], "Import an STL/OBJ or use a primitive.")
        if l.geometry and any(s <= 0 for s in (l.geometry.size if l.geometry.type == "box" else l.geometry.size[:1])):
            add("R021", "error", "Invalid geometry size", f"Link '{l.name}' has non-positive dimensions {l.geometry.size}.", [l.name])
        if l.geometry and l.mass <= 0:
            add("R022", "warning", "Massless link with geometry",
                f"Link '{l.name}' has geometry but zero mass; physics engines treat it as static or unstable.", [l.name],
                "Set a mass (use CAD mass properties).")
        if l.material not in MATERIALS:
            add("R023", "info", "Unknown material", f"Link '{l.name}' material '{l.material}' has no density; mass must be set manually.", [l.name])
        if l.mass > 0:
            err = inertia_valid(link_inertia(l))
            if err:
                add("R024", "error", "Invalid inertia tensor", f"Link '{l.name}': {err}.", [l.name], "Recompute inertia from geometry.")
        if l.geometry and l.geometry.type != "mesh" and l.geometry.size and max(l.geometry.size) > 5.0:
            add("R025", "warning", "Suspicious size — check units",
                f"Link '{l.name}' is {max(l.geometry.size)} m; RoboVerse uses SI metres. Was this entered in mm?",
                [l.name], "Convert dimensions to metres.")
    # sensors & actuators
    jset = {j.name: j for j in robot.joints}
    for s in robot.sensors:
        if s.link not in link_set:
            add("R030", "error", "Sensor attached to missing link", f"Sensor '{s.id}' references link '{s.link}'.", [s.id])
        if s.rate_hz <= 0:
            add("R031", "error", "Invalid sensor rate", f"Sensor '{s.id}' has rate {s.rate_hz} Hz.", [s.id])
        if s.component_ref and not registry.get(s.component_ref):
            add("R032", "warning", "Sensor component not in library", f"'{s.component_ref}' is unknown.", [s.id])
    for a in robot.actuators:
        j = jset.get(a.joint)
        if not j:
            add("R040", "error", "Actuator on missing joint", f"Actuator '{a.id}' drives joint '{a.joint}', which does not exist.", [a.id])
            continue
        if j.type == "fixed":
            add("R041", "error", "Actuator on fixed joint", f"Actuator '{a.id}' drives fixed joint '{a.joint}'.", [a.id, a.joint],
                "Change the joint to continuous/revolute.")
        if not registry.get(a.component_ref):
            add("R042", "error", "Actuator component not in library", f"'{a.component_ref}' is unknown.", [a.id])
    # frames (REP-103 conventions for wheeled bases)
    d = robot.drivetrain
    wheel_joints = [jset[a.joint] for a in robot.actuators if a.joint in jset and "wheel" in a.role]
    for j in wheel_joints:
        ax = j.axis
        if abs(ax[1]) < 0.9 * math.sqrt(sum(x * x for x in ax) or 1):
            add("R050", "warning", "Wheel axis not along Y (REP-103)",
                f"Wheel joint '{j.name}' axis is {ax}. With x forward / z up, wheel axles should be along y; otherwise the robot will drive sideways or spin.",
                [j.name], "Set the wheel joint axis to [0, 1, 0].")
    if d.drive_type in ("differential", "four_wheel", "mecanum", "tracked"):
        lefts = [j for j in wheel_joints if j.origin.xyz[1] > 0]
        rights = [j for j in wheel_joints if j.origin.xyz[1] < 0]
        if wheel_joints and (not lefts or not rights):
            add("R051", "error", "Wheels not on both sides", "A skid/differential base needs driven wheels on both sides of the x axis.",
                [j.name for j in wheel_joints])
        if lefts and rights:
            sep = abs(lefts[0].origin.xyz[1] - rights[0].origin.xyz[1])
            if abs(sep - d.wheel_separation) > 0.005:
                add("R052", "warning", "Wheel separation mismatch",
                    f"Drivetrain wheel_separation is {d.wheel_separation} m but joints are {sep:.3f} m apart; odometry will be biased.",
                    [lefts[0].name, rights[0].name], "Regenerate the base or update wheel_separation.")
    if d.drive_type not in ("arm",):
        if d.wheel_radius <= 0:
            add("R053", "error", "Invalid wheel radius", f"wheel_radius = {d.wheel_radius}.")
        # sizing: speed and torque
        mass = total_mass + d.payload_kg
        motors = [registry.get(a.component_ref) for a in robot.actuators if "wheel" in a.role]
        motors = [m for m in motors if m and m.rating("noload_rpm")]
        if motors and d.wheel_radius > 0:
            m = motors[0]
            rpm = m.rating("noload_rpm") / d.gear_ratio
            v_max = rpm * 2 * math.pi / 60 * d.wheel_radius
            if d.max_speed > 0.85 * v_max:
                add("R060", "warning", "Requested max speed near/above motor capability",
                    f"Motor no-load speed gives {v_max:.2f} m/s at the wheel; requested max_speed is {d.max_speed} m/s. "
                    "Under load, a DC motor reaches ~70-85% of no-load speed.",
                    [a.id for a in robot.actuators], "Lower max_speed, use a larger wheel or a faster motor.",
                    [SpecRef(component=m.id, field="noload_rpm", value=m.rating("noload_rpm"), unit="rpm",
                             source=m.ratings["noload_rpm"].source, url=m.datasheet)])
            t_stall = m.rating("stall_torque")
            if t_stall:
                n = len(motors)
                f_needed = mass * (d.max_accel + 9.81 * d.rolling_resistance)
                t_needed = f_needed * d.wheel_radius / max(n, 1) / d.gear_ratio
                ratio = t_needed / t_stall
                if ratio > 0.5:
                    add("R061", "error" if ratio > 1 else "warning", "Insufficient motor torque",
                        f"Accelerating {mass:.1f} kg at {d.max_accel} m/s^2 needs {t_needed:.2f} N*m per motor, "
                        f"{ratio:.0%} of stall torque ({t_stall} N*m). Continuous operation should stay below ~30-50% of stall.",
                        [a.id for a in robot.actuators], "Reduce acceleration/payload or use a higher-torque motor/gear ratio.",
                        [SpecRef(component=m.id, field="stall_torque", value=t_stall, unit="N*m",
                                 source=m.ratings["stall_torque"].source, url=m.datasheet)])
                mu = d.wheel_friction
                if d.max_accel > mu * 9.81 * 0.5 * (2 if d.drive_type != "differential" else 1):
                    add("R062", "warning", "Acceleration exceeds traction",
                        f"max_accel {d.max_accel} m/s^2 exceeds what friction ({mu}) can transmit; wheels will slip.",
                        fix="Lower max_accel.")
        # tipping: COM height vs support base under max deceleration
        base = next((l for l in robot.links if l.name == robot.base_link), None)
        if base and base.geometry and base.geometry.type == "box":
            h_com = d.wheel_radius + base.origin.xyz[2]  # COM approximated at chassis centre
            half_track = d.wheel_separation / 2
            half_len = base.geometry.size[0] / 2
            a_tip = 9.81 * min(half_len, half_track) / max(h_com, 1e-3)
            if d.max_decel > a_tip:
                add("R063", "warning", "Tipping risk under braking",
                    f"Estimated tipping deceleration is {a_tip:.1f} m/s^2 but max_decel is {d.max_decel} m/s^2 (COM estimated from geometry).",
                    fix="Lower the payload/COM, widen the base or reduce max_decel.")
    return issues
