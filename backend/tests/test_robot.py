import xml.etree.ElementTree as ET

import pytest

from roboverse.engines.description import from_urdf, to_mjcf, to_sdf, to_urdf, to_xacro
from roboverse.engines.robot import generate_mobile_robot, validate_robot
from roboverse.schemas.project import Drivetrain, Joint, JointLimits, Link


def errs(issues):
    return {i.code for i in issues if i.severity in ("error", "critical")}


@pytest.mark.parametrize("drive", ["differential", "four_wheel", "ackermann", "mecanum", "tracked"])
def test_generated_robots_are_valid(drive, registry):
    r = generate_mobile_robot("r", Drivetrain(drive_type=drive, wheel_separation=0.34, max_speed=0.5), [0.4, 0.3, 0.1], 4.0)
    assert errs(validate_robot(r, registry)) == set()


def test_detects_structural_errors(amr, registry):
    r = amr.robot
    r.joints.append(Joint(name="bad", type="revolute", parent="base_link", child="ghost"))
    r.joints.append(Joint(name="zero_axis", type="continuous", parent="base_link", child="laser", axis=[0, 0, 0]))
    r.links.append(Link(name="floating"))
    r.joints.append(Joint(name="lim", type="revolute", parent="base_link", child="imu_link",
                          limits=JointLimits(lower=1, upper=-1)))
    c = errs(validate_robot(r, registry))
    assert {"R004", "R006", "R011", "R012", "R009"} <= c


def test_drivetrain_sizing(amr, registry):
    amr.robot.drivetrain.max_speed = 2.0
    amr.robot.drivetrain.payload_kg = 120
    codes = {i.code for i in validate_robot(amr.robot, registry)}
    assert "R060" in codes and "R061" in codes


def test_urdf_roundtrip_preserves_unknown(amr):
    urdf = to_urdf(amr.robot)
    root = ET.fromstring(urdf)
    assert root.tag == "robot" and len(root.findall("link")) == len(amr.robot.links)
    extra = urdf.replace("</robot>", '<gazebo reference="base_link"><material>Gazebo/Blue</material></gazebo></robot>')
    robot, report = from_urdf(extra)
    assert len(robot.links) == len(amr.robot.links) and len(robot.joints) == len(amr.robot.joints)
    kept = [p for p in report["preserved"] if p["element"] == "gazebo"]
    assert kept, "unsupported elements must be preserved, not dropped"
    again = to_urdf(robot, report["preserved"])
    assert "<gazebo" in again


def test_sdf_and_xacro(amr):
    sdf = ET.fromstring(to_sdf(amr.robot))
    assert sdf.find("model/plugin").get("name") == "gz::sim::systems::DiffDrive"
    assert "${wheel_separation/2}" in to_xacro(amr.robot)


def test_mjcf_loads_in_mujoco(amr):
    mujoco = pytest.importorskip("mujoco")
    m = mujoco.MjModel.from_xml_string(to_mjcf(amr.robot, amr.world.objects))
    assert m.nu == 2 and m.nbody >= 5
