"""Digital-twin resolver: follows the real wiring from each mechanical actuator
to its motor, driver channel, controller pin, firmware channel and battery.

Nothing is inferred from 3D placement. If a wire is missing, the actuator is
unbound and the co-simulator will not drive it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..library.registry import Registry
from ..schemas.issues import Issue
from ..schemas.library import Component
from ..schemas.project import Project
from .circuit.compat import CompatibilityEngine


@dataclass
class ActuatorBinding:
    actuator_id: str
    joint: str
    role: str
    twin_id: str
    motor_instance: Optional[str] = None
    motor: Optional[Component] = None
    driver_instance: Optional[str] = None
    driver: Optional[Component] = None
    channel: Optional[str] = None
    pwm_pin: Optional[str] = None  # controller pin id
    pwm_channel: Optional[str] = None  # firmware channel name
    encoder_pin: Optional[str] = None
    battery_instance: Optional[str] = None
    battery: Optional[Component] = None
    bus_voltage_nominal: Optional[float] = None
    fuse_instance: Optional[str] = None
    fuse_rating: Optional[float] = None
    issues: list[str] = field(default_factory=list)

    @property
    def drivable(self) -> bool:
        return all([self.motor, self.driver, self.battery, self.pwm_pin])

    def to_dict(self) -> dict:
        return {"actuator": self.actuator_id, "joint": self.joint, "role": self.role, "twin_id": self.twin_id,
                "motor": self.motor_instance, "motor_component": self.motor.id if self.motor else None,
                "driver": self.driver_instance, "driver_component": self.driver.id if self.driver else None,
                "channel": self.channel, "controller_pin": self.pwm_pin, "firmware_channel": self.pwm_channel,
                "encoder_pin": self.encoder_pin, "battery": self.battery_instance,
                "bus_voltage": self.bus_voltage_nominal, "fuse": self.fuse_instance, "drivable": self.drivable,
                "issues": self.issues}


def _trace_to(g, inst: str, pin: str, target: Optional[str], depth: int = 3):
    """Follow a signal net to `target`, passing through level shifters / buffers that declare
    `params.passthrough` pin pairs. Returns the target's NetPin or None."""
    net = g.net_of(inst, pin)
    if not net or not target:
        return None
    hit = next((p for p in net.pins if p.instance.id == target), None)
    if hit or depth == 0:
        return hit
    for p in net.pins:
        for a, b in p.component.params.get("passthrough", []):
            other = b if p.pin.id == a else a if p.pin.id == b else None
            if other and p.instance.id != inst:
                found = _trace_to(g, p.instance.id, other, target, depth - 1)
                if found:
                    return found
    return None


def resolve_twin(project: Project, registry: Registry) -> tuple[list[ActuatorBinding], list[Issue], CompatibilityEngine]:
    eng = CompatibilityEngine(project.circuit, registry, project.firmware, project.robot.controller_ref)
    eng.run()
    g = eng.g
    issues: list[Issue] = []
    ctrl = project.robot.controller_ref

    def add(code, sev, title, msg, refs=(), fix="", connection=None):
        issues.append(Issue(code=code, severity=sev, domain="twin", title=title, message=msg, refs=list(refs), fix=fix,
                            connection=connection))

    if not ctrl:
        add("T010", "error", "No controller selected", "The robot has no controller assigned, so no firmware can command the motors.",
            fix="Select the main controller instance in the Robot designer (Controller hardware).")
    elif ctrl not in g.instances:
        add("T010b", "error", "Controller instance missing", f"Controller '{ctrl}' does not exist in the circuit.", [ctrl])
    pin_to_channel = {a.pin: a for a in project.firmware.pin_map}
    if ctrl and ctrl in g.components:
        ctrl_pins = {p.id for p in g.components[ctrl].pins}
        for a in project.firmware.pin_map:
            if a.pin not in ctrl_pins:
                add("T009", "error", "Firmware pin does not exist",
                    f"Channel '{a.channel}' is mapped to pin '{a.pin}', which {ctrl} does not have.", [ctrl],
                    "Pick a valid pin in the Firmware pin map.")
    by_twin = {i.twin_id: i.id for i in project.circuit.instances if i.twin_id}
    for b in project.bindings:
        if b.electrical and b.twin_id not in by_twin:
            by_twin[b.twin_id] = b.electrical
    out: list[ActuatorBinding] = []
    for act in project.robot.actuators:
        ab = ActuatorBinding(act.id, act.joint, act.role, act.twin_id)
        out.append(ab)
        mi = by_twin.get(act.twin_id)
        if not mi or mi not in g.components:
            ab.issues.append("no electrical motor bound")
            add("T001", "error", "Actuator has no electrical motor",
                f"Actuator '{act.id}' ({act.joint}) is not bound to a motor in the schematic. The simulator will not drive it.",
                [act.id], "Place the motor in Circuit Studio and set its twin id, or use Auto-bind.", connection=act.joint)
            continue
        ab.motor_instance, ab.motor = mi, g.components[mi]
        if act.component_ref != ab.motor.id:
            add("T002", "warning", "Mechanical and electrical motor differ",
                f"Actuator '{act.id}' specifies {act.component_ref} but the schematic uses {ab.motor.id}. "
                "The electrical part's ratings will be used.", [act.id, mi])
        net = g.net_of(mi, "M+")
        drv_pin = next((p for p in (net.pins if net else []) if p.pin.type == "motor_out"), None)
        if not drv_pin:
            ab.issues.append("motor not wired to a driver")
            add("T003", "error", "Motor not connected to a driver",
                f"{mi}.M+ is not wired to a motor driver output, so commands cannot reach it.", [mi],
                "Wire M+/M- to OUTx1/OUTx2 of an H-bridge channel.", connection=f"{mi}.M+")
            continue
        ab.driver_instance, ab.driver, ab.channel = drv_pin.instance.id, drv_pin.component, drv_pin.pin.group
        pwm_pid = f"PWM{ab.channel}" if ab.driver.pin(f"PWM{ab.channel}") else None
        if pwm_pid:
            pnet = g.net_of(ab.driver_instance, pwm_pid)
            cpin = next((p for p in (pnet.pins if pnet else []) if p.instance.id == ctrl), None)
            if cpin:
                ab.pwm_pin = cpin.pin.id
                fw = pin_to_channel.get(cpin.pin.id)
                if fw:
                    ab.pwm_channel = fw.channel
                    if fw.function != "pwm":
                        add("T006", "warning", "Firmware channel is not PWM",
                            f"{ctrl}.{cpin.pin.id} drives {ab.driver_instance}.{pwm_pid} but firmware configures it as '{fw.function}'.",
                            [ctrl, ab.driver_instance], "Set the channel function to pwm.")
                else:
                    add("T005", "warning", "PWM pin not in firmware pin map",
                        f"{ctrl}.{cpin.pin.id} is wired to {ab.driver_instance}.{pwm_pid} but no firmware channel uses it.",
                        [ctrl], "Add it to the firmware pin map (Auto-bind does this).")
            else:
                ab.issues.append("driver PWM not wired to controller")
                add("T004", "error", "Driver input not connected to the controller",
                    f"{ab.driver_instance}.{pwm_pid} is not wired to the controller ({ctrl}).", [ab.driver_instance],
                    "Wire the PWM/EN input to a PWM-capable controller pin.", connection=f"{ab.driver_instance}.{pwm_pid}")
        vm = next((p for p in ab.driver.pins if p.type == "power_in" and p.id.startswith("VM")), None)
        rail = eng.rail_of(ab.driver_instance, vm.id) if vm else None
        bat = next((s for s in (rail.sources if rail else []) if s.component.sim_model in ("battery:thevenin", "spice:V")), None)
        if bat:
            ab.battery_instance, ab.battery, ab.bus_voltage_nominal = bat.instance.id, bat.component, rail.v_nom
            for nid in rail.nets:
                for p in eng._net(nid).pins:
                    if p.component.sim_model == "protection:fuse_i2t":
                        ab.fuse_instance = p.instance.id
                        ab.fuse_rating = p.instance.params.get("rating_a", p.component.params.get("rating_a"))
        else:
            ab.issues.append("driver has no power source")
            add("T007", "error", "Motor driver is not powered",
                f"{ab.driver_instance}.{vm.id if vm else 'VM'} has no battery or supply on its rail.", [ab.driver_instance],
                "Connect VM to the battery (through the fuse).")
        if ab.motor.pin("ENC_A"):
            epin = _trace_to(g, mi, "ENC_A", ctrl)
            if epin:
                ab.encoder_pin = epin.pin.id
            else:
                add("T008", "warning", "Encoder not wired",
                    f"{mi}.ENC_A is not connected to the controller; the wheel loop will run open-loop and odometry is unavailable.",
                    [mi], "Wire ENC_A/ENC_B to interrupt-capable controller pins.")
    for s in project.robot.sensors:
        if s.type in ("encoder",):
            continue
        if s.twin_id not in by_twin:
            add("T020", "info", "Sensor has no electrical counterpart",
                f"Sensor '{s.id}' ({s.type}) is simulated but not placed in the schematic; its power and interface are not validated.",
                [s.id], "Add the sensor to Circuit Studio and set its twin id.")
    return out, issues, eng


def auto_bind(project: Project, registry: Registry) -> dict:
    """Create firmware pin-map entries and twin bindings from the existing wiring (does not add wires)."""
    bindings, _, eng = resolve_twin(project, registry)
    added = []
    existing = {a.pin for a in project.firmware.pin_map}
    from ..schemas.project import PinAssignment, TwinBinding  # noqa: PLC0415
    for b in bindings:
        if b.pwm_pin and b.pwm_pin not in existing:
            ch = f"{b.role}_pwm"
            project.firmware.pin_map.append(PinAssignment(channel=ch, pin=b.pwm_pin, function="pwm", twin_id=b.twin_id))
            existing.add(b.pwm_pin)
            added.append(ch)
        if b.encoder_pin and b.encoder_pin not in existing:
            ch = f"{b.role}_enc_a"
            project.firmware.pin_map.append(PinAssignment(channel=ch, pin=b.encoder_pin, function="encoder", twin_id=b.twin_id))
            existing.add(b.encoder_pin)
            added.append(ch)
        if b.motor_instance and not any(x.twin_id == b.twin_id for x in project.bindings):
            project.bindings.append(TwinBinding(twin_id=b.twin_id, label=f"{b.role} drive", mechanical=b.actuator_id,
                                                electrical=b.motor_instance,
                                                firmware_channels=[c for c in (b.pwm_channel, f"{b.role}_pwm") if c],
                                                sim_entity=b.joint))
    _ = eng
    return {"added_channels": added, "bindings": [b.to_dict() for b in resolve_twin(project, registry)[0]]}
