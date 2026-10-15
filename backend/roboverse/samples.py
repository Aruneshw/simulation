"""Project templates and sample projects."""
from __future__ import annotations

from .engines.cad.parametric import example_parts
from .engines.robot import generate_arm, generate_mobile_robot
from .engines.world.templates import make_world
from .schemas.project import (AssemblyItem, Cad, Circuit, ComponentInstance, ControllerModel, Drivetrain, Firmware,
                              PinAssignment, PinRef, Pose, Project, ProjectType, Scenario, SimulationConfig,
                              TwinBinding, Wire, World)


class CircuitBuilder:
    def __init__(self):
        self.c = Circuit()
        self.n = 0

    def add(self, iid, comp, x, y, twin=None, **params):
        self.c.instances.append(ComponentInstance(id=iid, component_id=comp, position=[x, y], params=params, twin_id=twin))
        return iid

    def wire(self, a: str, b: str, label=None):
        self.n += 1
        ai, ap = a.split(".", 1)
        bi, bp = b.split(".", 1)
        self.c.wires.append(Wire(id=f"W{self.n}", a=PinRef(instance=ai, pin=ap), b=PinRef(instance=bi, pin=bp), label=label))


def amr_circuit(faulty: bool = False) -> tuple[Circuit, list[PinAssignment]]:
    cb = CircuitBuilder()
    cb.add("BT1", "battery.lifepo4_4s_20ah", 20, 60)
    cb.add("F1", "fuse.blade", 140, 60, rating_a=15.0)
    cb.add("S1", "switch.estop_nc", 250, 60)
    cb.add("U1", "driver.l298n" if faulty else "driver.cytron_mdd10a", 620, 20)
    cb.add("U2", "reg.lm2596_5v", 380, 200)
    cb.add("U3", "mcu.esp32_devkitc", 380, 330)
    cb.add("M1", "motor.pololu_37d_50to1_12v", 900, 20, twin="twin_left_wheel_motor")
    cb.add("M2", "motor.pololu_37d_50to1_12v", 900, 140, twin="twin_right_wheel_motor")
    cb.add("U4", "sensor.rplidar_a1", 900, 330, twin="twin_lidar")
    cb.add("U5", "sensor.mpu6050_gy521", 900, 470, twin="twin_imu")
    cb.add("R1", "passive.resistor", 720, 560, resistance=4700.0)
    cb.add("R2", "passive.resistor", 720, 610, resistance=4700.0)
    if not faulty:
        cb.add("U6", "level.bss138_4ch", 620, 300)
    cb.add("G1", "ground", 40, 220)
    # power path: battery -> fuse -> e-stop -> main rail
    cb.wire("BT1.+", "F1.1", "VBAT")
    cb.wire("F1.2", "S1.1")
    cb.wire("S1.2", "U1.VM", "VMAIN")
    cb.wire("S1.2", "U2.VIN")
    cb.wire("U2.VOUT", "U3.5V", "5V")
    cb.wire("U2.VOUT", "U4.5V")
    cb.wire("U3.3V3", "U5.VCC", "3V3")
    cb.wire("U3.3V3", "R1.1")
    cb.wire("U3.3V3", "R2.1")
    gnds = ["BT1.-", "U1.GND", "U2.GND", "U3.GND", "U4.GND", "U5.GND", "M1.ENC_GND", "M2.ENC_GND", "G1.GND"]
    if faulty:
        cb.wire("U2.VOUT", "U1.VCC")  # L298N logic supply
    else:
        cb.wire("U3.3V3", "U6.LV")
        cb.wire("U2.VOUT", "U6.HV")
        gnds.append("U6.GND")
    for g in gnds[1:]:
        cb.wire(gnds[0], g, "GND")
    # motors
    cb.wire("U1.OUTA1", "M1.M+")
    cb.wire("U1.OUTA2", "M1.M-")
    cb.wire("U1.OUTB1", "M2.M+")
    cb.wire("U1.OUTB2", "M2.M-")
    cb.wire("U2.VOUT", "M1.ENC_VCC")
    cb.wire("U2.VOUT", "M2.ENC_VCC")
    # controller -> driver
    cb.wire("U3.GPIO25", "U1.PWMA")
    cb.wire("U3.GPIO27", "U1.INA1")
    cb.wire("U3.GPIO14", "U1.INA2")
    cb.wire("U3.GPIO26", "U1.PWMB")
    cb.wire("U3.GPIO13", "U1.INB1")
    cb.wire("U3.GPIO32", "U1.INB2")
    # encoders
    enc = [("M1.ENC_A", "GPIO4"), ("M1.ENC_B", "GPIO5"), ("M2.ENC_A", "GPIO18"), ("M2.ENC_B", "GPIO19")]
    for k, (src, gpio) in enumerate(enc, start=1):
        if faulty:
            cb.wire(src, f"U3.{gpio}")  # 5 V encoder straight into a 3.3 V-only GPIO
        else:
            cb.wire(src, f"U6.HV{k}")
            cb.wire(f"U6.LV{k}", f"U3.{gpio}")
    # lidar UART and IMU I2C
    cb.wire("U4.TX", "U3.GPIO16")
    cb.wire("U4.RX", "U3.GPIO17")
    cb.wire("U5.SDA", "U3.GPIO21", "SDA")
    cb.wire("U5.SCL", "U3.GPIO22", "SCL")
    cb.wire("R1.2", "U3.GPIO21")
    cb.wire("R2.2", "U3.GPIO22")
    pin_map = [
        PinAssignment(channel="left_wheel_pwm", pin="GPIO25", function="pwm", twin_id="twin_left_wheel_motor"),
        PinAssignment(channel="left_wheel_dir_a", pin="GPIO27", function="gpio_out", twin_id="twin_left_wheel_motor"),
        PinAssignment(channel="left_wheel_dir_b", pin="GPIO14", function="gpio_out", twin_id="twin_left_wheel_motor"),
        PinAssignment(channel="right_wheel_pwm", pin="GPIO26", function="pwm", twin_id="twin_right_wheel_motor"),
        PinAssignment(channel="right_wheel_dir_a", pin="GPIO13", function="gpio_out", twin_id="twin_right_wheel_motor"),
        PinAssignment(channel="right_wheel_dir_b", pin="GPIO32", function="gpio_out", twin_id="twin_right_wheel_motor"),
        PinAssignment(channel="left_wheel_enc_a", pin="GPIO4", function="encoder", twin_id="twin_left_wheel_motor"),
        PinAssignment(channel="left_wheel_enc_b", pin="GPIO5", function="encoder", twin_id="twin_left_wheel_motor"),
        PinAssignment(channel="right_wheel_enc_a", pin="GPIO18", function="encoder", twin_id="twin_right_wheel_motor"),
        PinAssignment(channel="right_wheel_enc_b", pin="GPIO19", function="encoder", twin_id="twin_right_wheel_motor"),
        PinAssignment(channel="lidar_rx", pin="GPIO16", function="uart_rx", twin_id="twin_lidar"),
        PinAssignment(channel="lidar_tx", pin="GPIO17", function="uart_tx", twin_id="twin_lidar"),
        PinAssignment(channel="imu_sda", pin="GPIO21", function="i2c_sda", twin_id="twin_imu"),
        PinAssignment(channel="imu_scl", pin="GPIO22", function="i2c_scl", twin_id="twin_imu"),
    ]
    return cb.c, pin_map


def warehouse_amr(faulty: bool = False) -> Project:
    drive = Drivetrain(drive_type="differential", wheel_radius=0.05, wheel_width=0.032, wheel_separation=0.34,
                       wheel_friction=0.8, max_speed=0.6, max_accel=0.6, max_decel=1.0, payload_kg=2.0)
    robot = generate_mobile_robot("rv_warehouse_amr", drive, [0.40, 0.30, 0.10], chassis_mass=4.0, wheel_mass=0.12)
    robot.controller_ref = "U3"
    robot.power.battery_ref = "BT1"
    circuit, pin_map = amr_circuit(faulty)
    world = make_world("warehouse")
    scenario = Scenario(mode="waypoints", waypoints=[[-3.5, -5.5], [0.5, 2.5], [4.6, 6.0], [7.5, -4.8]],
                        return_to_dock=True, dock_object="dock_1")
    parts = example_parts()
    cad = Cad(parts=parts, assembly=[AssemblyItem(id="a_plate", part="chassis_plate", pose=Pose(xyz=[0, 0, 0.1]), link="base_link"),
                                     AssemblyItem(id="a_br_l", part="motor_bracket", pose=Pose(xyz=[-0.02, 0.10, 0.104]), link="base_link"),
                                     AssemblyItem(id="a_br_r", part="motor_bracket", pose=Pose(xyz=[-0.02, -0.145, 0.104]), link="base_link")])
    name = "Warehouse AMR" + (" (with design errors)" if faulty else "")
    p = Project(name=name, type=ProjectType.amr,
                description="Differential-drive AMR: LiFePO4 4S, Cytron MDD10A, ESP32, Pololu 37D gearmotors, "
                            "RPLIDAR A1, MPU-6050. Visits three waypoints, the loading dock, then returns to charge."
                if not faulty else "Same AMR with typical wiring mistakes for the compatibility engine to catch.",
                world=world, robot=robot, circuit=circuit, cad=cad,
                firmware=Firmware(target="esp32", mode="behavioral", controller=ControllerModel(loop_hz=100), pin_map=pin_map),
                simulation=SimulationConfig(dt=0.005, duration=180.0, scenario=scenario))
    p.bindings = [TwinBinding(twin_id="twin_left_wheel_motor", label="Left drive", mechanical="act_left_wheel", electrical="M1",
                              firmware_channels=["left_wheel_pwm", "left_wheel_enc_a"], sim_entity="left_wheel_joint"),
                  TwinBinding(twin_id="twin_right_wheel_motor", label="Right drive", mechanical="act_right_wheel", electrical="M2",
                              firmware_channels=["right_wheel_pwm", "right_wheel_enc_a"], sim_entity="right_wheel_joint"),
                  TwinBinding(twin_id="twin_lidar", label="2D LiDAR", mechanical="lidar", electrical="U4",
                              firmware_channels=["lidar_rx", "lidar_tx"], sim_entity="lidar"),
                  TwinBinding(twin_id="twin_imu", label="IMU", mechanical="imu", electrical="U5",
                              firmware_channels=["imu_sda", "imu_scl"], sim_entity="imu")]
    return p


def obstacle_course_bot() -> Project:
    p = warehouse_amr()
    p.name = "Obstacle course"
    p.description = "Goal-based navigation through a cluttered course."
    p.world = make_world("obstacle_course")
    p.simulation.scenario = Scenario(mode="goal", goal=[5.2, -2.8])
    p.simulation.duration = 90.0
    return p


def blank(name: str, ptype: ProjectType, template: str | None = None) -> Project:
    world = make_world(template) if template else World()
    if ptype in (ProjectType.robotic_arm, ProjectType.gripper):
        robot = generate_arm("arm", 4)
    elif ptype in (ProjectType.amr, ProjectType.agv):
        drive = Drivetrain(wheel_radius=0.075 if ptype == ProjectType.agv else 0.05, wheel_separation=0.45 if ptype == ProjectType.agv else 0.3)
        robot = generate_mobile_robot("robot", drive, [0.6, 0.45, 0.15] if ptype == ProjectType.agv else [0.4, 0.3, 0.1], 8.0 if ptype == ProjectType.agv else 4.0)
    else:
        from .schemas.project import Robot  # noqa: PLC0415
        robot = Robot()
    return Project(name=name, type=ptype, world=world, robot=robot)


TEMPLATES = {
    "warehouse_amr": ("Warehouse AMR (complete digital twin)", warehouse_amr),
    "warehouse_amr_faulty": ("Warehouse AMR with design errors", lambda: warehouse_amr(True)),
    "obstacle_course": ("Obstacle course navigation", obstacle_course_bot),
}
