"""Component library schema.

Every rating carries a provenance so the UI can tell datasheet values from
assumptions. Unknown ratings are left as None rather than invented.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SupportStatus(str, Enum):
    fully_modeled = "fully_modeled"  # solved by a circuit/physics engine from first principles
    simulation_supported = "simulation_supported"  # parametric engineering model in the co-simulator
    behavioral = "behavioral"  # simplified behavioural model, not cycle/transistor accurate
    cad_only = "cad_only"
    schematic_only = "schematic_only"  # ERC/compatibility only, no dynamic model
    imported_unverified = "imported_unverified"
    user_defined = "user_defined"


class Category(str, Enum):
    mechanical = "mechanical"
    wheels_gearboxes = "wheels_gearboxes"
    motors_actuators = "motors_actuators"
    sensors = "sensors"
    microcontrollers = "microcontrollers"
    sbc = "sbc"
    motor_drivers = "motor_drivers"
    power_electronics = "power_electronics"
    passives = "passives"
    analog_ics = "analog_ics"
    digital_ics = "digital_ics"
    batteries = "batteries"
    communication = "communication"
    connectors = "connectors"
    dev_boards = "dev_boards"
    protection_switching = "protection_switching"
    robot_models = "robot_models"
    industrial_equipment = "industrial_equipment"
    environments = "environments"
    firmware_adapters = "firmware_adapters"


PinType = Literal[
    "power_in", "power_out", "ground", "digital_in", "digital_out", "digital_io",
    "pwm_in", "analog_in", "analog_out", "uart_tx", "uart_rx", "i2c_sda", "i2c_scl",
    "spi_mosi", "spi_miso", "spi_sck", "spi_cs", "can_h", "can_l", "can_tx", "can_rx",
    "motor_out", "motor_in", "encoder_out", "usb", "passive", "nc",
]


class Rated(BaseModel):
    """A numeric rating with its source."""
    value: Optional[float] = None
    unit: str = ""
    source: Literal["datasheet", "assumption", "user", "unknown"] = "unknown"
    note: str = ""


class Pin(BaseModel):
    id: str
    name: str
    type: PinType
    # power pins
    v_min: Optional[float] = None
    v_max: Optional[float] = None
    v_nominal: Optional[float] = None  # for power_out: the rail voltage it provides
    i_max: Optional[float] = None  # A, continuous source/sink capability
    # logic pins
    logic_v: Optional[float] = None  # output high level / IO domain voltage
    vih_min: Optional[float] = None  # minimum input-high voltage
    v_abs_max: Optional[float] = None  # absolute max input voltage
    five_v_tolerant: Optional[bool] = None
    required: bool = False  # floating = warning
    capabilities: list[str] = Field(default_factory=list)  # pwm, adc, uart, i2c, spi, can, interrupt
    group: Optional[str] = None  # e.g. "A" channel of a dual driver
    spice_node: Optional[int] = None  # index into spice model terminals


class Provenance(BaseModel):
    source: Literal["builtin_verified", "public_library", "datasheet", "user_import", "manufacturer", "community"]
    author: str = "RoboVerse Studio"
    license: str = "CC0-1.0"
    url: Optional[str] = None
    verified: bool = False
    notes: str = ""


class Component(BaseModel):
    id: str
    version: str = "1.0.0"
    name: str
    category: Category
    tags: list[str] = Field(default_factory=list)
    manufacturer: Optional[str] = None
    part_number: Optional[str] = None
    description: str = ""
    symbol: str = "box"  # symbol key used by the schematic editor
    footprint: Optional[str] = None  # KiCad footprint reference
    pins: list[Pin] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    ratings: dict[str, Rated] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)  # model parameters (e.g. resistance, kt)
    sim_model: Optional[str] = None  # e.g. spice:R, motor:dc_brushed, battery:thevenin
    support_status: SupportStatus = SupportStatus.schematic_only
    datasheet: Optional[str] = None
    compatibility: list[str] = Field(default_factory=list)  # free-text constraints shown to the user
    dependencies: list[str] = Field(default_factory=list)  # other component ids required
    provenance: Provenance = Field(default_factory=lambda: Provenance(source="builtin_verified"))

    def pin(self, pid: str) -> Optional[Pin]:
        return next((p for p in self.pins if p.id == pid), None)

    def rating(self, key: str) -> Optional[float]:
        r = self.ratings.get(key)
        return r.value if r else None
