"""Analytical electro-mechanical models used by the co-simulator.

These are engineering estimates (labelled `analytical_model` in telemetry),
not circuit-solver results and not hardware measurements. Thermal and battery
outputs are NOT safety validation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ...schemas.library import Component

# Open-circuit voltage per cell vs state of charge (0..1). Representative
# curves; replace with measured curves for a specific cell.
OCV_CURVES = {
    "lipo": ([0.0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0], [3.30, 3.55, 3.65, 3.72, 3.80, 3.87, 4.00, 4.08, 4.20]),
    "liion": ([0.0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0], [3.00, 3.30, 3.45, 3.55, 3.68, 3.80, 3.95, 4.05, 4.20]),
    "lifepo4": ([0.0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0], [2.60, 3.00, 3.15, 3.22, 3.27, 3.30, 3.33, 3.36, 3.60]),
}


@dataclass
class Battery:
    """Thevenin battery: V = OCV(SoC) - I*R0 - V_rc, with one RC pair for polarisation."""
    chemistry: str
    cells_series: int
    capacity_ah: float
    r0: float
    r1: float = 0.01
    c1: float = 2000.0
    soc: float = 1.0
    max_discharge_a: float | None = None
    v_rc: float = 0.0
    ah_used: float = 0.0
    energy_wh: float = 0.0

    @classmethod
    def from_component(cls, comp: Component, soc: float = 1.0, params: dict | None = None) -> "Battery":
        p = {**comp.params, **(params or {})}
        return cls(chemistry=p.get("chemistry", "liion"), cells_series=int(p.get("cells_series", 1)),
                   capacity_ah=float(p.get("capacity_ah", comp.rating("capacity_ah") or 1.0)),
                   r0=float(p.get("r_internal", 0.05)), soc=soc, max_discharge_a=comp.rating("max_discharge_a"),
                   r1=float(p.get("r_internal", 0.05)) * 0.3)

    def ocv(self) -> float:
        xs, ys = OCV_CURVES.get(self.chemistry, OCV_CURVES["liion"])
        return float(np.interp(self.soc, xs, ys)) * self.cells_series

    def terminal_voltage(self, current: float) -> float:
        return max(0.0, self.ocv() - current * self.r0 - self.v_rc)

    def step(self, current: float, dt: float) -> float:
        """Advance by dt with discharge current (A, negative = charging). Returns terminal voltage."""
        v = self.terminal_voltage(current)
        tau = self.r1 * self.c1
        self.v_rc += dt * (current * self.r1 - self.v_rc) / tau
        self.soc = min(1.0, max(0.0, self.soc - current * dt / (3600.0 * self.capacity_ah)))
        self.ah_used += current * dt / 3600.0
        self.energy_wh += v * current * dt / 3600.0
        return v


@dataclass
class DCMotor:
    """Brushed DC (gear)motor referred to the output shaft.

    Derived from datasheet points: R = V/I_stall, Kt = T_stall/I_stall,
    Ke = (V - R*I0)/w0. Viscous+Coulomb friction reproduces the no-load current.
    Electrical dynamics (L) are neglected: the electrical time constant (~ms)
    is shorter than the controller period.
    """
    v_rated: float
    r: float
    kt: float
    ke: float
    friction_torque: float
    inertia: float = 2e-5
    temp_c: float = 25.0
    r_th: float = 8.0  # K/W winding to ambient (assumption unless specified)
    c_th: float = 60.0  # J/K
    current: float = 0.0
    torque: float = 0.0

    @classmethod
    def from_component(cls, comp: Component) -> "DCMotor":
        v = comp.rating("v_rated")
        i_stall = comp.rating("i_stall")
        t_stall = comp.rating("stall_torque")
        rpm0 = comp.rating("noload_rpm")
        i0 = comp.rating("i_noload") or 0.0
        if None in (v, i_stall, t_stall, rpm0):
            raise ValueError(f"{comp.id}: v_rated, i_stall, stall_torque and noload_rpm are required for the DC motor model")
        r = v / i_stall
        kt = t_stall / i_stall
        w0 = rpm0 * 2 * math.pi / 60.0
        ke = (v - r * i0) / w0
        return cls(v_rated=v, r=r, kt=kt, ke=ke, friction_torque=kt * i0,
                   inertia=float(comp.params.get("rotor_inertia", 3e-6)) * float(comp.params.get("gear_ratio", 1.0)) ** 2,
                   r_th=float(comp.params.get("thermal_resistance", 8.0)),
                   c_th=float(comp.params.get("thermal_capacity", 60.0)))

    def compute(self, v_applied: float, omega: float, i_limit: float | None = None) -> tuple[float, float]:
        """Return (current, shaft torque) for a terminal voltage and output speed (rad/s)."""
        r_hot = self.r * (1 + 0.00393 * (self.temp_c - 25.0))  # copper tempco
        i = (v_applied - self.ke * omega) / r_hot
        if i_limit is not None:
            i = max(-i_limit, min(i_limit, i))
        fr = self.friction_torque * math.tanh(omega / 0.5)
        self.current = i
        self.torque = self.kt * i - fr
        return i, self.torque

    def thermal_step(self, dt: float, ambient: float) -> None:
        p = self.current ** 2 * self.r
        self.temp_c += dt * (p - (self.temp_c - ambient) / self.r_th) / self.c_th


@dataclass
class HBridge:
    """H-bridge channel: PWM duty -> average terminal voltage, with drop and current limit."""
    r_ds_on: float = 0.5
    v_drop: float = 0.0  # bipolar drivers (L298) have a fixed drop
    i_cont: float | None = None
    i_peak: float | None = None
    over_current_time: float = 0.0
    tripped: bool = False

    @classmethod
    def from_component(cls, comp: Component) -> "HBridge":
        return cls(r_ds_on=float(comp.params.get("r_ds_on", 0.5)), v_drop=float(comp.params.get("v_drop", 0.0)),
                   i_cont=comp.rating("i_cont_per_channel"), i_peak=comp.rating("i_peak_per_channel"))

    def output_voltage(self, duty: float, v_bus: float, current: float) -> float:
        if self.tripped:
            return 0.0
        duty = max(-1.0, min(1.0, duty))
        v = duty * max(0.0, v_bus - self.v_drop) - 2 * self.r_ds_on * current
        return v

    def check(self, current: float, dt: float) -> str | None:
        """Thermal-shutdown style protection: trip after 0.5 s above peak rating."""
        if self.i_peak is None:
            return None
        if abs(current) > self.i_peak:
            self.over_current_time += dt
            if self.over_current_time > 0.5 and not self.tripped:
                self.tripped = True
                return "driver_overcurrent_shutdown"
        else:
            self.over_current_time = max(0.0, self.over_current_time - dt)
        return None


@dataclass
class Fuse:
    """I^2*t fuse: melts when integrated (I^2 - In^2)*t exceeds the melting integral."""
    rating_a: float
    i2t_melt: float = field(default=0.0)
    accum: float = 0.0
    blown: bool = False

    def __post_init__(self):
        if not self.i2t_melt:
            # typical slow-blow automotive fuse ~ 10*In^2 at 2x rating over ~2.5 s (assumption)
            self.i2t_melt = 10.0 * self.rating_a ** 2

    def step(self, current: float, dt: float) -> bool:
        if self.blown:
            return True
        self.accum = max(0.0, self.accum + (current ** 2 - (1.1 * self.rating_a) ** 2) * dt)
        if self.accum > self.i2t_melt:
            self.blown = True
        return self.blown


def wheel_speed_limit(motor: DCMotor, v_bus: float, wheel_radius: float, gear_ratio: float = 1.0) -> float:
    """Theoretical top speed (m/s) at full voltage and zero load."""
    w0 = v_bus / motor.ke
    return w0 / gear_ratio * wheel_radius
