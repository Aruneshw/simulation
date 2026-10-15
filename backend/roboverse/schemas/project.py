"""Shared project model — the single source of truth for the digital twin.

Every workspace (world builder, CAD, robot designer, circuit studio, firmware,
simulation) reads and writes the same `Project` document. Cross-domain links
are explicit: a `TwinBinding` ties one mechanical actuator/sensor to one
circuit instance and one firmware channel through a shared `twin_id`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class ProjectType(str, Enum):
    amr = "amr"
    agv = "agv"
    robotic_arm = "robotic_arm"
    drone = "drone"
    gripper = "gripper"
    industrial_automation = "industrial_automation"
    iot = "iot"
    motor_control = "motor_control"
    embedded = "embedded"
    custom = "custom"


Vec3 = list[float]


class Pose(BaseModel):
    xyz: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rpy: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])


# ---------------------------------------------------------------- world ----

WorldKind = Literal[
    "floor", "wall", "door", "ramp", "stairs", "platform", "box", "cylinder",
    "rack", "table", "workstation", "loading_zone", "charging_station",
    "human", "moving_object", "mesh", "camera", "lidar", "robot_start", "goal",
]


class CollisionProps(BaseModel):
    enabled: bool = True
    friction: float = 0.8
    restitution: float = 0.0


class MotionProfile(BaseModel):
    """Scripted motion for dynamic obstacles (humans, forklifts...)."""
    type: Literal["patrol"] = "patrol"
    waypoints: list[list[float]] = Field(default_factory=list)  # [[x, y], ...]
    speed: float = 0.5


class WorldObject(BaseModel):
    id: str
    name: str
    kind: WorldKind
    shape: Literal["box", "cylinder", "plane", "mesh", "marker"] = "box"
    size: Vec3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])  # box: x,y,z ; cylinder: r,r,h
    pose: Pose = Field(default_factory=Pose)
    color: str = "#8a96a8"
    static: bool = True
    collision: CollisionProps = Field(default_factory=CollisionProps)
    motion: Optional[MotionProfile] = None
    mesh_ref: Optional[str] = None
    parent: Optional[str] = None  # scene hierarchy
    props: dict[str, Any] = Field(default_factory=dict)


class World(BaseModel):
    template: Optional[str] = None
    bounds: list[float] = Field(default_factory=lambda: [-10.0, -10.0, 10.0, 10.0])
    gravity: Vec3 = Field(default_factory=lambda: [0.0, 0.0, -9.81])
    objects: list[WorldObject] = Field(default_factory=list)


# ----------------------------------------------------------------- robot ----

class Geometry(BaseModel):
    type: Literal["box", "cylinder", "sphere", "mesh"]
    size: Vec3 = Field(default_factory=lambda: [0.1, 0.1, 0.1])  # box xyz | cylinder r,_,length | sphere r
    mesh_ref: Optional[str] = None


class Link(BaseModel):
    name: str
    geometry: Optional[Geometry] = None
    origin: Pose = Field(default_factory=Pose)  # visual/collision origin in link frame
    mass: float = 0.0
    material: str = "aluminium"
    # Optional explicit inertia [ixx, iyy, izz, ixy, ixz, iyz]; computed from geometry when absent.
    inertia: Optional[list[float]] = None
    color: str = "#5b6b82"


class JointLimits(BaseModel):
    lower: float = 0.0
    upper: float = 0.0
    effort: float = 10.0
    velocity: float = 10.0


class Joint(BaseModel):
    name: str
    type: Literal["fixed", "continuous", "revolute", "prismatic"]
    parent: str
    child: str
    origin: Pose = Field(default_factory=Pose)
    axis: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    limits: Optional[JointLimits] = None


DriveType = Literal[
    "differential", "four_wheel", "ackermann", "mecanum", "tracked",
    "arm", "mobile_manipulator", "custom",
]


class Drivetrain(BaseModel):
    drive_type: DriveType = "differential"
    wheel_radius: float = 0.05
    wheel_width: float = 0.03
    wheel_separation: float = 0.30
    wheel_friction: float = 0.9
    gear_ratio: float = 1.0  # extra reduction between motor output shaft and wheel
    max_speed: float = 1.0  # m/s
    max_accel: float = 1.0  # m/s^2
    max_decel: float = 1.5  # m/s^2
    max_steering_angle: float = 0.6  # rad (ackermann)
    payload_kg: float = 0.0
    rolling_resistance: float = 0.015


class Actuator(BaseModel):
    id: str
    twin_id: str
    joint: str
    component_ref: str  # library component id (motor)
    role: str = "drive"  # left_wheel | right_wheel | drive | arm


class Sensor(BaseModel):
    id: str
    twin_id: str
    type: Literal["lidar", "camera", "depth", "imu", "encoder", "ultrasonic", "bumper"]
    link: str
    pose: Pose = Field(default_factory=Pose)
    rate_hz: float = 10.0
    noise_std: float = 0.0
    component_ref: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)


class PowerSystem(BaseModel):
    battery_ref: Optional[str] = None  # circuit instance id of the battery
    base_load_w: Optional[float] = None  # computed from power budget when None
    driver_efficiency: float = 0.9


class Robot(BaseModel):
    name: str = "robot"
    base_link: str = "base_link"
    links: list[Link] = Field(default_factory=list)
    joints: list[Joint] = Field(default_factory=list)
    drivetrain: Drivetrain = Field(default_factory=Drivetrain)
    actuators: list[Actuator] = Field(default_factory=list)
    sensors: list[Sensor] = Field(default_factory=list)
    power: PowerSystem = Field(default_factory=PowerSystem)
    controller_ref: Optional[str] = None  # circuit instance id of the main controller


# --------------------------------------------------------------- circuit ----

class ComponentInstance(BaseModel):
    id: str  # reference designator, e.g. U1, M1, BT1
    component_id: str  # library component id
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    rotation: int = 0
    params: dict[str, Any] = Field(default_factory=dict)  # value overrides (e.g. resistance)
    twin_id: Optional[str] = None


class PinRef(BaseModel):
    instance: str
    pin: str


class Wire(BaseModel):
    id: str
    a: PinRef
    b: PinRef
    label: Optional[str] = None


class Circuit(BaseModel):
    instances: list[ComponentInstance] = Field(default_factory=list)
    wires: list[Wire] = Field(default_factory=list)


# -------------------------------------------------------------- firmware ----

class PinAssignment(BaseModel):
    """Maps a firmware channel to a controller pin and a twin entity."""
    channel: str  # e.g. left_pwm, left_dir, left_enc_a
    pin: str  # controller pin id
    function: Literal["pwm", "gpio_out", "gpio_in", "adc", "uart_tx", "uart_rx",
                      "i2c_sda", "i2c_scl", "spi_mosi", "spi_miso", "spi_sck",
                      "can_tx", "can_rx", "encoder"]
    twin_id: Optional[str] = None


class ControllerModel(BaseModel):
    type: Literal["diff_drive_pid"] = "diff_drive_pid"
    loop_hz: float = 100.0
    kp: float = 0.8
    ki: float = 4.0
    kd: float = 0.0
    feedforward: float = 1.0


class FirmwareFile(BaseModel):
    path: str
    content: str


class Firmware(BaseModel):
    target: str = "arduino_uno"  # firmware target id (see engines/firmware/targets.py)
    mode: Literal["behavioral", "hal_mock", "emulated", "hil"] = "behavioral"
    controller: ControllerModel = Field(default_factory=ControllerModel)
    pin_map: list[PinAssignment] = Field(default_factory=list)
    files: list[FirmwareFile] = Field(default_factory=list)


# ------------------------------------------------------------------- CAD ----

class SketchShape(BaseModel):
    type: Literal["rect", "circle", "polygon"]
    params: dict[str, Any] = Field(default_factory=dict)  # rect: w,h,cx,cy  circle: r,cx,cy  polygon: points


class Feature(BaseModel):
    id: str
    op: Literal["box", "cylinder", "sphere", "extrude", "union", "difference", "intersection", "translate", "rotate"]
    params: dict[str, Any] = Field(default_factory=dict)
    sketch: Optional[list[SketchShape]] = None  # extrude: first = outer, rest = holes
    operands: list[str] = Field(default_factory=list)  # boolean operands (feature ids)


class CadPart(BaseModel):
    id: str
    name: str
    kind: Literal["parametric", "imported_mesh"] = "parametric"
    material: str = "aluminium"
    parameters: dict[str, float] = Field(default_factory=dict)  # named dimensions; "$name" refs in feature params
    features: list[Feature] = Field(default_factory=list)
    result: Optional[str] = None  # feature id that is the final body (default: last)
    mesh_ref: Optional[str] = None  # imported mesh asset id
    twin_id: Optional[str] = None


class AssemblyItem(BaseModel):
    id: str
    part: str
    pose: Pose = Field(default_factory=Pose)
    link: Optional[str] = None  # robot link this item is mounted to


class Mate(BaseModel):
    id: str
    type: Literal["coincident", "concentric", "offset"]
    a: str
    b: str
    offset: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class Cad(BaseModel):
    parts: list[CadPart] = Field(default_factory=list)
    assembly: list[AssemblyItem] = Field(default_factory=list)
    mates: list[Mate] = Field(default_factory=list)


# ------------------------------------------------------------ simulation ----

class Scenario(BaseModel):
    mode: Literal["goal", "waypoints", "teleop", "dock", "open_loop"] = "waypoints"
    waypoints: list[list[float]] = Field(default_factory=list)
    goal: Optional[list[float]] = None
    return_to_dock: bool = False
    dock_object: Optional[str] = None
    estop_at: Optional[float] = None  # scripted emergency stop time (s)
    open_loop_cmd: list[float] = Field(default_factory=lambda: [0.3, 0.0])  # v, w for open_loop


class SimulationConfig(BaseModel):
    physics_backend: Literal["builtin_planar", "mujoco"] = "builtin_planar"
    dt: float = 0.005
    duration: float = 60.0
    seed: int = 42
    real_time_factor: float = 1.0  # 0 = as fast as possible
    sensor_noise: bool = True
    comm_latency_ms: float = 10.0
    ambient_c: float = 25.0
    scenario: Scenario = Field(default_factory=Scenario)
    telemetry_hz: float = 20.0
    localization_scan_matching: bool = True  # LiDAR map matching; disable to study pure odometry drift


class TwinBinding(BaseModel):
    """Shared identity across domains."""
    twin_id: str
    label: str
    mechanical: Optional[str] = None  # actuator id / sensor id / link name
    electrical: Optional[str] = None  # circuit instance id
    firmware_channels: list[str] = Field(default_factory=list)
    sim_entity: Optional[str] = None


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: Optional[str] = None
    name: str
    type: ProjectType = ProjectType.amr
    description: str = ""
    world: World = Field(default_factory=World)
    robot: Robot = Field(default_factory=Robot)
    circuit: Circuit = Field(default_factory=Circuit)
    firmware: Firmware = Field(default_factory=Firmware)
    cad: Cad = Field(default_factory=Cad)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    bindings: list[TwinBinding] = Field(default_factory=list)
    # Files we imported but cannot interpret are kept verbatim, never dropped.
    preserved: dict[str, Any] = Field(default_factory=dict)
