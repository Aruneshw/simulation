"""Built-in component definitions.

Ratings marked source="datasheet" were taken from the referenced manufacturer
documentation; anything not confirmed is marked "assumption" with a note, or
left unknown. Generic parts (resistor, wheel, battery pack) are parameterised
and carry user-editable values instead of a part number.
"""
from __future__ import annotations

from ..schemas.library import Category as C
from ..schemas.library import Component, Pin, Provenance, Rated
from ..schemas.library import SupportStatus as S


def R(value, unit, source="datasheet", note=""):
    return Rated(value=value, unit=unit, source=source, note=note)


def pw(pid, name, vmin=None, vmax=None, required=True, **kw):
    return Pin(id=pid, name=name, type="power_in", v_min=vmin, v_max=vmax, required=required, **kw)


def po(pid, name, v, imax=None, **kw):
    return Pin(id=pid, name=name, type="power_out", v_nominal=v, i_max=imax, **kw)


def gnd(pid="GND", name="GND"):
    return Pin(id=pid, name=name, type="ground", required=True)


def io(pid, name, logic, abs_max, vih=None, caps=(), ft=False, imax=None, **kw):
    return Pin(id=pid, name=name, type=kw.pop("type", "digital_io"), logic_v=logic, v_abs_max=abs_max,
               vih_min=vih, capabilities=list(caps), five_v_tolerant=ft, i_max=imax, **kw)


def din(pid, name, vih, abs_max, required=False, **kw):
    return Pin(id=pid, name=name, type=kw.pop("type", "digital_in"), vih_min=vih, v_abs_max=abs_max,
               required=required, **kw)


def dout(pid, name, logic, **kw):
    return Pin(id=pid, name=name, type=kw.pop("type", "digital_out"), logic_v=logic, **kw)


def passive(pid, name, node):
    return Pin(id=pid, name=name, type="passive", spice_node=node)


VERIFIED = Provenance(source="builtin_verified", verified=True)


def DS(url, notes=""):
    return Provenance(source="datasheet", url=url, verified=True, notes=notes)


COMMUNITY = Provenance(source="community", verified=False,
                       notes="No single manufacturer datasheet; values are commonly published module figures.")


def _passives() -> list[Component]:
    return [
        Component(id="passive.resistor", name="Resistor", category=C.passives, symbol="resistor",
                  tags=["resistor", "passive", "spice"], footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
                  pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"resistance": 1000.0, "power_rating_w": 0.25}, sim_model="spice:R",
                  support_status=S.fully_modeled, provenance=VERIFIED,
                  description="Ideal resistor; value and power rating are instance parameters."),
        Component(id="passive.capacitor", name="Capacitor", category=C.passives, symbol="capacitor",
                  tags=["capacitor", "passive", "spice"], footprint="Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
                  pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"capacitance": 1e-6, "voltage_rating": 25.0}, sim_model="spice:C",
                  support_status=S.fully_modeled, provenance=VERIFIED),
        Component(id="passive.inductor", name="Inductor", category=C.passives, symbol="inductor",
                  tags=["inductor", "passive", "spice"], pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"inductance": 1e-3}, sim_model="spice:L", support_status=S.fully_modeled,
                  provenance=VERIFIED),
        Component(id="diode.1n4148", name="1N4148 small-signal diode", category=C.passives, symbol="diode",
                  manufacturer="Vishay", part_number="1N4148", tags=["diode", "spice"],
                  footprint="Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal",
                  pins=[passive("A", "Anode", 0), passive("K", "Cathode", 1)],
                  ratings={"v_rrm": R(100, "V"), "i_f_avg": R(0.15, "A")},
                  params={"is": 2.52e-9, "n": 1.752}, sim_model="spice:D", support_status=S.fully_modeled,
                  datasheet="https://www.vishay.com/docs/81857/1n4148.pdf",
                  provenance=DS("https://www.vishay.com/docs/81857/1n4148.pdf",
                                "SPICE Is/N from widely used public model.")),
        Component(id="diode.1n4007", name="1N4007 rectifier diode", category=C.passives, symbol="diode",
                  manufacturer="Vishay", part_number="1N4007", tags=["diode", "rectifier", "reverse-polarity"],
                  pins=[passive("A", "Anode", 0), passive("K", "Cathode", 1)],
                  ratings={"v_rrm": R(1000, "V"), "i_f_avg": R(1.0, "A")},
                  params={"is": 7.0e-9, "n": 1.8}, sim_model="spice:D", support_status=S.fully_modeled,
                  datasheet="https://www.vishay.com/docs/88503/1n4001.pdf",
                  provenance=DS("https://www.vishay.com/docs/88503/1n4001.pdf",
                                "SPICE Is/N are approximate fit values (assumption).")),
        Component(id="led.generic_red", name="LED (red, 5 mm)", category=C.passives, symbol="led",
                  tags=["led", "indicator"], pins=[passive("A", "Anode", 0), passive("K", "Cathode", 1)],
                  ratings={"v_f": R(2.0, "V", "assumption", "typical red LED"),
                           "i_f_max": R(0.020, "A", "assumption", "typical 5 mm LED continuous rating")},
                  params={"is": 1e-19, "n": 1.9}, sim_model="spice:D", support_status=S.fully_modeled,
                  provenance=Provenance(source="builtin_verified", notes="Generic LED; use a part-specific model for accuracy.")),
        Component(id="source.dc_voltage", name="DC voltage source", category=C.power_electronics, symbol="vsource",
                  tags=["source", "spice", "supply"],
                  pins=[Pin(id="+", name="+", type="power_out", spice_node=0), Pin(id="-", name="-", type="ground", spice_node=1)],
                  params={"voltage": 5.0}, sim_model="spice:V", support_status=S.fully_modeled, provenance=VERIFIED),
        Component(id="source.dc_current", name="DC current source", category=C.power_electronics, symbol="isource",
                  tags=["source", "spice"], pins=[passive("+", "+", 0), passive("-", "-", 1)],
                  params={"current": 0.01}, sim_model="spice:I", support_status=S.fully_modeled, provenance=VERIFIED),
        Component(id="source.pulse_voltage", name="Pulse / PWM voltage source", category=C.power_electronics, symbol="vsource",
                  tags=["source", "pwm", "spice"],
                  pins=[Pin(id="+", name="+", type="power_out", spice_node=0), Pin(id="-", name="-", type="ground", spice_node=1)],
                  params={"v1": 0.0, "v2": 5.0, "period": 1e-3, "duty": 0.5}, sim_model="spice:VPULSE",
                  support_status=S.fully_modeled, provenance=VERIFIED),
        Component(id="ground", name="Ground reference", category=C.passives, symbol="ground",
                  tags=["ground", "reference"], pins=[gnd("GND")], sim_model="spice:GND",
                  support_status=S.fully_modeled, provenance=VERIFIED),
        Component(id="switch.spst", name="SPST switch", category=C.protection_switching, symbol="switch",
                  tags=["switch"], pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"closed": True, "r_on": 0.01, "r_off": 1e9}, sim_model="spice:SW",
                  support_status=S.fully_modeled, provenance=VERIFIED),
    ]


def _semis() -> list[Component]:
    return [
        Component(id="bjt.2n2222a", name="2N2222A NPN transistor", category=C.analog_ics, symbol="npn",
                  manufacturer="onsemi", part_number="P2N2222A", tags=["bjt", "npn", "transistor"],
                  pins=[passive("C", "Collector", 0), passive("B", "Base", 1), passive("E", "Emitter", 2)],
                  ratings={"v_ceo": R(40, "V"), "i_c_max": R(0.6, "A")},
                  sim_model=None, support_status=S.schematic_only,
                  datasheet="https://www.onsemi.com/pdf/datasheet/p2n2222a-d.pdf",
                  provenance=DS("https://www.onsemi.com/pdf/datasheet/p2n2222a-d.pdf",
                                "Built-in MNA solver has no BJT model; export to ngspice for transistor-level simulation.")),
        Component(id="mosfet.irlz44n", name="IRLZ44N logic-level N-MOSFET", category=C.power_electronics, symbol="nmos",
                  manufacturer="Infineon", part_number="IRLZ44NPBF", tags=["mosfet", "switch", "logic-level"],
                  pins=[passive("G", "Gate", 0), passive("D", "Drain", 1), passive("S", "Source", 2)],
                  ratings={"v_ds": R(55, "V"), "i_d": R(47, "A", note="Tc=25C, package/thermal limited in practice"),
                           "v_gs_th_max": R(2.0, "V")},
                  support_status=S.schematic_only,
                  provenance=Provenance(source="datasheet", verified=False,
                                        notes="Ratings from Infineon IRLZ44N datasheet; confirm before use.")),
        Component(id="opamp.lm358", name="LM358 dual op-amp", category=C.analog_ics, symbol="opamp",
                  manufacturer="Texas Instruments", part_number="LM358", tags=["opamp", "analog"],
                  pins=[pw("VCC", "V+", 3.0, 32.0), gnd("GND"), Pin(id="IN+", name="IN+", type="analog_in"),
                        Pin(id="IN-", name="IN-", type="analog_in"), Pin(id="OUT", name="OUT", type="analog_out")],
                  ratings={"i_typ": R(0.0007, "A", note="quiescent, both amplifiers")},
                  sim_model="behavioral:opamp_ideal", support_status=S.behavioral,
                  datasheet="https://www.ti.com/lit/ds/symlink/lm358.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/lm358.pdf")),
        Component(id="logic.sn74hc08", name="SN74HC08 quad AND gate", category=C.digital_ics, symbol="ic",
                  manufacturer="Texas Instruments", part_number="SN74HC08", tags=["logic", "and", "hc"],
                  pins=[pw("VCC", "VCC", 2.0, 6.0), gnd(), din("1A", "1A", 3.15, 7.0, required=True), din("1B", "1B", 3.15, 7.0, required=True),
                        dout("1Y", "1Y", 5.0)],
                  ratings={"i_typ": R(0.00002, "A")},
                  compatibility=["VIH min is 3.15 V at VCC=4.5 V — 3.3 V logic will not reliably drive a 5 V HC input."],
                  sim_model="behavioral:logic_and", support_status=S.behavioral,
                  datasheet="https://www.ti.com/lit/ds/symlink/sn74hc08.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/sn74hc08.pdf")),
        Component(id="level.bss138_4ch", name="Bi-directional logic level converter (BSS138, 4 ch)",
                  category=C.digital_ics, symbol="ic", manufacturer="SparkFun", part_number="BOB-12009",
                  tags=["level shifter", "3.3V", "5V"],
                  pins=[pw("LV", "LV", 1.8, 3.6), pw("HV", "HV", 3.0, 5.5), gnd(),
                        *[pin for k in range(1, 5) for pin in (io(f"LV{k}", f"LV{k}", 3.3, 3.6, 2.0),
                                                              io(f"HV{k}", f"HV{k}", 5.0, 5.5, 3.0))]],
                  params={"domains": {**{f"LV{k}": "LV" for k in range(1, 5)}, **{f"HV{k}": "HV" for k in range(1, 5)}},
                          "passthrough": [[f"LV{k}", f"HV{k}"] for k in range(1, 5)]},
                  sim_model="behavioral:level_shifter", support_status=S.behavioral,
                  datasheet="https://www.sparkfun.com/products/12009",
                  provenance=Provenance(source="manufacturer", url="https://www.sparkfun.com/products/12009",
                                        verified=False, notes="Logic levels follow the LV/HV supplies.")),
    ]


def _regulators() -> list[Component]:
    return [
        Component(id="reg.lm7805", name="LM7805 5 V linear regulator", category=C.power_electronics, symbol="regulator",
                  manufacturer="Texas Instruments", part_number="LM340T-5.0 / LM7805",
                  tags=["regulator", "linear", "5V"],
                  pins=[pw("VIN", "IN", 7.0, 35.0), gnd(), po("VOUT", "OUT", 5.0, 1.5)],
                  ratings={"i_out_max": R(1.5, "A"), "dropout": R(2.0, "V"), "i_typ": R(0.008, "A", note="quiescent")},
                  params={"topology": "linear"}, sim_model="behavioral:regulator", support_status=S.simulation_supported,
                  datasheet="https://www.ti.com/lit/ds/symlink/lm340.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/lm340.pdf",
                                "Dissipation = (Vin-Vout)*Iout; check heatsinking.")),
        Component(id="reg.ams1117_33", name="AMS1117-3.3 LDO", category=C.power_electronics, symbol="regulator",
                  manufacturer="Advanced Monolithic Systems", part_number="AMS1117-3.3",
                  tags=["regulator", "ldo", "3.3V"],
                  pins=[pw("VIN", "IN", 4.5, 15.0), gnd(), po("VOUT", "OUT", 3.3, 1.0)],
                  ratings={"i_out_max": R(1.0, "A"), "dropout": R(1.1, "V"), "i_typ": R(0.005, "A")},
                  params={"topology": "linear"}, sim_model="behavioral:regulator", support_status=S.simulation_supported,
                  datasheet="http://www.advanced-monolithic.com/pdf/ds1117.pdf",
                  provenance=DS("http://www.advanced-monolithic.com/pdf/ds1117.pdf")),
        Component(id="reg.lm2596_5v", name="LM2596 buck converter module (5 V)", category=C.power_electronics,
                  symbol="regulator", manufacturer="Texas Instruments (IC)", part_number="LM2596S-5.0",
                  tags=["regulator", "buck", "dc-dc", "5V"],
                  pins=[pw("VIN", "IN", 7.0, 40.0), gnd(), po("VOUT", "OUT", 5.0, 3.0)],
                  ratings={"i_out_max": R(3.0, "A"), "efficiency": R(0.8, "", "assumption", "typical at 12V->5V, 2A"),
                           "i_typ": R(0.005, "A")},
                  params={"topology": "switching"}, sim_model="behavioral:regulator", support_status=S.simulation_supported,
                  datasheet="https://www.ti.com/lit/ds/symlink/lm2596.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/lm2596.pdf",
                                "Module thermal limits are usually below the IC's 3 A rating.")),
    ]


def _batteries() -> list[Component]:
    def pack(cid, name, chem, cells_s, cell_nom, cell_max, cell_min, ah, max_a, r_int, tags, source="assumption", note="", url=None):
        return Component(
            id=cid, name=name, category=C.batteries, symbol="battery", tags=["battery", chem, *tags],
            pins=[po("+", "+", round(cells_s * cell_nom, 2), max_a), gnd("-", "-")],
            ratings={"v_nominal": R(round(cells_s * cell_nom, 2), "V", source, note),
                     "v_max": R(round(cells_s * cell_max, 2), "V", source, note),
                     "v_min": R(round(cells_s * cell_min, 2), "V", source, note),
                     "capacity_ah": R(ah, "Ah", source, note),
                     "max_discharge_a": R(max_a, "A", source, note)},
            params={"chemistry": chem, "cells_series": cells_s, "r_internal": r_int, "capacity_ah": ah},
            sim_model="battery:thevenin", support_status=S.simulation_supported, datasheet=url,
            provenance=Provenance(source="datasheet" if source == "datasheet" else "builtin_verified",
                                  url=url, verified=source == "datasheet",
                                  notes=note or "Generic pack; edit to match your cells."))
    return [
        pack("battery.lipo_3s_2200", "LiPo 3S 2200 mAh (generic)", "lipo", 3, 3.7, 4.2, 3.3, 2.2, 44.0, 0.03,
             ["3S", "11.1V"], note="Generic 20C pack; real ratings vary by vendor."),
        pack("battery.lifepo4_4s_20ah", "LiFePO4 4S 20 Ah (generic)", "lifepo4", 4, 3.2, 3.65, 2.5, 20.0, 20.0, 0.02,
             ["4S", "12.8V"], note="Generic 1C BMS-limited pack."),
        pack("battery.liion_6s2p_25r", "Li-ion 6S2P pack (Samsung INR18650-25R)", "liion", 6, 3.6, 4.2, 2.5, 5.0, 40.0, 0.05,
             ["6S", "22.2V", "18650"], source="datasheet",
             note="Cell: 2500 mAh, 20 A continuous per cell (Samsung SDI spec). Pack resistance is an estimate.",
             url="https://www.samsungsdi.com/"),
        pack("battery.liion_7s4p_24v", "Li-ion 7S4P 24 V pack (generic)", "liion", 7, 3.6, 4.2, 3.0, 10.0, 15.0, 0.08,
             ["7S", "24V"], note="Generic AMR pack; BMS limit assumed 15 A."),
        Component(id="supply.bench", name="Bench power supply", category=C.power_electronics, symbol="vsource",
                  tags=["supply", "lab"], pins=[po("+", "+", 12.0, 5.0), gnd("-", "-")],
                  params={"voltage": 12.0, "current_limit": 5.0}, sim_model="spice:V",
                  support_status=S.simulation_supported, provenance=VERIFIED),
    ]


def _motors() -> list[Component]:
    return [
        Component(id="motor.pololu_37d_50to1_12v", name="Pololu 37D 50:1 gearmotor 12 V, 64 CPR encoder",
                  category=C.motors_actuators, symbol="motor", manufacturer="Pololu", part_number="4753",
                  tags=["dc motor", "gearmotor", "encoder", "12V"],
                  pins=[Pin(id="M+", name="M+", type="motor_in"), Pin(id="M-", name="M-", type="motor_in"),
                        pw("ENC_VCC", "Encoder Vcc", 3.5, 20.0, required=False), gnd("ENC_GND", "Encoder GND"),
                        dout("ENC_A", "Encoder A", None, type="encoder_out"),
                        dout("ENC_B", "Encoder B", None, type="encoder_out")],
                  ratings={"v_rated": R(12.0, "V"), "noload_rpm": R(200.0, "rpm"), "i_noload": R(0.2, "A"),
                           "i_stall": R(5.5, "A"), "stall_torque": R(2.06, "N*m", note="21 kg*cm"),
                           "encoder_cpr_output": R(3200.0, "counts/rev", note="64 CPR motor shaft x 50:1")},
                  params={"gear_ratio": 50.0, "rotor_inertia": 3e-6, "encoder_follows_vcc": True,
                          "thermal_resistance": 8.0, "thermal_capacity": 60.0,
                          "assumptions": "rotor inertia and thermal parameters are estimates, not datasheet values"},
                  sim_model="motor:dc_brushed", support_status=S.simulation_supported,
                  datasheet="https://www.pololu.com/product/4753",
                  compatibility=["Stall current 5.5 A: the driver must survive stall or limit current."],
                  provenance=DS("https://www.pololu.com/product/4753",
                                "Encoder outputs swing to encoder Vcc (Hall sensors with pull-ups).")),
        Component(id="motor.dc_generic", name="Brushed DC gearmotor (parametric)", category=C.motors_actuators,
                  symbol="motor", tags=["dc motor", "parametric"],
                  pins=[Pin(id="M+", name="M+", type="motor_in"), Pin(id="M-", name="M-", type="motor_in")],
                  ratings={"v_rated": R(12.0, "V", "user"), "noload_rpm": R(150.0, "rpm", "user"),
                           "i_noload": R(0.15, "A", "user"), "i_stall": R(3.0, "A", "user"),
                           "stall_torque": R(1.2, "N*m", "user")},
                  params={"rotor_inertia": 3e-6, "gear_ratio": 30.0, "thermal_resistance": 8.0, "thermal_capacity": 60.0},
                  sim_model="motor:dc_brushed", support_status=S.simulation_supported,
                  provenance=Provenance(source="builtin_verified", notes="Enter values from your motor's datasheet.")),
        Component(id="servo.sg90", name="SG90 micro servo", category=C.motors_actuators, symbol="servo",
                  manufacturer="TowerPro", part_number="SG90", tags=["servo", "pwm", "5V"],
                  pins=[pw("V+", "V+", 4.8, 6.0), gnd(), din("SIG", "Signal", None, 6.0, required=True, type="pwm_in")],
                  ratings={"stall_torque": R(0.18, "N*m", "assumption", "1.8 kg*cm @4.8V, vendor figure"),
                           "i_stall": R(0.65, "A", "assumption", "typical measured, not specified by vendor"),
                           "i_typ": R(0.1, "A", "assumption")},
                  sim_model="behavioral:servo", support_status=S.behavioral, provenance=COMMUNITY),
        Component(id="stepper.nema17_17hs4401", name="NEMA 17 stepper 17HS4401", category=C.motors_actuators,
                  symbol="motor", part_number="17HS4401", tags=["stepper", "nema17"],
                  pins=[Pin(id="A+", name="A+", type="motor_in"), Pin(id="A-", name="A-", type="motor_in"),
                        Pin(id="B+", name="B+", type="motor_in"), Pin(id="B-", name="B-", type="motor_in")],
                  ratings={"i_phase": R(1.7, "A", "assumption", "commonly published vendor figure"),
                           "holding_torque": R(0.40, "N*m", "assumption"), "r_phase": R(1.5, "ohm", "assumption")},
                  sim_model=None, support_status=S.schematic_only, provenance=COMMUNITY),
    ]


def _drivers() -> list[Component]:
    def hbridge(cid, name, mfr, pn, vm, vlogic, vih, i_cont, i_peak, url, tags, extra_notes="", status=S.simulation_supported):
        pins = [pw("VM", "Motor supply", vm[0], vm[1]), gnd()]
        if vlogic:
            pins.append(pw("VCC", "Logic supply", vlogic[0], vlogic[1]))
        for ch in ("A", "B"):
            pins += [din(f"PWM{ch}", f"PWM{ch}/EN{ch}", vih, 7.0, required=True, type="pwm_in", group=ch),
                     din(f"IN{ch}1", f"IN{ch}1", vih, 7.0, required=True, group=ch),
                     din(f"IN{ch}2", f"IN{ch}2", vih, 7.0, required=True, group=ch),
                     Pin(id=f"OUT{ch}1", name=f"OUT{ch}1", type="motor_out", group=ch, i_max=i_cont),
                     Pin(id=f"OUT{ch}2", name=f"OUT{ch}2", type="motor_out", group=ch, i_max=i_cont)]
        return Component(id=cid, name=name, category=C.motor_drivers, symbol="driver", manufacturer=mfr, part_number=pn,
                         tags=["motor driver", "h-bridge", *tags], pins=pins,
                         ratings={"i_cont_per_channel": R(i_cont, "A"), "i_peak_per_channel": R(i_peak, "A"),
                                  "vm_max": R(vm[1], "V"), "i_typ": R(0.02, "A", "assumption", "logic quiescent")},
                         params={"channels": 2, "r_ds_on": 0.5}, sim_model="driver:hbridge", support_status=status,
                         datasheet=url, provenance=DS(url, extra_notes))

    l298 = hbridge("driver.l298n", "L298N dual H-bridge", "STMicroelectronics", "L298N", (4.8, 46.0), (4.5, 7.0), 2.3,
                   2.0, 3.0, "https://www.st.com/resource/en/datasheet/l298.pdf", ["bipolar"],
                   "Bipolar output stage: expect ~2-4 V total drop at 1-2 A. Module includes a 78M05 regulator.")
    l298.params["v_drop"] = 2.5
    tb = hbridge("driver.tb6612fng", "TB6612FNG dual driver", "Toshiba", "TB6612FNG", (2.5, 13.5), (2.7, 5.5), 0.7 * 3.3,
                 1.2, 3.2, "https://www.sparkfun.com/datasheets/Robotics/TB6612FNG.pdf", ["mosfet", "3.3V logic"],
                 "VIH = 0.7*VCC; at VCC=5 V a 3.3 V MCU is marginal-OK (3.5 V required) -> power VCC from 3.3 V.")
    # VIH depends on VCC; store the ratio so the engine can evaluate it against the actual rail.
    tb.params.update({"vih_ratio_of": "VCC", "vih_ratio": 0.7, "r_ds_on": 0.5})
    drv = hbridge("driver.drv8833", "DRV8833 dual H-bridge", "Texas Instruments", "DRV8833", (2.7, 10.8), None, 2.0,
                  1.5, 2.0, "https://www.ti.com/lit/ds/symlink/drv8833.pdf", ["mosfet", "low voltage"],
                  "1.5 A RMS per H-bridge at 25 C with adequate PCB cooling.")
    drv.params["r_ds_on"] = 0.36
    mdd = hbridge("driver.cytron_mdd10a", "Cytron MDD10A dual 10 A driver", "Cytron", "MDD10A", (5.0, 30.0), None, 1.8,
                  10.0, 30.0, "https://www.cytron.io/p-10amp-5v-30v-dc-motor-driver-2-channels",
                  ["mosfet", "high current", "3.3V logic"], "Logic accepts 3.3 V and 5 V. Peak 30 A for 10 s.")
    mdd.params["r_ds_on"] = 0.02
    vnh = hbridge("driver.vnh5019", "VNH5019 single 12 A driver", "STMicroelectronics", "VNH5019A-E", (5.5, 24.0), None, 2.1,
                  12.0, 30.0, "https://www.st.com/resource/en/datasheet/vnh5019a-e.pdf", ["mosfet", "current sense"],
                  "Single-channel IC; listed here as a dual-channel carrier (two ICs).")
    vnh.params["r_ds_on"] = 0.018
    drivers = [l298, tb, drv, mdd, vnh]
    drivers += [
        Component(id="driver.a4988", name="A4988 stepper driver", category=C.motor_drivers, symbol="driver",
                  manufacturer="Allegro", part_number="A4988", tags=["stepper driver"],
                  pins=[pw("VMOT", "VMOT", 8.0, 35.0), pw("VDD", "VDD", 3.0, 5.5), gnd(),
                        din("STEP", "STEP", 0.7 * 3.0, 5.5, required=True), din("DIR", "DIR", 0.7 * 3.0, 5.5, required=True),
                        Pin(id="1A", name="1A", type="motor_out"), Pin(id="1B", name="1B", type="motor_out"),
                        Pin(id="2A", name="2A", type="motor_out"), Pin(id="2B", name="2B", type="motor_out")],
                  ratings={"i_peak_per_channel": R(2.0, "A", note="with sufficient cooling")},
                  support_status=S.schematic_only, datasheet="https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.pdf",
                  provenance=DS("https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.pdf")),
        Component(id="driver.drv8825", name="DRV8825 stepper driver", category=C.motor_drivers, symbol="driver",
                  manufacturer="Texas Instruments", part_number="DRV8825", tags=["stepper driver"],
                  pins=[pw("VMOT", "VMOT", 8.2, 45.0), gnd(), din("STEP", "STEP", 2.2, 5.75, required=True),
                        din("DIR", "DIR", 2.2, 5.75, required=True),
                        Pin(id="A1", name="A1", type="motor_out"), Pin(id="A2", name="A2", type="motor_out"),
                        Pin(id="B1", name="B1", type="motor_out"), Pin(id="B2", name="B2", type="motor_out")],
                  ratings={"i_peak_per_channel": R(2.5, "A")}, support_status=S.schematic_only,
                  datasheet="https://www.ti.com/lit/ds/symlink/drv8825.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/drv8825.pdf")),
    ]
    return drivers


def _uno() -> Component:
    pins = [pw("VIN", "VIN", 7.0, 12.0, required=False),
            po("5V", "5V", 5.0, 0.4), po("3V3", "3.3V", 3.3, 0.05), gnd()]
    pwm = {3, 5, 6, 9, 10, 11}
    for d in range(14):
        caps = ["gpio", "interrupt"] if d in (2, 3) else ["gpio"]
        if d in pwm:
            caps.append("pwm")
        if d == 0:
            caps.append("uart_rx")
        if d == 1:
            caps.append("uart_tx")
        if d in (10, 11, 12, 13):
            caps.append("spi")
        pins.append(io(f"D{d}", f"D{d}", 5.0, 5.5, 3.0, caps, imax=0.02))
    for a in range(6):
        caps = ["gpio", "adc"] + (["i2c"] if a in (4, 5) else [])
        pins.append(io(f"A{a}", f"A{a}", 5.0, 5.5, 3.0, caps, imax=0.02))
    return Component(id="mcu.arduino_uno_r3", name="Arduino Uno R3", category=C.dev_boards, symbol="board",
                     manufacturer="Arduino", part_number="A000066", tags=["arduino", "atmega328p", "5V logic"],
                     pins=pins, interfaces=["uart", "i2c", "spi", "pwm", "adc"],
                     ratings={"i_typ": R(0.05, "A", "assumption", "board idle"),
                              "gpio_i_max": R(0.02, "A", note="recommended; 40 mA absolute max")},
                     params={"firmware_target": "arduino_uno", "logic_v": 5.0},
                     sim_model="firmware:behavioral", support_status=S.behavioral,
                     datasheet="https://docs.arduino.cc/hardware/uno-rev3",
                     provenance=DS("https://docs.arduino.cc/hardware/uno-rev3"))


def _three_v3_board(cid, name, mfr, pn, gpios, pwm_all, adc, url, extra_power, target, ft=False, imax=0.012,
                    i2c=(), uart=(), can=(), notes="") -> Component:
    pins = [*extra_power, gnd()]
    for g in gpios:
        caps = ["gpio"]
        if pwm_all:
            caps.append("pwm")
        if g in adc:
            caps.append("adc")
        if g in i2c:
            caps.append("i2c")
        if g in uart:
            caps.append("uart_tx" if uart.index(g) % 2 == 0 else "uart_rx")
        if g in can:
            caps.append("can")
        pins.append(io(g, g, 3.3, 5.5 if ft else 3.6, 2.0 if not ft else 2.31, caps, ft=ft, imax=imax))
    return Component(id=cid, name=name, category=C.dev_boards, symbol="board", manufacturer=mfr, part_number=pn,
                     tags=["3.3V logic", target], pins=pins, interfaces=["uart", "i2c", "spi", "pwm", "adc"],
                     ratings={"i_typ": R(0.08, "A", "assumption", "board active, radios off")},
                     params={"firmware_target": target, "logic_v": 3.3},
                     sim_model="firmware:behavioral", support_status=S.behavioral, datasheet=url,
                     compatibility=["GPIO are NOT 5 V tolerant." if not ft else "Most GPIO are 5 V tolerant (FT)."],
                     provenance=DS(url, notes))


def _controllers() -> list[Component]:
    esp_gpio = ["GPIO" + str(g) for g in (4, 5, 13, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33)]
    esp = _three_v3_board(
        "mcu.esp32_devkitc", "ESP32-DevKitC (ESP32-WROOM-32)", "Espressif", "ESP32-DevKitC-32E", esp_gpio, True,
        {"GPIO32", "GPIO33", "GPIO25", "GPIO26", "GPIO27", "GPIO14", "GPIO13", "GPIO4"},
        "https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/esp32/get-started-devkitc.html",
        [pw("5V", "5V", 4.75, 5.25, required=False), po("3V3", "3V3", 3.3, 0.5)], "esp32",
        imax=0.02, i2c=("GPIO21", "GPIO22"), uart=("GPIO17", "GPIO16"), can=("GPIO4", "GPIO5"),
        notes="LEDC PWM on any output GPIO. ADC2 unusable while Wi-Fi is active. TWAI (CAN) needs an external transceiver.")
    esp.ratings["i_typ"] = R(0.16, "A", "assumption", "Wi-Fi active average")
    nucleo_gpio = ["PA0", "PA1", "PA4", "PA5", "PA6", "PA7", "PA8", "PA9", "PA10", "PB3", "PB4", "PB5", "PB6",
                   "PB8", "PB9", "PB10", "PC0", "PC1", "PC7"]
    nucleo = _three_v3_board(
        "mcu.nucleo_f401re", "STM32 Nucleo-F401RE", "STMicroelectronics", "NUCLEO-F401RE", nucleo_gpio, True,
        {"PA0", "PA1", "PA4", "PB0", "PC0", "PC1"}, "https://www.st.com/en/evaluation-tools/nucleo-f401re.html",
        [pw("VIN", "VIN", 7.0, 12.0, required=False), po("5V", "5V", 5.0, 0.3), po("3V3", "3V3", 3.3, 0.3)],
        "stm32", ft=True, imax=0.025, i2c=("PB8", "PB9"), uart=("PA9", "PA10"),
        notes="Analog-capable pins (PA0, PA1, PA4, PC0, PC1) are not 5 V tolerant in analog mode; treated as FT in digital mode.")
    for p in nucleo.pins:
        if p.id in ("PA0", "PA1", "PA4", "PC0", "PC1"):
            p.five_v_tolerant, p.v_abs_max = False, 3.6
    pico_gpio = [f"GP{g}" for g in range(0, 23)] + ["GP26", "GP27", "GP28"]
    pico = _three_v3_board(
        "mcu.rpi_pico", "Raspberry Pi Pico (RP2040)", "Raspberry Pi", "SC0915", pico_gpio, True,
        {"GP26", "GP27", "GP28"}, "https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf",
        [pw("VSYS", "VSYS", 1.8, 5.5, required=False), pw("VBUS", "VBUS", 4.75, 5.25, required=False),
         po("3V3", "3V3(OUT)", 3.3, 0.3)], "rp2040", imax=0.012, i2c=("GP4", "GP5"), uart=("GP0", "GP1"))
    pi_gpio = [f"GPIO{g}" for g in (2, 3, 4, 14, 15, 17, 18, 22, 23, 24, 25, 27, 12, 13, 19, 26)]
    rpi = _three_v3_board(
        "sbc.raspberry_pi_4b", "Raspberry Pi 4 Model B", "Raspberry Pi", "RPI4-MODBP", pi_gpio, False, set(),
        "https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf",
        [pw("5V", "5V", 4.75, 5.25), po("3V3", "3V3", 3.3, 0.5)], "raspberry_pi",
        imax=0.016, i2c=("GPIO2", "GPIO3"), uart=("GPIO14", "GPIO15"),
        notes="No ADC. Hardware PWM only on GPIO12/13/18/19. 5 V input should supply 3 A.")
    rpi.category = C.sbc
    rpi.ratings["i_typ"] = R(1.2, "A", "assumption", "moderate CPU load, no USB peripherals")
    for p in rpi.pins:
        if p.id in ("GPIO12", "GPIO13", "GPIO18", "GPIO19"):
            p.capabilities.append("pwm")
    rpi.interfaces = ["uart", "i2c", "spi", "pwm", "usb", "ethernet", "wifi", "csi"]
    teensy_gpio = [str(i) for i in range(0, 24)]
    teensy = _three_v3_board(
        "mcu.teensy41", "Teensy 4.1", "PJRC", "TEENSY41", teensy_gpio, True, {"14", "15", "16", "17", "18", "19"},
        "https://www.pjrc.com/store/teensy41.html",
        [pw("VIN", "VIN", 3.6, 5.5), po("3V3", "3.3V", 3.3, 0.25)], "teensy41", imax=0.01,
        i2c=("18", "19"), uart=("1", "0"), can=("22", "23"))
    jetson = Component(id="sbc.jetson_orin_nano_devkit", name="NVIDIA Jetson Orin Nano Developer Kit", category=C.sbc,
                       symbol="board", manufacturer="NVIDIA", tags=["sbc", "gpu", "ai"],
                       pins=[pw("DC_IN", "DC jack", 9.0, 20.0),
                             gnd(), io("PIN7", "Header pin 7", 3.3, 3.6, 2.0, ["gpio"]),
                             io("PIN32", "Header pin 32", 3.3, 3.6, 2.0, ["gpio", "pwm"])],
                       interfaces=["usb", "ethernet", "csi", "i2c", "uart"],
                       ratings={"i_typ": R(1.0, "A", "assumption", "~12 W at 12 V-19 V input, workload dependent")},
                       support_status=S.schematic_only,
                       provenance=Provenance(source="manufacturer", verified=False,
                                             notes="Header subset only. Confirm power input range for your carrier revision."))
    mega = _uno()
    mega.id, mega.name, mega.part_number = "mcu.arduino_mega2560", "Arduino Mega 2560 Rev3", "A000067"
    mega.params = {"firmware_target": "arduino_mega", "logic_v": 5.0}
    mega.datasheet = "https://docs.arduino.cc/hardware/mega-2560"
    mega.provenance = DS("https://docs.arduino.cc/hardware/mega-2560", "Pin subset mirrors Uno header.")
    return [_uno(), mega, esp, nucleo, pico, rpi, teensy, jetson]


def _sensors() -> list[Component]:
    return [
        Component(id="sensor.rplidar_a1", name="RPLIDAR A1M8 2D LiDAR", category=C.sensors, symbol="sensor",
                  manufacturer="Slamtec", part_number="A1M8", tags=["lidar", "uart", "5V"],
                  pins=[pw("5V", "5V", 4.9, 5.5), gnd(), dout("TX", "TX", 3.3, type="uart_tx"),
                        din("RX", "RX", 2.0, 5.0, type="uart_rx"), din("MOTOCTL", "MOTOCTL", 2.0, 5.0, type="pwm_in")],
                  interfaces=["uart"],
                  ratings={"range_max": R(12.0, "m"), "range_min": R(0.15, "m"), "scan_rate": R(5.5, "Hz", note="typical"),
                           "i_typ": R(0.4, "A", "assumption", "includes scan motor")},
                  params={"beams": 360}, sim_model="sensor:lidar2d", support_status=S.simulation_supported,
                  datasheet="https://www.slamtec.com/en/Lidar/A1",
                  provenance=DS("https://www.slamtec.com/en/Lidar/A1",
                                "UART is 3.3 V TTL; usually connected via bundled USB adapter.")),
        Component(id="sensor.mpu6050_gy521", name="MPU-6050 IMU (GY-521 module)", category=C.sensors, symbol="sensor",
                  manufacturer="TDK InvenSense", part_number="MPU-6050", tags=["imu", "i2c", "accelerometer", "gyro"],
                  pins=[pw("VCC", "VCC", 3.3, 5.0), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=6.0),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=6.0)],
                  interfaces=["i2c"], ratings={"i_typ": R(0.004, "A")},
                  params={"i2c_address": "0x68"},
                  sim_model="sensor:imu", support_status=S.simulation_supported,
                  datasheet="https://invensense.tdk.com/products/motion-tracking/6-axis/mpu-6050/",
                  provenance=Provenance(source="datasheet", verified=False,
                                        url="https://invensense.tdk.com/products/motion-tracking/6-axis/mpu-6050/",
                                        notes="Chip VDD 2.375-3.46 V; GY-521 module adds a 3.3 V LDO and pull-ups to VCC (module figures).")),
        Component(id="sensor.bno055", name="BNO055 9-DoF absolute orientation", category=C.sensors, symbol="sensor",
                  manufacturer="Bosch Sensortec", part_number="BNO055", tags=["imu", "i2c", "fusion"],
                  pins=[pw("VDD", "VDD", 2.4, 3.6), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=3.6),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=3.6)],
                  interfaces=["i2c"], ratings={"i_typ": R(0.0123, "A")}, sim_model="sensor:imu",
                  support_status=S.simulation_supported,
                  datasheet="https://www.bosch-sensortec.com/products/smart-sensor-systems/bno055/",
                  provenance=DS("https://www.bosch-sensortec.com/products/smart-sensor-systems/bno055/", "Bare IC ratings.")),
        Component(id="sensor.hcsr04", name="HC-SR04 ultrasonic ranger", category=C.sensors, symbol="sensor",
                  tags=["ultrasonic", "5V"],
                  pins=[pw("VCC", "VCC", 4.5, 5.5), gnd(), din("TRIG", "Trig", 2.0, 5.5, required=True),
                        dout("ECHO", "Echo", 5.0)],
                  ratings={"range_max": R(4.0, "m", "assumption"), "i_typ": R(0.015, "A", "assumption")},
                  compatibility=["Echo output is 5 V: use a divider or level shifter for 3.3 V MCUs."],
                  sim_model="sensor:ultrasonic", support_status=S.simulation_supported, provenance=COMMUNITY),
        Component(id="sensor.vl53l0x", name="VL53L0X time-of-flight ranger", category=C.sensors, symbol="sensor",
                  manufacturer="STMicroelectronics", part_number="VL53L0X", tags=["tof", "i2c"],
                  pins=[pw("VDD", "AVDD", 2.6, 3.5), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=3.6),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=3.6)],
                  interfaces=["i2c"], ratings={"range_max": R(2.0, "m"), "i_typ": R(0.019, "A")},
                  sim_model="sensor:ultrasonic", support_status=S.simulation_supported,
                  datasheet="https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html",
                  provenance=DS("https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html", "Bare IC ratings.")),
        Component(id="sensor.ina219", name="INA219 current/power monitor", category=C.sensors, symbol="sensor",
                  manufacturer="Texas Instruments", part_number="INA219", tags=["current sense", "i2c", "power"],
                  pins=[pw("VS", "VS", 3.0, 5.5), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=6.0),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=6.0), passive("VIN+", "VIN+", 0),
                        passive("VIN-", "VIN-", 1)],
                  interfaces=["i2c"], ratings={"bus_v_max": R(26.0, "V"), "i_typ": R(0.001, "A")},
                  sim_model="sensor:power_monitor", support_status=S.simulation_supported,
                  datasheet="https://www.ti.com/lit/ds/symlink/ina219.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/ina219.pdf")),
        Component(id="adc.ads1115", name="ADS1115 16-bit ADC", category=C.analog_ics, symbol="ic",
                  manufacturer="Texas Instruments", part_number="ADS1115", tags=["adc", "i2c"],
                  pins=[pw("VDD", "VDD", 2.0, 5.5), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=5.5),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=5.5), Pin(id="A0", name="AIN0", type="analog_in")],
                  interfaces=["i2c"], ratings={"i_typ": R(0.0002, "A")}, sim_model="behavioral:adc",
                  support_status=S.behavioral, datasheet="https://www.ti.com/lit/ds/symlink/ads1115.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/ads1115.pdf")),
        Component(id="sensor.rpi_camera_v2", name="Raspberry Pi Camera Module v2", category=C.sensors, symbol="sensor",
                  manufacturer="Raspberry Pi", part_number="IMX219", tags=["camera", "csi", "rgb"],
                  interfaces=["csi"], pins=[Pin(id="CSI", name="CSI", type="usb")],
                  ratings={"resolution": R(8.0, "MP")}, sim_model="sensor:camera",
                  support_status=S.behavioral, datasheet="https://www.raspberrypi.com/documentation/accessories/camera.html",
                  provenance=DS("https://www.raspberrypi.com/documentation/accessories/camera.html")),
        Component(id="sensor.realsense_d435", name="Intel RealSense D435 depth camera", category=C.sensors, symbol="sensor",
                  manufacturer="Intel", part_number="D435", tags=["depth", "camera", "usb3"],
                  interfaces=["usb"], pins=[Pin(id="USB", name="USB-C", type="usb")],
                  ratings={"range_max": R(10.0, "m", note="ideal conditions"), "i_typ": R(0.7, "A", "assumption", "at 5 V")},
                  sim_model="sensor:depth", support_status=S.behavioral,
                  provenance=Provenance(source="manufacturer", verified=False)),
        Component(id="sensor.quadrature_encoder", name="Quadrature encoder (Hall, open-collector w/ pull-ups)",
                  category=C.sensors, symbol="sensor", tags=["encoder"],
                  pins=[pw("VCC", "VCC", 3.3, 5.5), gnd(), dout("A", "A", None, type="encoder_out"),
                        dout("B", "B", None, type="encoder_out")],
                  params={"cpr": 1024, "follows_vcc": True}, sim_model="sensor:encoder",
                  support_status=S.simulation_supported, provenance=VERIFIED),
        Component(id="sensor.as5600", name="AS5600 magnetic angle encoder", category=C.sensors, symbol="sensor",
                  manufacturer="ams OSRAM", part_number="AS5600", tags=["encoder", "i2c", "angle"],
                  pins=[pw("VDD", "VDD", 3.0, 5.5), gnd(), Pin(id="SDA", name="SDA", type="i2c_sda", v_abs_max=6.0),
                        Pin(id="SCL", name="SCL", type="i2c_scl", v_abs_max=6.0)],
                  interfaces=["i2c"], ratings={"resolution_bits": R(12, "bit")}, sim_model="sensor:encoder",
                  support_status=S.behavioral, provenance=Provenance(source="manufacturer", verified=False)),
    ]


def _comms() -> list[Component]:
    return [
        Component(id="comm.mcp2515_tja1050", name="MCP2515 CAN controller + TJA1050 module", category=C.communication,
                  symbol="ic", manufacturer="Microchip / NXP", part_number="MCP2515", tags=["can", "spi", "5V"],
                  pins=[pw("VCC", "VCC", 4.75, 5.25), gnd(), din("CS", "CS", 2.0, 5.5, type="spi_cs"),
                        din("SI", "SI", 2.0, 5.5, type="spi_mosi"), dout("SO", "SO", 5.0, type="spi_miso"),
                        din("SCK", "SCK", 2.0, 5.5, type="spi_sck"), Pin(id="CANH", name="CANH", type="can_h"),
                        Pin(id="CANL", name="CANL", type="can_l")],
                  interfaces=["spi", "can"], ratings={"i_typ": R(0.07, "A", "assumption")},
                  compatibility=["SO output swings to 5 V when module runs from 5 V — not safe for 3.3 V MCUs."],
                  sim_model="comm:can", support_status=S.behavioral,
                  datasheet="https://www.microchip.com/en-us/product/MCP2515", provenance=COMMUNITY),
        Component(id="comm.sn65hvd230", name="SN65HVD230 3.3 V CAN transceiver", category=C.communication, symbol="ic",
                  manufacturer="Texas Instruments", part_number="SN65HVD230", tags=["can", "3.3V"],
                  pins=[pw("VCC", "VCC", 3.0, 3.6), gnd(), din("TXD", "D", 2.0, 4.1, type="can_tx"),
                        dout("RXD", "R", 3.3, type="can_rx"), Pin(id="CANH", name="CANH", type="can_h"),
                        Pin(id="CANL", name="CANL", type="can_l")],
                  interfaces=["can"], ratings={"i_typ": R(0.01, "A")}, sim_model="comm:can",
                  support_status=S.behavioral, datasheet="https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf",
                  provenance=DS("https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf")),
        Component(id="comm.max485", name="MAX485 RS-485 transceiver", category=C.communication, symbol="ic",
                  manufacturer="Analog Devices", part_number="MAX485", tags=["rs485", "uart", "5V"],
                  pins=[pw("VCC", "VCC", 4.75, 5.25), gnd(), din("DI", "DI", 2.0, 5.5, type="uart_rx"),
                        dout("RO", "RO", 5.0, type="uart_tx"), din("DE", "DE", 2.0, 5.5, required=True),
                        Pin(id="A", name="A", type="passive"), Pin(id="B", name="B", type="passive")],
                  interfaces=["uart", "rs485"], ratings={"i_typ": R(0.0005, "A")}, sim_model="comm:serial",
                  support_status=S.behavioral,
                  datasheet="https://www.analog.com/media/en/technical-documentation/data-sheets/MAX1487-MAX491.pdf",
                  provenance=DS("https://www.analog.com/media/en/technical-documentation/data-sheets/MAX1487-MAX491.pdf")),
        Component(id="comm.nrf24l01p", name="nRF24L01+ 2.4 GHz transceiver", category=C.communication, symbol="ic",
                  manufacturer="Nordic Semiconductor", part_number="nRF24L01+", tags=["wireless", "spi", "2.4GHz"],
                  pins=[pw("VCC", "VCC", 1.9, 3.6), gnd(), din("CSN", "CSN", 0.7 * 3.3, 5.25, type="spi_cs"),
                        din("MOSI", "MOSI", 0.7 * 3.3, 5.25, type="spi_mosi"), dout("MISO", "MISO", 3.3, type="spi_miso"),
                        din("SCK", "SCK", 0.7 * 3.3, 5.25, type="spi_sck")],
                  interfaces=["spi"], ratings={"i_typ": R(0.0135, "A", note="RX mode")},
                  compatibility=["Supply must be 1.9-3.6 V; inputs are 5 V tolerant."], sim_model="comm:radio",
                  support_status=S.behavioral, datasheet="https://www.nordicsemi.com/Products/nRF24-series",
                  provenance=DS("https://www.nordicsemi.com/Products/nRF24-series")),
        Component(id="comm.cp2102", name="CP2102 USB-UART bridge module", category=C.communication, symbol="ic",
                  manufacturer="Silicon Labs", part_number="CP2102", tags=["usb", "uart"],
                  pins=[Pin(id="USB", name="USB", type="usb"), po("5V", "5V", 5.0, 0.5), gnd(),
                        dout("TXD", "TXD", 3.3, type="uart_tx"), din("RXD", "RXD", 2.0, 5.0, type="uart_rx")],
                  interfaces=["usb", "uart"], sim_model="comm:serial", support_status=S.behavioral,
                  datasheet="https://www.silabs.com/interface/usb-bridges/classic/device.cp2102",
                  provenance=DS("https://www.silabs.com/interface/usb-bridges/classic/device.cp2102", "RXD is 5 V tolerant.")),
    ]


def _protection_connectors() -> list[Component]:
    return [
        Component(id="fuse.blade", name="Automotive blade fuse", category=C.protection_switching, symbol="fuse",
                  tags=["fuse", "protection"], pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"rating_a": 10.0, "r_cold": 0.005}, sim_model="protection:fuse_i2t",
                  ratings={"rating_a": R(10.0, "A", "user")}, support_status=S.simulation_supported, provenance=VERIFIED),
        Component(id="switch.estop_nc", name="Emergency stop (NC contact)", category=C.protection_switching, symbol="switch",
                  tags=["estop", "safety", "switch"], pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  params={"closed": True}, ratings={"contact_a": R(10.0, "A", "assumption")},
                  sim_model="spice:SW", support_status=S.simulation_supported,
                  compatibility=["A simulated E-stop is NOT a certified safety function."], provenance=VERIFIED),
        Component(id="relay.srd05vdc", name="Songle SRD-05VDC-SL-C relay", category=C.protection_switching, symbol="relay",
                  manufacturer="Songle", part_number="SRD-05VDC-SL-C", tags=["relay", "5V"],
                  pins=[passive("COIL+", "Coil+", 0), passive("COIL-", "Coil-", 1), passive("COM", "COM", 2),
                        passive("NO", "NO", 3), passive("NC", "NC", 4)],
                  ratings={"coil_v": R(5.0, "V"), "coil_i": R(0.0714, "A", note="70 ohm coil"),
                           "contact_a_dc": R(10.0, "A", note="at 28-30 VDC")},
                  compatibility=["Coil current (~71 mA) exceeds any MCU GPIO rating: drive through a transistor + flyback diode."],
                  support_status=S.schematic_only, provenance=COMMUNITY),
        Component(id="conn.xt60", name="XT60 power connector", category=C.connectors, symbol="connector",
                  manufacturer="Amass", part_number="XT60", tags=["connector", "power"],
                  pins=[passive("+", "+", 0), passive("-", "-", 1)],
                  ratings={"i_cont": R(30.0, "A", "datasheet", "Amass continuous rating")},
                  support_status=S.schematic_only, provenance=Provenance(source="manufacturer", verified=False)),
        Component(id="conn.jst_xh_2", name="JST XH 2-pin (2.5 mm)", category=C.connectors, symbol="connector",
                  manufacturer="JST", part_number="B2B-XH-A", tags=["connector", "signal"],
                  pins=[passive("1", "1", 0), passive("2", "2", 1)], ratings={"i_cont": R(3.0, "A")},
                  datasheet="https://www.jst-mfg.com/product/pdf/eng/eXH.pdf", support_status=S.schematic_only,
                  provenance=DS("https://www.jst-mfg.com/product/pdf/eng/eXH.pdf")),
        Component(id="conn.terminal_2p", name="Screw terminal block 2-pin 5.08 mm", category=C.connectors, symbol="connector",
                  tags=["connector", "terminal"], pins=[passive("1", "1", 0), passive("2", "2", 1)],
                  ratings={"i_cont": R(None, "A", "unknown", "rating varies by manufacturer — enter from datasheet")},
                  support_status=S.schematic_only, provenance=VERIFIED),
    ]


def _mechanical() -> list[Component]:
    def mech(cid, name, cat, params, tags, status=S.cad_only):
        return Component(id=cid, name=name, category=cat, symbol="part", tags=tags, params=params,
                         support_status=status, provenance=VERIFIED)
    return [
        mech("wheel.rubber_65mm", "Rubber wheel 65 mm", C.wheels_gearboxes,
             {"radius": 0.0325, "width": 0.026, "mass": 0.04, "friction": 0.9}, ["wheel"], S.simulation_supported),
        mech("wheel.pu_100mm", "Polyurethane wheel 100 mm", C.wheels_gearboxes,
             {"radius": 0.05, "width": 0.032, "mass": 0.12, "friction": 0.8}, ["wheel"], S.simulation_supported),
        mech("wheel.pu_150mm", "Polyurethane drive wheel 150 mm", C.wheels_gearboxes,
             {"radius": 0.075, "width": 0.04, "mass": 0.35, "friction": 0.8}, ["wheel", "agv"], S.simulation_supported),
        mech("wheel.mecanum_97mm", "Mecanum wheel 97 mm", C.wheels_gearboxes,
             {"radius": 0.0485, "width": 0.045, "mass": 0.2, "roller_angle_deg": 45},
             ["wheel", "mecanum", "omni"], S.cad_only),
        mech("wheel.caster_50mm", "Swivel caster 50 mm", C.wheels_gearboxes,
             {"radius": 0.025, "width": 0.02, "mass": 0.06, "friction": 0.05}, ["caster"], S.simulation_supported),
        mech("mech.extrusion_2020", "Aluminium extrusion 20x20 (per metre)", C.mechanical,
             {"profile": [0.02, 0.02], "linear_mass": 0.5}, ["frame", "extrusion"]),
        mech("mech.bracket_l_2020", "L bracket for 2020", C.mechanical, {"size": [0.02, 0.02, 0.02], "mass": 0.01},
             ["bracket", "mount"]),
        mech("mech.motor_mount_37d", "Motor mount for 37D gearmotor", C.mechanical,
             {"size": [0.045, 0.04, 0.003], "mass": 0.02}, ["mount", "bracket"]),
        mech("mech.gearbox_planetary_10to1", "Planetary gearbox 10:1", C.wheels_gearboxes,
             {"ratio": 10.0, "efficiency": 0.9, "mass": 0.2}, ["gearbox"], S.simulation_supported),
        mech("mech.enclosure_abs", "ABS enclosure 200x120x75", C.mechanical, {"size": [0.2, 0.12, 0.075], "mass": 0.3},
             ["enclosure"]),
        mech("equip.pallet_rack", "Pallet rack bay", C.industrial_equipment, {"size": [2.7, 1.1, 2.0]}, ["rack", "warehouse"]),
        mech("equip.conveyor", "Belt conveyor section", C.industrial_equipment, {"size": [3.0, 0.6, 0.8]}, ["conveyor"]),
        mech("equip.charging_dock", "AMR charging dock", C.industrial_equipment,
             {"size": [0.4, 0.3, 0.3], "charge_power_w": 120.0}, ["charging", "dock"], S.simulation_supported),
    ]


def _models_envs_adapters() -> list[Component]:
    items = []
    for cid, name in [("robot.rv_diff_small", "RV-Diff small AMR (reference template)"),
                      ("robot.rv_agv_tugger", "RV-AGV tugger (reference template)"),
                      ("robot.rv_arm_4dof", "RV-Arm 4-DoF (reference template)")]:
        items.append(Component(id=cid, name=name, category=C.robot_models, symbol="part", tags=["template", "robot"],
                               support_status=S.simulation_supported if "diff" in cid or "agv" in cid else S.cad_only,
                               provenance=VERIFIED))
    for env in ["warehouse", "factory_floor", "indoor_logistics", "outdoor_terrain", "laboratory", "obstacle_course"]:
        items.append(Component(id=f"env.{env}", name=env.replace("_", " ").title(), category=C.environments,
                               symbol="part", tags=["environment", "template"], support_status=S.simulation_supported,
                               provenance=VERIFIED))
    for tgt, status in [("arduino_uno", S.behavioral), ("esp32", S.behavioral), ("stm32", S.behavioral),
                        ("rp2040", S.behavioral), ("raspberry_pi", S.behavioral)]:
        items.append(Component(id=f"fw.{tgt}", name=f"Firmware adapter: {tgt}", category=C.firmware_adapters,
                               symbol="part", tags=["firmware", tgt], support_status=status, provenance=VERIFIED))
    return items


def builtin_components() -> list[Component]:
    return [*_passives(), *_semis(), *_regulators(), *_batteries(), *_motors(), *_drivers(), *_controllers(),
            *_sensors(), *_comms(), *_protection_connectors(), *_mechanical(), *_models_envs_adapters()]
