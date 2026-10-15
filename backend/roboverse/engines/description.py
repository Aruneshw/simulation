"""Robot description interchange: URDF / Xacro / SDF export, MJCF for MuJoCo,
and URDF import that preserves elements it cannot interpret."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Optional

from ..schemas.project import Geometry, Joint, JointLimits, Link, Pose, Robot
from .robot import link_inertia


def _f(v: float) -> str:
    return f"{v:.6g}"


def _v(vals) -> str:
    return " ".join(_f(x) for x in vals)


def _geom_xml(g: Geometry, mesh_uri: Optional[str] = None) -> ET.Element:
    geo = ET.Element("geometry")
    if g.type == "box":
        ET.SubElement(geo, "box", size=_v(g.size))
    elif g.type == "cylinder":
        ET.SubElement(geo, "cylinder", radius=_f(g.size[0]), length=_f(g.size[2]))
    elif g.type == "sphere":
        ET.SubElement(geo, "sphere", radius=_f(g.size[0]))
    else:
        ET.SubElement(geo, "mesh", filename=mesh_uri or f"package://robot_description/meshes/{g.mesh_ref}.stl")
    return geo


def _pretty(el: ET.Element) -> str:
    ET.indent(el, space="  ")
    return '<?xml version="1.0"?>\n' + ET.tostring(el, encoding="unicode") + "\n"


def to_urdf_element(robot: Robot, xacro: bool = False) -> ET.Element:
    attrs = {"name": robot.name}
    if xacro:
        attrs["xmlns:xacro"] = "http://www.ros.org/wiki/xacro"
    root = ET.Element("robot", attrs)
    if xacro:
        d = robot.drivetrain
        for k, v in (("wheel_radius", d.wheel_radius), ("wheel_separation", d.wheel_separation), ("wheel_width", d.wheel_width)):
            ET.SubElement(root, "xacro:property", name=k, value=_f(v))
    colors = {}
    for l in robot.links:
        if l.color not in colors:
            colors[l.color] = f"mat_{len(colors)}"
            m = ET.SubElement(root, "material", name=colors[l.color])
            c = l.color.lstrip("#")
            rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)] if len(c) == 6 else [0.5, 0.5, 0.5]
            ET.SubElement(m, "color", rgba=_v([*rgb, 1.0]))
    for l in robot.links:
        le = ET.SubElement(root, "link", name=l.name)
        if l.geometry:
            for tag in ("visual", "collision"):
                e = ET.SubElement(le, tag)
                ET.SubElement(e, "origin", xyz=_v(l.origin.xyz), rpy=_v(l.origin.rpy))
                e.append(_geom_xml(l.geometry))
                if tag == "visual":
                    ET.SubElement(e, "material", name=colors[l.color])
        if l.mass > 0:
            ine = ET.SubElement(le, "inertial")
            ET.SubElement(ine, "origin", xyz=_v(l.origin.xyz), rpy=_v(l.origin.rpy))
            ET.SubElement(ine, "mass", value=_f(l.mass))
            i = link_inertia(l)
            ET.SubElement(ine, "inertia", ixx=_f(i[0]), iyy=_f(i[1]), izz=_f(i[2]), ixy=_f(i[3]), ixz=_f(i[4]), iyz=_f(i[5]))
    for j in robot.joints:
        je = ET.SubElement(root, "joint", name=j.name, type=j.type)
        ET.SubElement(je, "parent", link=j.parent)
        ET.SubElement(je, "child", link=j.child)
        xyz = j.origin.xyz
        if xacro and "wheel" in j.child and j.type == "continuous" and abs(xyz[1]) > 0:
            sign = "" if xyz[1] > 0 else "-"
            ET.SubElement(je, "origin", xyz=f"{_f(xyz[0])} {sign}${{wheel_separation/2}} {_f(xyz[2])}", rpy=_v(j.origin.rpy))
        else:
            ET.SubElement(je, "origin", xyz=_v(xyz), rpy=_v(j.origin.rpy))
        if j.type != "fixed":
            ET.SubElement(je, "axis", xyz=_v(j.axis))
        if j.limits and j.type in ("revolute", "prismatic", "continuous"):
            lim = {"effort": _f(j.limits.effort), "velocity": _f(j.limits.velocity)}
            if j.type != "continuous":
                lim.update(lower=_f(j.limits.lower), upper=_f(j.limits.upper))
            ET.SubElement(je, "limit", lim)
    # ros2_control interfaces for actuated joints
    if robot.actuators:
        rc = ET.SubElement(root, "ros2_control", name="RoboVerseSystem", type="system")
        hw = ET.SubElement(rc, "hardware")
        ET.SubElement(hw, "plugin").text = "mock_components/GenericSystem"
        for a in robot.actuators:
            je = ET.SubElement(rc, "joint", name=a.joint)
            ET.SubElement(je, "command_interface", name="velocity" if "wheel" in a.role else "position")
            ET.SubElement(je, "state_interface", name="position")
            ET.SubElement(je, "state_interface", name="velocity")
    return root


def to_urdf(robot: Robot, preserved: Optional[list[dict]] = None) -> str:
    """URDF export. Elements preserved from an import (transmissions, gazebo tags...) are re-emitted verbatim."""
    root = to_urdf_element(robot)
    for p in preserved or []:
        try:
            root.append(ET.fromstring(p["xml"]))
        except (ET.ParseError, KeyError):
            continue
    return _pretty(root)


def to_xacro(robot: Robot) -> str:
    return _pretty(to_urdf_element(robot, xacro=True))


def _rpy_to_quat(r, p, y):
    cr, sr = math.cos(r / 2), math.sin(r / 2)
    cp, sp = math.cos(p / 2), math.sin(p / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]


def _compose(parent_xyz, parent_rpy, xyz, rpy):
    """Pose composition (parent * child) using rotation matrices; returns xyz, rpy."""
    import numpy as np

    def rot(r, p, y):
        cx, sx, cy_, sy_, cz, sz = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
        return np.array([[cz * cy_, cz * sy_ * sx - sz * cx, cz * sy_ * cx + sz * sx],
                         [sz * cy_, sz * sy_ * sx + cz * cx, sz * sy_ * cx - cz * sx],
                         [-sy_, cy_ * sx, cy_ * cx]])
    R1 = rot(*parent_rpy)
    R = R1 @ rot(*rpy)
    t = np.array(parent_xyz) + R1 @ np.array(xyz)
    pitch = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    roll = math.atan2(R[2, 1], R[2, 2])
    yaw = math.atan2(R[1, 0], R[0, 0])
    return t.tolist(), [roll, pitch, yaw]


def link_world_poses(robot: Robot) -> dict[str, tuple[list[float], list[float]]]:
    """Pose of every link frame in the model (root) frame."""
    poses = {}
    children = {}
    for j in robot.joints:
        children.setdefault(j.parent, []).append(j)
    child_set = {j.child for j in robot.joints}
    roots = [l.name for l in robot.links if l.name not in child_set]
    stack = [(r, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) for r in roots]
    while stack:
        name, xyz, rpy = stack.pop()
        if name in poses:
            continue
        poses[name] = (xyz, rpy)
        for j in children.get(name, []):
            cx, cr = _compose(xyz, rpy, j.origin.xyz, j.origin.rpy)
            stack.append((j.child, cx, cr))
    return poses


def to_sdf(robot: Robot, version: str = "1.9") -> str:
    sdf = ET.Element("sdf", version=version)
    model = ET.SubElement(sdf, "model", name=robot.name)
    poses = link_world_poses(robot)
    for l in robot.links:
        le = ET.SubElement(model, "link", name=l.name)
        xyz, rpy = poses.get(l.name, ([0, 0, 0], [0, 0, 0]))
        ET.SubElement(le, "pose").text = _v([*xyz, *rpy])
        if l.mass > 0:
            ine = ET.SubElement(le, "inertial")
            ET.SubElement(ine, "pose").text = _v([*l.origin.xyz, *l.origin.rpy])
            ET.SubElement(ine, "mass").text = _f(l.mass)
            i = link_inertia(l)
            it = ET.SubElement(ine, "inertia")
            for k, v in zip(("ixx", "iyy", "izz", "ixy", "ixz", "iyz"), i):
                ET.SubElement(it, k).text = _f(v)
        if l.geometry:
            for tag in ("visual", "collision"):
                e = ET.SubElement(le, tag, name=f"{l.name}_{tag}")
                ET.SubElement(e, "pose").text = _v([*l.origin.xyz, *l.origin.rpy])
                geo = ET.SubElement(e, "geometry")
                g = l.geometry
                if g.type == "box":
                    ET.SubElement(ET.SubElement(geo, "box"), "size").text = _v(g.size)
                elif g.type == "cylinder":
                    c = ET.SubElement(geo, "cylinder")
                    ET.SubElement(c, "radius").text = _f(g.size[0])
                    ET.SubElement(c, "length").text = _f(g.size[2])
                elif g.type == "sphere":
                    ET.SubElement(ET.SubElement(geo, "sphere"), "radius").text = _f(g.size[0])
                else:
                    ET.SubElement(ET.SubElement(geo, "mesh"), "uri").text = f"meshes/{g.mesh_ref}.stl"
                if tag == "collision" and "wheel" in l.name:
                    fr = ET.SubElement(ET.SubElement(ET.SubElement(e, "surface"), "friction"), "ode")
                    ET.SubElement(fr, "mu").text = _f(robot.drivetrain.wheel_friction)
                    ET.SubElement(fr, "mu2").text = _f(robot.drivetrain.wheel_friction)
                if tag == "collision" and l.name == "caster":
                    fr = ET.SubElement(ET.SubElement(ET.SubElement(e, "surface"), "friction"), "ode")
                    ET.SubElement(fr, "mu").text = "0.01"
                    ET.SubElement(fr, "mu2").text = "0.01"
    for j in robot.joints:
        je = ET.SubElement(model, "joint", name=j.name, type="revolute" if j.type == "continuous" else j.type)
        ET.SubElement(je, "parent").text = j.parent
        ET.SubElement(je, "child").text = j.child
        if j.type != "fixed":
            ax = ET.SubElement(je, "axis")
            ET.SubElement(ax, "xyz", expressed_in=j.parent).text = _v(j.axis)
            lim = ET.SubElement(ax, "limit")
            if j.type == "continuous":
                ET.SubElement(lim, "lower").text = "-1e16"
                ET.SubElement(lim, "upper").text = "1e16"
            elif j.limits:
                ET.SubElement(lim, "lower").text = _f(j.limits.lower)
                ET.SubElement(lim, "upper").text = _f(j.limits.upper)
            if j.limits:
                ET.SubElement(lim, "effort").text = _f(j.limits.effort)
                ET.SubElement(lim, "velocity").text = _f(j.limits.velocity)
    for s in robot.sensors:
        if s.type not in ("lidar", "imu", "camera", "depth"):
            continue
        link = next((le for le in model.findall("link") if le.get("name") == s.link), None)
        if link is None:
            continue
        stype = {"lidar": "gpu_lidar", "imu": "imu", "camera": "camera", "depth": "depth_camera"}[s.type]
        se = ET.SubElement(link, "sensor", name=s.id, type=stype)
        ET.SubElement(se, "update_rate").text = _f(s.rate_hz)
        ET.SubElement(se, "always_on").text = "1"
        if s.type == "lidar":
            lid = ET.SubElement(se, "lidar")
            hz = ET.SubElement(ET.SubElement(ET.SubElement(lid, "scan"), "horizontal"), "samples")
            hz.text = str(int(s.params.get("beams", 360)))
            rng = ET.SubElement(lid, "range")
            ET.SubElement(rng, "min").text = _f(s.params.get("range_min", 0.15))
            ET.SubElement(rng, "max").text = _f(s.params.get("range_max", 12.0))
    if robot.drivetrain.drive_type == "differential":
        lw = next((a.joint for a in robot.actuators if a.role == "left_wheel"), None)
        rw = next((a.joint for a in robot.actuators if a.role == "right_wheel"), None)
        if lw and rw:
            pl = ET.SubElement(model, "plugin", filename="gz-sim-diff-drive-system", name="gz::sim::systems::DiffDrive")
            for k, v in (("left_joint", lw), ("right_joint", rw), ("wheel_separation", _f(robot.drivetrain.wheel_separation)),
                         ("wheel_radius", _f(robot.drivetrain.wheel_radius)), ("topic", "cmd_vel"), ("odom_topic", "odom")):
                ET.SubElement(pl, k).text = v
    return _pretty(sdf)


# ----------------------------------------------------------------- MJCF --

def to_mjcf(robot: Robot, world_objects: list | None = None, timestep: float = 0.005) -> str:
    """MuJoCo model for wheeled robots: free-floating chassis, hinge wheels driven by torque motors."""
    mj = ET.Element("mujoco", model=robot.name)
    ET.SubElement(mj, "compiler", angle="radian", autolimits="true")
    ET.SubElement(mj, "option", timestep=_f(timestep), integrator="implicitfast")
    default = ET.SubElement(mj, "default")
    ET.SubElement(default, "geom", condim="3", friction="0.8 0.005 0.0001")
    world = ET.SubElement(mj, "worldbody")
    ET.SubElement(world, "geom", name="floor", type="plane", size="50 50 0.1", rgba="0.85 0.86 0.88 1")
    for o in world_objects or []:
        if not o.collision.enabled or o.shape not in ("box", "cylinder") or o.kind in ("floor", "robot_start", "goal", "loading_zone", "charging_station"):
            continue
        x, y, z = o.pose.xyz
        if o.shape == "box":
            ET.SubElement(world, "geom", name=f"obj_{o.id}", type="box", pos=_v([x, y, z + o.size[2] / 2]),
                          euler=_v(o.pose.rpy), size=_v([s / 2 for s in o.size]), rgba="0.6 0.6 0.65 1")
        else:
            ET.SubElement(world, "geom", name=f"obj_{o.id}", type="cylinder", pos=_v([x, y, z + o.size[2] / 2]),
                          size=_v([o.size[0], o.size[2] / 2]), rgba="0.6 0.6 0.65 1")
    poses = link_world_poses(robot)
    by_parent = {}
    for j in robot.joints:
        by_parent.setdefault(j.parent, []).append(j)
    links = {l.name: l for l in robot.links}

    def geom_for(body: ET.Element, l: Link):
        if not l.geometry or l.geometry.type == "mesh":
            if l.mass > 0:
                ET.SubElement(body, "inertial", pos="0 0 0", mass=_f(l.mass), diaginertia=_v(link_inertia(l)[:3]))
            return
        g = l.geometry
        attrs = {"name": f"g_{l.name}", "pos": _v(l.origin.xyz), "euler": _v(l.origin.rpy), "mass": _f(max(l.mass, 1e-4))}
        if g.type == "box":
            attrs.update(type="box", size=_v([s / 2 for s in g.size]))
        elif g.type == "cylinder":
            attrs.update(type="cylinder", size=_v([g.size[0], g.size[2] / 2]))
        else:
            attrs.update(type="sphere", size=_f(g.size[0]))
        if "wheel" in l.name:
            attrs["friction"] = f"{robot.drivetrain.wheel_friction} 0.005 0.0001"
        if l.name == "caster":
            attrs["friction"] = "0.0 0.0 0.0"
        c = l.color.lstrip("#")
        if len(c) == 6:
            attrs["rgba"] = _v([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1])
        ET.SubElement(body, "geom", attrs)

    def build(parent_el: ET.Element, link_name: str, xyz, rpy, joint: Optional[Joint]):
        body = ET.SubElement(parent_el, "body", name=link_name, pos=_v(xyz), euler=_v(rpy))
        if joint is None:
            ET.SubElement(body, "freejoint", name="root")
        elif joint.type in ("continuous", "revolute"):
            attrs = {"name": joint.name, "type": "hinge", "axis": _v(joint.axis), "damping": "0.001"}
            if joint.type == "revolute" and joint.limits:
                attrs["range"] = f"{_f(joint.limits.lower)} {_f(joint.limits.upper)}"
            ET.SubElement(body, "joint", attrs)
        elif joint.type == "prismatic":
            ET.SubElement(body, "joint", name=joint.name, type="slide", axis=_v(joint.axis))
        geom_for(body, links[link_name])
        for cj in by_parent.get(link_name, []):
            if cj.child in links:
                build(body, cj.child, cj.origin.xyz, cj.origin.rpy, cj)

    child_set = {j.child for j in robot.joints}
    roots = [l.name for l in robot.links if l.name not in child_set]
    root = roots[0] if roots else robot.base_link
    # base_footprint is massless; start the floating body at the footprint with a tiny lift
    build(world, root, [0, 0, 0.002], [0, 0, 0], None)
    act = ET.SubElement(mj, "actuator")
    for a in robot.actuators:
        ET.SubElement(act, "motor", name=f"m_{a.joint}", joint=a.joint, gear="1", ctrllimited="false")
    sensor = ET.SubElement(mj, "sensor")
    for a in robot.actuators:
        ET.SubElement(sensor, "jointvel", name=f"v_{a.joint}", joint=a.joint)
        ET.SubElement(sensor, "jointpos", name=f"p_{a.joint}", joint=a.joint)
    _ = poses
    return ET.tostring(mj, encoding="unicode")


# ------------------------------------------------------------ URDF import --

SUPPORTED_ROBOT_TAGS = {"link", "joint", "material"}


def from_urdf(text: str) -> tuple[Robot, dict]:
    """Parse URDF into the project model. Returns (robot, report) where report lists every
    element that was preserved verbatim because RoboVerse does not model it."""
    root = ET.fromstring(text)
    report = {"preserved": [], "warnings": []}
    materials = {}
    for m in root.findall("material"):
        c = m.find("color")
        if c is not None:
            rgba = [float(x) for x in c.get("rgba", "0.5 0.5 0.5 1").split()]
            materials[m.get("name")] = "#" + "".join(f"{int(max(0, min(1, x)) * 255):02x}" for x in rgba[:3])

    def pose(el) -> Pose:
        if el is None:
            return Pose()
        return Pose(xyz=[float(x) for x in el.get("xyz", "0 0 0").split()],
                    rpy=[float(x) for x in el.get("rpy", "0 0 0").split()])

    links = []
    for le in root.findall("link"):
        l = Link(name=le.get("name"))
        vis = le.find("visual")
        if vis is None:
            vis = le.find("collision")
        if vis is not None:
            l.origin = pose(vis.find("origin"))
            geo = vis.find("geometry")
            if geo is not None and len(geo):
                g = geo[0]
                if g.tag == "box":
                    l.geometry = Geometry(type="box", size=[float(x) for x in g.get("size").split()])
                elif g.tag == "cylinder":
                    r = float(g.get("radius"))
                    l.geometry = Geometry(type="cylinder", size=[r, r, float(g.get("length"))])
                elif g.tag == "sphere":
                    r = float(g.get("radius"))
                    l.geometry = Geometry(type="sphere", size=[r, r, r])
                elif g.tag == "mesh":
                    l.geometry = Geometry(type="mesh", mesh_ref=g.get("filename"))
                    report["warnings"].append(f"link {l.name}: mesh '{g.get('filename')}' must be imported separately")
            mat = vis.find("material")
            if mat is not None:
                c = mat.find("color")
                if c is not None:
                    rgba = [float(x) for x in c.get("rgba").split()]
                    l.color = "#" + "".join(f"{int(max(0, min(1, x)) * 255):02x}" for x in rgba[:3])
                elif mat.get("name") in materials:
                    l.color = materials[mat.get("name")]
        ine = le.find("inertial")
        if ine is not None:
            m = ine.find("mass")
            l.mass = float(m.get("value")) if m is not None else 0.0
            i = ine.find("inertia")
            if i is not None:
                l.inertia = [float(i.get(k, 0)) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")]
        links.append(l)
    joints = []
    for je in root.findall("joint"):
        jt = je.get("type")
        if jt not in ("fixed", "continuous", "revolute", "prismatic"):
            report["preserved"].append({"element": "joint", "name": je.get("name"),
                                        "reason": f"joint type '{jt}' not supported", "xml": ET.tostring(je, encoding="unicode")})
            continue
        ax = je.find("axis")
        lim = je.find("limit")
        joints.append(Joint(name=je.get("name"), type=jt, parent=je.find("parent").get("link"), child=je.find("child").get("link"),
                            origin=pose(je.find("origin")),
                            axis=[float(x) for x in ax.get("xyz").split()] if ax is not None else [1, 0, 0],
                            limits=JointLimits(lower=float(lim.get("lower", 0)), upper=float(lim.get("upper", 0)),
                                               effort=float(lim.get("effort", 0)), velocity=float(lim.get("velocity", 0)))
                            if lim is not None else None))
    for child in root:
        if child.tag not in SUPPORTED_ROBOT_TAGS:
            report["preserved"].append({"element": child.tag, "name": child.get("name"),
                                        "reason": "not modelled by RoboVerse; kept verbatim and re-emitted on export",
                                        "xml": ET.tostring(child, encoding="unicode")})
    child_set = {j.child for j in joints}
    roots = [l.name for l in links if l.name not in child_set]
    base = "base_link" if any(l.name == "base_link" for l in links) else (roots[0] if roots else "base_link")
    return Robot(name=root.get("name", "imported_robot"), base_link=base, links=links, joints=joints), report
