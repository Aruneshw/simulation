"""Hardware compatibility engine + electrical rule check (ERC) + power budget.

Every finding names the exact connection, explains the mechanism, cites the
specification used (with its provenance) and proposes a practical fix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ...library.registry import Registry
from ...schemas.issues import Issue, SpecRef, sort_issues
from ...schemas.library import Component, Pin
from ...schemas.project import Circuit, Firmware
from .netlist import Net, NetGraph, NetPin, build_nets

OUTPUT_FUNCS = {"pwm", "gpio_out", "uart_tx", "spi_mosi", "spi_sck", "can_tx"}
INPUT_FUNCS = {"gpio_in", "adc", "uart_rx", "spi_miso", "can_rx", "encoder"}
DEDICATED_DRIVERS = {"digital_out", "uart_tx", "encoder_out", "analog_out", "can_rx", "spi_miso"}
DEDICATED_RECEIVERS = {"digital_in", "pwm_in", "uart_rx", "analog_in", "spi_mosi", "spi_sck", "spi_cs", "can_tx"}
# protocol pin on a peripheral -> capability needed on the controller pin it connects to
PROTOCOL_CAP = {"uart_tx": "uart_rx", "uart_rx": "uart_tx", "i2c_sda": "i2c", "i2c_scl": "i2c",
                "spi_mosi": "spi", "spi_miso": "spi", "spi_sck": "spi", "can_tx": "can", "can_rx": "can",
                "pwm_in": "pwm"}

# Running current of a brushed motor when only stall/no-load are known. This
# is an assumption and is labelled as such everywhere it is used.
MOTOR_TYPICAL_FRACTION_OF_STALL = 0.25


def _spec(comp: Component, field_: str, value, unit="", source=None) -> SpecRef:
    r = comp.ratings.get(field_)
    return SpecRef(component=comp.id, field=field_, value=value, unit=unit or (r.unit if r else ""),
                   source=source or (r.source if r else "datasheet" if comp.provenance.verified else "assumption"),
                   url=comp.datasheet)


def _pin_spec(comp: Component, pin: Pin, field_: str, value, unit="V") -> SpecRef:
    return SpecRef(component=comp.id, field=f"pin {pin.id}.{field_}", value=value, unit=unit,
                   source="datasheet" if comp.provenance.verified else "assumption", url=comp.datasheet)


def conductive_pairs(comp: Component, params: dict) -> list[tuple[str, str]]:
    """Two-terminal parts that pass DC current with negligible drop when closed."""
    if comp.sim_model == "protection:fuse_i2t" or comp.category.value == "connectors":
        return [(comp.pins[0].id, comp.pins[1].id)] if len(comp.pins) >= 2 else []
    if comp.sim_model == "spice:SW" and params.get("closed", comp.params.get("closed", True)):
        return [(comp.pins[0].id, comp.pins[1].id)]
    if comp.id == "sensor.ina219":
        return [("VIN+", "VIN-")]
    return []


@dataclass
class Rail:
    id: str
    nets: list[str]
    v_nom: Optional[float] = None
    v_max: Optional[float] = None
    v_min: Optional[float] = None
    sources: list[NetPin] = field(default_factory=list)
    is_ground: bool = False
    load_typ: float = 0.0
    load_peak: float = 0.0
    loads: list[dict] = field(default_factory=list)

    @property
    def name(self) -> str:
        if self.is_ground:
            return "GND"
        if self.sources:
            return f"{self.sources[0].label} ({self.v_nom:g} V)" if self.v_nom is not None else self.sources[0].label
        return self.id


class CompatibilityEngine:
    def __init__(self, circuit: Circuit, registry: Registry, firmware: Optional[Firmware] = None,
                 controller_ref: Optional[str] = None):
        self.circuit = circuit
        self.registry = registry
        self.firmware = firmware
        self.controller_ref = controller_ref
        self.g: NetGraph = build_nets(circuit, registry)
        self.issues: list[Issue] = []
        self.rails: dict[str, Rail] = {}
        self.net_rail: dict[str, str] = {}
        self.pin_funcs: dict[tuple[str, str], str] = {}
        if firmware and controller_ref:
            for a in firmware.pin_map:
                self.pin_funcs[(controller_ref, a.pin)] = a.function

    # ------------------------------------------------------------ helpers --
    def add(self, **kw) -> None:
        self.issues.append(Issue(domain=kw.pop("domain", "electrical"), **kw))

    def _source_range(self, np_: NetPin) -> tuple[Optional[float], Optional[float], Optional[float]]:
        comp, inst = np_.component, np_.instance
        v = inst.params.get("voltage", comp.params.get("voltage", np_.pin.v_nominal))
        if comp.sim_model == "battery:thevenin":
            return comp.rating("v_nominal"), comp.rating("v_max"), comp.rating("v_min")
        if comp.sim_model == "spice:VPULSE":
            v = max(inst.params.get("v1", comp.params.get("v1", 0)), inst.params.get("v2", comp.params.get("v2", 5)))
        return v, v, v

    def _build_rails(self) -> None:
        parent = {n.id: n.id for n in self.g.nets}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp:
                continue
            for a, b in conductive_pairs(comp, inst.params):
                na, nb = self.g.pin_to_net.get((inst.id, a)), self.g.pin_to_net.get((inst.id, b))
                if na and nb:
                    parent[find(nb)] = find(na)
        groups: dict[str, list[str]] = {}
        for n in self.g.nets:
            groups.setdefault(find(n.id), []).append(n.id)
        for i, (_, nets) in enumerate(groups.items()):
            rail = Rail(id=f"R{i + 1}", nets=nets)
            for nid in nets:
                self.net_rail[nid] = rail.id
                net = self._net(nid)
                rail.sources += net.of_type("power_out")
                if net.of_type("ground"):
                    rail.is_ground = True
            vs = [self._source_range(s) for s in rail.sources]
            if vs:
                rail.v_nom = vs[0][0]
                rail.v_max = max((v[1] for v in vs if v[1] is not None), default=None)
                rail.v_min = min((v[2] for v in vs if v[2] is not None), default=None)
            self.rails[rail.id] = rail

    def _net(self, nid: str) -> Net:
        return next(n for n in self.g.nets if n.id == nid)

    def rail_of(self, inst: str, pin: str) -> Optional[Rail]:
        nid = self.g.pin_to_net.get((inst, pin))
        return self.rails.get(self.net_rail.get(nid, "")) if nid else None

    def _connected(self, inst: str, pin: str) -> bool:
        net = self.g.net_of(inst, pin)
        return bool(net and len(net.pins) > 1)

    def _rail_voltage_of_pin(self, inst: str, pin: str) -> Optional[float]:
        r = self.rail_of(inst, pin)
        return r.v_nom if r and r.sources else None

    def _drive_level(self, np_: NetPin) -> Optional[float]:
        comp, pin = np_.component, np_.pin
        if pin.logic_v is not None and not comp.params.get("domains"):
            return pin.logic_v
        domains = comp.params.get("domains") or {}
        if pin.id in domains:
            return self._rail_voltage_of_pin(np_.instance.id, domains[pin.id])
        if comp.params.get("encoder_follows_vcc") or comp.params.get("follows_vcc"):
            vcc = next((p for p in comp.pins if p.type == "power_in"), None)
            if vcc:
                return self._rail_voltage_of_pin(np_.instance.id, vcc.id)
        return pin.logic_v

    def _vih(self, np_: NetPin) -> Optional[float]:
        comp = np_.component
        ref = comp.params.get("vih_ratio_of")
        if ref and np_.pin.type in DEDICATED_RECEIVERS:
            v = self._rail_voltage_of_pin(np_.instance.id, ref)
            if v is not None:
                return comp.params.get("vih_ratio", 0.7) * v
        return np_.pin.vih_min

    def _role(self, np_: NetPin, net: Net) -> str:
        """'driver', 'receiver' or 'unknown' for a logic pin on a net."""
        t = np_.pin.type
        if t in DEDICATED_DRIVERS:
            return "driver"
        if t in DEDICATED_RECEIVERS:
            return "receiver"
        if t == "digital_io":
            f = self.pin_funcs.get(np_.key)
            if f in OUTPUT_FUNCS:
                return "driver"
            if f in INPUT_FUNCS:
                return "receiver"
            others = [p for p in net.pins if p is not np_]
            if any(p.pin.type in DEDICATED_DRIVERS for p in others):
                return "receiver"
            if any(p.pin.type in DEDICATED_RECEIVERS for p in others):
                return "driver"
        return "unknown"

    # ------------------------------------------------------------- checks --
    def run(self) -> list[Issue]:
        for iid in self.g.unknown:
            self.add(code="E060", severity="error", title="Unknown component",
                     message=f"Instance {iid} references a component that is not in the library.",
                     connection=iid, refs=[iid], fix="Import the component definition or replace the instance.")
        for b in self.g.bad_wires:
            self.add(code="E061", severity="error", title="Invalid wire", message=b,
                     fix="Delete the wire or reconnect it to an existing pin.")
        self._build_rails()
        self._check_rails()
        self._check_power_pins()
        self._check_logic()
        self._check_buses()
        self._check_motors()
        self._check_misc()
        self.budget = self.power_budget()
        self._check_budget()
        return sort_issues(self.issues)

    def _check_rails(self) -> None:
        for rail in self.rails.values():
            volts = {}
            for s in rail.sources:
                v = self._source_range(s)[0]
                volts.setdefault(v, []).append(s)
            if rail.is_ground and rail.sources:
                for s in rail.sources:
                    self.add(code="E002", severity="critical", title="Supply shorted to ground",
                             message=f"{s.label} is a power output but its net is tied to ground. "
                                     "This is a dead short across the source.",
                             connection=f"{s.label} -> GND (rail {rail.id})", refs=[s.instance.id],
                             specs=[_pin_spec(s.component, s.pin, "v_nominal", self._source_range(s)[0])],
                             fix="Remove the wire between the supply output and ground.")
            if len(volts) > 1:
                labels = ", ".join(f"{s.label}={v} V" for v, ss in volts.items() for s in ss)
                self.add(code="E001", severity="critical", title="Two different supply rails shorted together",
                         message=f"Rail {rail.id} is driven by sources with different voltages ({labels}). "
                                 "Current will flow from the higher source into the lower one.",
                         connection=labels, refs=[s.instance.id for s in rail.sources],
                         fix="Separate the rails, or feed the lower rail through a regulator.")
            elif len(rail.sources) > 1:
                labels = ", ".join(s.label for s in rail.sources)
                self.add(code="E001b", severity="warning", title="Parallel supplies on one rail",
                         message=f"{labels} all drive the same rail. Regulator outputs and batteries "
                                 "are generally not designed to be paralleled.",
                         connection=labels, refs=[s.instance.id for s in rail.sources],
                         fix="Use a single source per rail or add ideal-diode ORing.")

    def _check_power_pins(self) -> None:
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp:
                continue
            power_pins = [p for p in comp.pins if p.type == "power_in"]
            gnd_pins = [p for p in comp.pins if p.type == "ground"]
            powered_any = False
            for p in power_pins:
                rail = self.rail_of(inst.id, p.id)
                label = f"{inst.id}.{p.id}"
                if rail is None or not self._connected(inst.id, p.id) or not rail.sources:
                    if p.required and not (rail and rail.is_ground):
                        alt = [q for q in power_pins if q is not p and self._connected(inst.id, q.id)]
                        if not alt:
                            self.add(code="E005", severity="error", title="Unpowered supply pin",
                                     message=f"{label} ({p.name}) has no voltage source on its net.",
                                     connection=label, refs=[inst.id],
                                     fix=f"Connect {p.name} to a rail within "
                                         f"{p.v_min if p.v_min is not None else '?'}-{p.v_max if p.v_max is not None else '?'} V.")
                    continue
                if rail.is_ground:
                    self.add(code="E002b", severity="critical", title="Supply pin tied to ground",
                             message=f"{label} is a supply input connected to ground.", connection=label,
                             refs=[inst.id], fix="Connect the supply pin to a positive rail.")
                    continue
                powered_any = True
                src = rail.sources[0]
                if p.v_max is not None and rail.v_max is not None and rail.v_max > p.v_max + 1e-6:
                    sev = "critical" if rail.v_max > 1.2 * p.v_max else "error"
                    self.add(code="E003", severity=sev, title="Supply over-voltage",
                             message=f"{label} accepts at most {p.v_max} V but rail {rail.name} can reach {rail.v_max} V.",
                             connection=f"{src.label} -> {label}", refs=[inst.id, src.instance.id],
                             specs=[_pin_spec(comp, p, "v_max", p.v_max),
                                    _pin_spec(src.component, src.pin, "rail v_max", rail.v_max)],
                             fix=f"Insert a regulator producing {p.v_min or ''}-{p.v_max} V, or choose a part rated for {rail.v_max} V.")
                elif p.v_min is not None and rail.v_nom is not None and rail.v_nom < p.v_min - 1e-6:
                    self.add(code="E004", severity="error", title="Supply under-voltage",
                             message=f"{label} needs at least {p.v_min} V but rail {rail.name} is {rail.v_nom} V nominal.",
                             connection=f"{src.label} -> {label}", refs=[inst.id, src.instance.id],
                             specs=[_pin_spec(comp, p, "v_min", p.v_min)],
                             fix="Use a higher-voltage rail or a boost converter.")
                elif p.v_min is not None and rail.v_min is not None and rail.v_min < p.v_min - 1e-6:
                    self.add(code="E004b", severity="warning", title="Supply drops below minimum near end of discharge",
                             message=f"{label} needs {p.v_min} V; the rail falls to {rail.v_min} V when the battery is depleted.",
                             connection=f"{src.label} -> {label}", refs=[inst.id, src.instance.id],
                             specs=[_pin_spec(comp, p, "v_min", p.v_min),
                                    _spec(src.component, "v_min", rail.v_min, "V")],
                             fix="Set the low-voltage cutoff above this level, or regulate the rail.")
            if (powered_any or any(self._connected(inst.id, p.id) for p in comp.pins if p.type not in ("ground",))) and gnd_pins:
                if not any(self._connected(inst.id, gp.id) for gp in gnd_pins) and power_pins:
                    self.add(code="E006", severity="error", title="Ground not connected",
                             message=f"{inst.id} has supply/signal connections but none of its ground pins are wired, "
                                     "so it has no return path or voltage reference.",
                             connection=f"{inst.id}.{gnd_pins[0].id}", refs=[inst.id],
                             fix=f"Wire {inst.id}.{gnd_pins[0].id} to the common ground.")

    def _ground_rail(self, inst_id: str) -> Optional[str]:
        comp = self.g.components.get(inst_id)
        if not comp:
            return None
        for p in comp.pins:
            if p.type == "ground" and self._connected(inst_id, p.id):
                r = self.rail_of(inst_id, p.id)
                return r.id if r else None
        return None

    def _check_logic(self) -> None:
        for net in self.g.nets:
            if len(net.pins) < 2:
                continue
            logic = [p for p in net.pins if p.pin.type in DEDICATED_DRIVERS | DEDICATED_RECEIVERS | {"digital_io", "i2c_sda", "i2c_scl"}]
            drivers = [p for p in logic if self._role(p, net) == "driver"]
            receivers = [p for p in logic if self._role(p, net) in ("receiver", "unknown")]
            push_pull = [d for d in drivers if d.pin.type == "digital_out"]
            if len(push_pull) > 1:
                self.add(code="E013", severity="error", title="Output contention",
                         message="Two push-pull outputs drive the same net; when they disagree they short each other.",
                         connection=" <-> ".join(d.label for d in push_pull) + f" (net {net.id})",
                         refs=[d.instance.id for d in push_pull], fix="Only one output may drive a net.")
            # Ground reference between components sharing a signal
            insts = {p.instance.id for p in logic}
            grounds = {i: self._ground_rail(i) for i in insts}
            known = {g for g in grounds.values() if g}
            if len(known) > 1:
                self.add(code="E007", severity="error", title="No common ground reference",
                         message="Components exchanging a signal on this net do not share a ground, so logic levels are undefined.",
                         connection=f"net {net.id}: " + ", ".join(p.label for p in logic),
                         refs=sorted(insts), fix="Connect the grounds of all communicating devices together.")
            for d in drivers:
                lvl = self._drive_level(d)
                for r in receivers:
                    if r.instance.id == d.instance.id:
                        continue
                    conn = f"{d.label} -> {r.label} (net {net.id})"
                    if lvl is None:
                        self.add(code="E019", severity="info", title="Output level unknown",
                                 message=f"Cannot determine the voltage that {d.label} drives; level checks skipped.",
                                 connection=conn, refs=[d.instance.id], fix="Specify logic_v for this pin or power the device.")
                        continue
                    amax = r.pin.v_abs_max
                    if amax is not None and lvl > amax + 1e-6:
                        self.add(code="E010", severity="critical" if lvl - amax > 1.0 else "error",
                                 title="Logic over-voltage (input not tolerant)",
                                 message=f"{d.label} drives {lvl} V high but {r.label} is rated to {amax} V absolute max"
                                         f"{' (not 5 V tolerant)' if r.pin.five_v_tolerant is False else ''}. "
                                         "This can damage the input.",
                                 connection=conn, refs=[d.instance.id, r.instance.id],
                                 specs=[_pin_spec(d.component, d.pin, "output high", lvl),
                                        _pin_spec(r.component, r.pin, "v_abs_max", amax)],
                                 fix="Add a level shifter (e.g. BSS138 module) or a resistive divider, "
                                     "or run the sending device from the lower rail.")
                        continue
                    vih = self._vih(r)
                    if vih is not None and lvl < vih - 1e-6:
                        self.add(code="E011", severity="warning", title="Logic high not guaranteed",
                                 message=f"{d.label} outputs {lvl} V but {r.label} needs at least {vih:.2f} V to read a "
                                         "logic HIGH. It may work on the bench and fail with temperature or tolerance.",
                                 connection=conn, refs=[d.instance.id, r.instance.id],
                                 specs=[_pin_spec(d.component, d.pin, "output high", lvl),
                                        _pin_spec(r.component, r.pin, "vih_min", round(vih, 3))],
                                 fix="Use a level shifter or power the receiver's logic supply from the lower rail.")
        # floating required inputs
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp:
                continue
            for p in comp.pins:
                if p.required and p.type in DEDICATED_RECEIVERS and not self._connected(inst.id, p.id):
                    self.add(code="E012", severity="warning", title="Floating input",
                             message=f"{inst.id}.{p.id} ({p.name}) is an input with no connection; it will float "
                                     "and read random values.",
                             connection=f"{inst.id}.{p.id}", refs=[inst.id],
                             fix="Connect it to a controller pin or tie it high/low through a resistor.")

    def _check_buses(self) -> None:
        for net in self.g.nets:
            types = [p.pin.type for p in net.pins]
            labels = ", ".join(p.label for p in net.pins)
            if types.count("uart_tx") > 1:
                self.add(code="E020", severity="error", title="UART TX connected to TX",
                         message="Two transmit pins are wired together; UART needs TX->RX crossover.",
                         connection=labels, refs=[p.instance.id for p in net.pins],
                         fix="Connect each TX to the other device's RX.")
            if types.count("uart_rx") > 1 and "uart_tx" not in types:
                self.add(code="E020b", severity="error", title="UART RX connected to RX",
                         message="Two receive pins are wired together with no transmitter.",
                         connection=labels, refs=[p.instance.id for p in net.pins], fix="Cross TX and RX.")
            if "i2c_sda" in types and "i2c_scl" in types:
                self.add(code="E021", severity="error", title="I2C SDA wired to SCL",
                         message="Data and clock lines are swapped or shorted.", connection=labels,
                         refs=[p.instance.id for p in net.pins], fix="Connect SDA to SDA and SCL to SCL.")
            if "can_h" in types and "can_l" in types:
                self.add(code="E022", severity="error", title="CAN_H shorted to CAN_L",
                         message="The differential CAN pair is shorted or swapped.", connection=labels,
                         refs=[p.instance.id for p in net.pins], fix="Connect CANH to CANH and CANL to CANL.")
            if "spi_mosi" in types and "spi_miso" in types:
                self.add(code="E023", severity="error", title="SPI MOSI wired to MISO",
                         message="A peripheral's data input and data output share a net.", connection=labels,
                         refs=[p.instance.id for p in net.pins], fix="MOSI goes controller->peripheral SI, MISO peripheral SO->controller.")
            # I2C pull-ups
            if any(t in ("i2c_sda", "i2c_scl") for t in types):
                has_res = any(p.component.id == "passive.resistor" for p in net.pins)
                pull_src = [p for p in net.pins if p.component.params.get("i2c_pullups_v")]
                if not has_res and not pull_src:
                    self.add(code="E025", severity="warning", title="I2C bus without pull-ups",
                             message="No pull-up resistor was found on this I2C line. I2C is open-drain and "
                                     "will not idle high without pull-ups (unless a module provides them).",
                             connection=labels, refs=[p.instance.id for p in net.pins],
                             fix="Add 4.7 kOhm pull-ups to the controller's logic rail (3.3 V for 3.3 V MCUs).")
                for ps in pull_src:
                    v = self._rail_voltage_of_pin(ps.instance.id, ps.component.params["i2c_pullups_v"])
                    for other in net.pins:
                        if other is ps or v is None:
                            continue
                        amax = other.pin.v_abs_max
                        if amax is not None and v > amax + 1e-6:
                            self.add(code="E026", severity="error", title="I2C pull-ups exceed input rating",
                                     message=f"{ps.instance.id}'s on-board pull-ups pull the bus to {v} V, above "
                                             f"{other.label}'s {amax} V limit.",
                                     connection=f"{ps.label} -> {other.label}", refs=[ps.instance.id, other.instance.id],
                                     fix="Power the module from the lower rail or use an I2C level shifter.")
            # controller capability
            for p in net.pins:
                need = PROTOCOL_CAP.get(p.pin.type)
                if not need:
                    continue
                for c in net.pins:
                    if c.pin.type != "digital_io" or not c.pin.capabilities or c.instance.id == p.instance.id:
                        continue
                    caps = c.pin.capabilities
                    has = need in caps
                    if need == "pwm" and "pwm" not in caps:
                        self.add(code="E024", severity="warning", title="Pin has no hardware PWM",
                                 message=f"{c.label} drives the PWM input {p.label} but has no hardware PWM; "
                                         "software PWM adds jitter and CPU load.",
                                 connection=f"{c.label} -> {p.label}", refs=[c.instance.id, p.instance.id],
                                 specs=[SpecRef(component=c.component.id, field=f"pin {c.pin.id}.capabilities",
                                                value=",".join(caps), source="datasheet", url=c.component.datasheet)],
                                 fix="Move the signal to a PWM-capable pin.")
                    elif need != "pwm" and not has:
                        sev = "warning" if need in ("i2c", "uart_rx", "uart_tx") else "error"
                        self.add(code="E024b", severity=sev, title="Interface not available on this pin",
                                 message=f"{p.label} is a {p.pin.type} signal but {c.label} has no '{need}' function "
                                         f"(capabilities: {', '.join(caps)}). Only bit-banged firmware could drive it.",
                                 connection=f"{c.label} -> {p.label}", refs=[c.instance.id, p.instance.id],
                                 fix=f"Use a pin that supports {need}.")

    def _check_motors(self) -> None:
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp or comp.sim_model != "motor:dc_brushed":
                continue
            drivers: list[NetPin] = []
            for mp in [p for p in comp.pins if p.type == "motor_in"]:
                net = self.g.net_of(inst.id, mp.id)
                others = [p for p in net.pins if p.instance.id != inst.id] if net else []
                if not others:
                    self.add(code="E034", severity="warning", title="Motor terminal unconnected",
                             message=f"{inst.id}.{mp.id} is not connected.", connection=f"{inst.id}.{mp.id}",
                             refs=[inst.id], fix="Connect both motor terminals to a driver channel.")
                    continue
                bad = [p for p in others if p.pin.type in ("digital_io", "digital_out", "power_out")]
                for b in bad:
                    self.add(code="E032", severity="critical" if b.pin.type != "power_out" else "warning",
                             title="Motor driven without a motor driver",
                             message=f"{inst.id}.{mp.id} connects directly to {b.label}. "
                                     + ("A GPIO pin can source only milliamps; the motor needs amps and its "
                                        "back-EMF will destroy the pin." if b.pin.type != "power_out"
                                        else "The motor can only run at full speed in one direction, with no control."),
                             connection=f"{b.label} -> {inst.id}.{mp.id}", refs=[inst.id, b.instance.id],
                             fix="Insert an H-bridge motor driver between the controller and the motor.")
                drivers += [p for p in others if p.pin.type == "motor_out"]
            if not drivers:
                continue
            drv = drivers[0]
            groups = {d.pin.group for d in drivers}
            if len(groups) > 1:
                self.add(code="E033", severity="error", title="Motor split across driver channels",
                         message=f"{inst.id}'s terminals go to different H-bridge channels ({', '.join(d.label for d in drivers)}).",
                         connection=", ".join(d.label for d in drivers), refs=[inst.id, drv.instance.id],
                         fix="Connect both terminals to OUTx1/OUTx2 of the same channel.")
            dcomp = drv.component
            i_stall = comp.rating("i_stall")
            i_cont = dcomp.rating("i_cont_per_channel")
            i_peak = dcomp.rating("i_peak_per_channel")
            conn = f"{drv.label} -> {inst.id} ({comp.name})"
            if i_stall is None or i_cont is None:
                self.add(code="E039", severity="info", title="Driver/motor current check skipped",
                         message="Stall current or driver rating is unknown.", connection=conn, refs=[inst.id],
                         fix="Enter the motor stall current and driver channel rating.")
            else:
                if i_peak is not None and i_stall > i_peak:
                    self.add(code="E030", severity="error", title="Motor stall current exceeds driver peak rating",
                             message=f"{comp.name} draws up to {i_stall} A at stall; {dcomp.name} survives "
                                     f"{i_peak} A peak per channel. A stalled wheel (obstacle, start-up) can destroy the driver.",
                             connection=conn, refs=[inst.id, drv.instance.id],
                             specs=[_spec(comp, "i_stall", i_stall, "A"), _spec(dcomp, "i_peak_per_channel", i_peak, "A")],
                             fix="Choose a driver rated above the stall current (e.g. Cytron MDD10A) or add current limiting.")
                elif i_stall > i_cont:
                    self.add(code="E030b", severity="warning", title="Stall current above driver continuous rating",
                             message=f"Stall ({i_stall} A) exceeds the continuous rating ({i_cont} A); prolonged stall will overheat the driver.",
                             connection=conn, refs=[inst.id, drv.instance.id],
                             specs=[_spec(comp, "i_stall", i_stall, "A"), _spec(dcomp, "i_cont_per_channel", i_cont, "A")],
                             fix="Enable stall detection in firmware or use a higher-rated driver.")
            vm_pin = next((p for p in dcomp.pins if p.type == "power_in" and p.id.startswith("VM")), None)
            v_rated = comp.rating("v_rated")
            if vm_pin and v_rated:
                rail = self.rail_of(drv.instance.id, vm_pin.id)
                if rail and rail.v_max:
                    if rail.v_max > 1.25 * v_rated:
                        self.add(code="E031", severity="warning", title="Motor over-volted",
                                 message=f"Driver supply reaches {rail.v_max} V; {comp.name} is rated {v_rated} V. "
                                         "Full PWM will overspeed and overheat the motor.",
                                 connection=conn, refs=[inst.id, drv.instance.id],
                                 specs=[_spec(comp, "v_rated", v_rated, "V")],
                                 fix=f"Limit the PWM duty to {v_rated / rail.v_max:.0%} in firmware or use a matching supply.")
                    elif rail.v_nom and rail.v_nom < 0.6 * v_rated:
                        self.add(code="E031b", severity="warning", title="Motor under-volted",
                                 message=f"Driver supply is {rail.v_nom} V; {comp.name} is rated {v_rated} V. Expect "
                                         f"about {rail.v_nom / v_rated:.0%} of rated speed and torque.",
                                 connection=conn, refs=[inst.id, drv.instance.id],
                                 fix="Use a supply closer to the motor rating.")

    def _check_misc(self) -> None:
        for net in self.g.nets:
            leds = [p for p in net.pins if p.component.id.startswith("led.") and p.pin.id == "A"]
            srcs = [p for p in net.pins if p.pin.type in ("power_out", "digital_io", "digital_out")]
            if leds and srcs:
                self.add(code="E050", severity="warning", title="LED without current-limiting resistor",
                         message=f"{leds[0].label} connects directly to {srcs[0].label}; LED current is limited only "
                                 "by the source and will exceed its rating.",
                         connection=f"{srcs[0].label} -> {leds[0].label}", refs=[leds[0].instance.id],
                         fix="Insert a series resistor: R = (V_source - V_f) / I_f, e.g. 150 Ohm for 5 V and 20 mA.")
            coils = [p for p in net.pins if p.component.id.startswith("relay.") and p.pin.id == "COIL+"]
            gpios = [p for p in net.pins if p.pin.type in ("digital_io", "digital_out")]
            for c in coils:
                for g in gpios:
                    coil_i = c.component.rating("coil_i")
                    self.add(code="E051", severity="error", title="GPIO overloaded by relay coil",
                             message=f"{g.label} drives the relay coil directly ({coil_i} A); GPIO limit is "
                                     f"{g.pin.i_max} A. The coil's inductive kick can also damage the pin.",
                             connection=f"{g.label} -> {c.label}", refs=[g.instance.id, c.instance.id],
                             specs=[_spec(c.component, "coil_i", coil_i, "A")],
                             fix="Drive the coil with an NPN/MOSFET and add a flyback diode (1N4007) across it.")

    # ------------------------------------------------------- power budget --
    def power_budget(self) -> dict:
        assumptions: list[str] = []
        for r in self.rails.values():
            r.load_typ = r.load_peak = 0.0
            r.loads = []

        def add_load(rail: Optional[Rail], who: str, typ: float, peak: float, note: str = ""):
            if rail is None or rail.is_ground:
                return
            rail.load_typ += typ
            rail.load_peak += peak
            rail.loads.append({"who": who, "typ_a": round(typ, 4), "peak_a": round(peak, 4), "note": note})

        regulators = []
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp:
                continue
            pins_in = [p for p in comp.pins if p.type == "power_in" and self._connected(inst.id, p.id)]
            if comp.sim_model == "behavioral:regulator":
                regulators.append((inst, comp))
            i_typ = comp.rating("i_typ")
            if i_typ is not None and pins_in:
                src = comp.ratings["i_typ"].source
                add_load(self.rail_of(inst.id, pins_in[0].id), inst.id, i_typ, comp.rating("i_peak") or i_typ,
                         "" if src == "datasheet" else f"{src}: {comp.ratings['i_typ'].note}")
            elif pins_in and comp.sim_model not in ("behavioral:regulator", "driver:hbridge"):
                assumptions.append(f"{inst.id}: supply current unknown — not included in budget")
        # motors -> driver VM
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp or comp.sim_model != "motor:dc_brushed":
                continue
            net = self.g.net_of(inst.id, "M+")
            drv = next((p for p in (net.pins if net else []) if p.pin.type == "motor_out"), None)
            if not drv:
                continue
            vm = next((p for p in drv.component.pins if p.type == "power_in" and p.id.startswith("VM")), None)
            i_stall = comp.rating("i_stall") or 0.0
            typ = MOTOR_TYPICAL_FRACTION_OF_STALL * i_stall
            add_load(self.rail_of(drv.instance.id, vm.id) if vm else None, inst.id, typ, i_stall,
                     f"assumption: running = {MOTOR_TYPICAL_FRACTION_OF_STALL:.0%} of stall; peak = stall")
        # propagate regulator outputs to inputs (repeat for chained regulators)
        done: set[str] = set()
        for _ in range(len(regulators) + 1):
            for inst, comp in regulators:
                if inst.id in done:
                    continue
                out_rail = self.rail_of(inst.id, "VOUT")
                in_rail = self.rail_of(inst.id, "VIN")
                # wait until downstream regulators feeding this output are done
                if any(o.id not in done and self.rail_of(o.id, "VIN") is out_rail for o, _ in regulators if o is not inst):
                    continue
                vout = comp.pins[[p.id for p in comp.pins].index("VOUT")].v_nominal or 0
                iq = comp.rating("i_typ") or 0.0
                if out_rail is None or in_rail is None:
                    done.add(inst.id)
                    continue
                if comp.params.get("topology") == "switching" and in_rail.v_nom:
                    eff = comp.rating("efficiency") or 0.85
                    k = vout / (eff * in_rail.v_nom)
                    add_load(in_rail, inst.id, out_rail.load_typ * k + iq, out_rail.load_peak * k + iq,
                             f"switching, efficiency {eff:.0%} ({comp.ratings.get('efficiency').source if comp.ratings.get('efficiency') else 'assumption'})")
                else:
                    add_load(in_rail, inst.id, out_rail.load_typ + iq, out_rail.load_peak + iq, "linear: I_in = I_out + Iq")
                    if in_rail.v_nom:
                        pd = (in_rail.v_nom - vout) * out_rail.load_typ
                        if pd > 1.0:
                            self.add(code="E044", severity="warning", title="Linear regulator dissipation",
                                     message=f"{inst.id} dissipates about {pd:.2f} W ((Vin-Vout) x Iload); "
                                             "a TO-220 without heatsink overheats around 1-2 W.",
                                     connection=f"{inst.id} {in_rail.v_nom} V -> {vout} V @ {out_rail.load_typ:.2f} A",
                                     refs=[inst.id], domain="power", fix="Use a buck converter or add a heatsink.")
                done.add(inst.id)
        rails = []
        for r in self.rails.values():
            if r.is_ground or not (r.sources or r.loads):
                continue
            cap = None
            for s in r.sources:
                cap = s.pin.i_max if s.pin.i_max is not None else cap
            rails.append({"rail": r.id, "name": r.name, "nets": r.nets, "v_nominal": r.v_nom, "v_min": r.v_min,
                          "v_max": r.v_max, "source": r.sources[0].label if r.sources else None, "capacity_a": cap,
                          "load_typ_a": round(r.load_typ, 4), "load_peak_a": round(r.load_peak, 4),
                          "power_typ_w": round(r.load_typ * (r.v_nom or 0), 3), "loads": r.loads})
        battery = None
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if comp and comp.sim_model == "battery:thevenin":
                r = self.rail_of(inst.id, "+")
                if r:
                    cap_ah = comp.rating("capacity_ah") or 0
                    p = r.load_typ * (r.v_nom or 0)
                    battery = {"instance": inst.id, "v_nominal": r.v_nom, "current_typ_a": round(r.load_typ, 3),
                               "current_peak_a": round(r.load_peak, 3), "power_typ_w": round(p, 2),
                               "runtime_h_estimate": round(cap_ah / r.load_typ, 2) if r.load_typ > 0 else None,
                               "max_discharge_a": comp.rating("max_discharge_a"),
                               "note": "Analytical estimate from typical loads (not a circuit-solver result)."}
        return {"rails": rails, "battery": battery, "assumptions": assumptions, "kind": "analytical_estimate"}

    def _check_budget(self) -> None:
        for r in self.budget["rails"]:
            cap = r["capacity_a"]
            if cap is not None and r["load_typ_a"] > cap:
                self.add(code="E040", severity="error", title="Rail overloaded", domain="power",
                         message=f"{r['name']} supplies {cap} A but typical load is {r['load_typ_a']:.2f} A.",
                         connection=r["source"], refs=[l["who"] for l in r["loads"]],
                         fix="Use a higher-current source or move loads to another rail.")
            elif cap is not None and r["load_peak_a"] > cap:
                self.add(code="E040b", severity="warning", title="Rail peak load exceeds source rating", domain="power",
                         message=f"{r['name']} peak load {r['load_peak_a']:.2f} A > {cap} A capability.",
                         connection=r["source"], refs=[l["who"] for l in r["loads"]],
                         fix="Check that peaks are short, add bulk capacitance, or upsize the source.")
        b = self.budget["battery"]
        if b and b["max_discharge_a"]:
            if b["current_peak_a"] > b["max_discharge_a"]:
                sev = "error" if b["current_typ_a"] > b["max_discharge_a"] else "warning"
                self.add(code="E041", severity=sev, title="Battery discharge limit exceeded", domain="power",
                         message=f"Peak draw {b['current_peak_a']:.1f} A (all motors stalled) exceeds the battery's "
                                 f"{b['max_discharge_a']} A rating; the BMS may cut out.",
                         connection=b["instance"], refs=[b["instance"]],
                         fix="Choose a pack with a higher discharge rating or limit motor current.")
        # fuses
        for inst in self.circuit.instances:
            comp = self.g.components.get(inst.id)
            if not comp:
                continue
            rail = self.rail_of(inst.id, comp.pins[0].id) if comp.pins else None
            rail_info = next((r for r in self.budget["rails"] if rail and r["rail"] == rail.id), None)
            if comp.sim_model == "protection:fuse_i2t" and rail_info:
                rating = inst.params.get("rating_a", comp.params.get("rating_a"))
                if rating is not None and rail_info["load_typ_a"] > rating:
                    self.add(code="E042", severity="error", title="Fuse undersized", domain="power",
                             message=f"{inst.id} is {rating} A but the typical load through it is {rail_info['load_typ_a']:.1f} A.",
                             connection=inst.id, refs=[inst.id], fix="Choose a fuse ~1.25-1.5x the continuous load.")
            if comp.category.value == "connectors" and rail_info:
                i_cont = comp.rating("i_cont")
                if i_cont is None:
                    self.add(code="E043b", severity="info", title="Connector rating unknown", domain="power",
                             message=f"{inst.id} ({comp.name}) carries {rail_info['load_typ_a']:.1f} A but has no rating.",
                             connection=inst.id, refs=[inst.id], fix="Enter the connector's current rating from its datasheet.")
                elif rail_info["load_typ_a"] > i_cont:
                    self.add(code="E043", severity="error", title="Connector current rating exceeded", domain="power",
                             message=f"{inst.id} is rated {i_cont} A; load is {rail_info['load_typ_a']:.1f} A.",
                             connection=inst.id, refs=[inst.id], fix="Use a higher-rated connector (e.g. XT60).")
        if self.budget["battery"] and not any(
                (self.g.components.get(i.id) and self.g.components[i.id].sim_model == "protection:fuse_i2t")
                for i in self.circuit.instances):
            self.add(code="E045", severity="info", title="No fuse on battery output", domain="power",
                     message="Battery-powered designs should fuse the main supply close to the battery.",
                     connection=self.budget["battery"]["instance"], refs=[self.budget["battery"]["instance"]],
                     fix="Add a blade fuse sized for the continuous load.")


def check_circuit(circuit: Circuit, registry: Registry, firmware: Optional[Firmware] = None,
                  controller_ref: Optional[str] = None) -> dict:
    eng = CompatibilityEngine(circuit, registry, firmware, controller_ref)
    issues = eng.run()
    nets = [{"id": n.id, "name": n.name, "pins": [p.label for p in n.pins],
             "rail": eng.net_rail.get(n.id), "voltage": eng.rails[eng.net_rail[n.id]].v_nom
             if eng.net_rail.get(n.id) else None} for n in eng.g.nets if len(n.pins) > 1]
    return {"issues": [i.model_dump() for i in issues], "nets": nets, "power_budget": eng.budget}
