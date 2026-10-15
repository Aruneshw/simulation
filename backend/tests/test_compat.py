from roboverse.engines.circuit.compat import check_circuit


def codes(res):
    return {i["code"] for i in res["issues"]}


def test_reference_amr_is_clean(amr, registry):
    res = check_circuit(amr.circuit, registry, amr.firmware, amr.robot.controller_ref)
    errors = [i for i in res["issues"] if i["severity"] in ("critical", "error")]
    assert errors == []
    bat = res["power_budget"]["battery"]
    assert bat["instance"] == "BT1" and bat["current_typ_a"] > 0 and bat["runtime_h_estimate"] > 1
    assert res["power_budget"]["kind"] == "analytical_estimate"


def test_faulty_amr_flags_level_and_driver(registry):
    from roboverse.samples import warehouse_amr
    p = warehouse_amr(faulty=True)
    res = check_circuit(p.circuit, registry, p.firmware, p.robot.controller_ref)
    c = codes(res)
    assert "E010" in c and "E030" in c
    lv = next(i for i in res["issues"] if i["code"] == "E010")
    assert "M1.ENC_A -> U3.GPIO4" in lv["connection"]  # exact connection
    assert lv["fix"] and lv["specs"]  # practical correction + cited specification
    assert any(s["field"].endswith("v_abs_max") for s in lv["specs"])


def test_raspberry_pi_gpio_vs_5v_sensor(cb, registry):
    cb.add("PS", "supply.bench", 0, 0, voltage=5.0)
    cb.add("PI", "sbc.raspberry_pi_4b", 0, 0)
    cb.add("US", "sensor.hcsr04", 0, 0)
    cb.wire("PS.+", "PI.5V"); cb.wire("PS.+", "US.VCC")
    cb.wire("PS.-", "PI.GND"); cb.wire("PS.-", "US.GND")
    cb.wire("US.ECHO", "PI.GPIO23"); cb.wire("PI.GPIO24", "US.TRIG")
    res = check_circuit(cb.c, registry)
    e = [i for i in res["issues"] if i["code"] == "E010"]
    assert e and "US.ECHO -> PI.GPIO23" in e[0]["connection"]
    assert "level shifter" in e[0]["fix"].lower() or "divider" in e[0]["fix"].lower()


def test_supply_overvoltage_and_short(cb, registry):
    cb.add("B", "battery.lipo_3s_2200", 0, 0)
    cb.add("S", "sensor.bno055", 0, 0)
    cb.add("V5", "source.dc_voltage", 0, 0, voltage=5.0)
    cb.wire("B.+", "S.VDD"); cb.wire("B.-", "S.GND")
    cb.wire("V5.+", "B.+")  # two different rails tied
    cb.wire("V5.-", "B.-")
    c = codes(check_circuit(cb.c, registry))
    assert "E003" in c and "E001" in c


def test_supply_to_ground_short(cb, registry):
    cb.add("V", "source.dc_voltage", 0, 0)
    cb.wire("V.+", "V.-")
    assert "E002" in codes(check_circuit(cb.c, registry))


def test_unpowered_missing_ground_floating(cb, registry):
    cb.add("D", "driver.drv8833", 0, 0)
    res = check_circuit(cb.c, registry)
    c = codes(res)
    assert "E005" in c and "E012" in c


def test_uart_i2c_can_miswiring(cb, registry):
    cb.add("U", "comm.cp2102", 0, 0)
    cb.add("L", "sensor.rplidar_a1", 0, 0)
    cb.wire("U.TXD", "L.TX")  # TX-TX
    cb.add("I", "sensor.bno055", 0, 0)
    cb.add("A", "adc.ads1115", 0, 0)
    cb.wire("I.SDA", "A.SCL")
    cb.add("C1", "comm.sn65hvd230", 0, 0)
    cb.add("C2", "comm.sn65hvd230", 0, 0)
    cb.wire("C1.CANH", "C2.CANL")
    c = codes(check_circuit(cb.c, registry))
    assert {"E020", "E021", "E022"} <= c


def test_motor_without_driver_and_led_without_resistor(cb, registry):
    cb.add("MCU", "mcu.arduino_uno_r3", 0, 0)
    cb.add("M", "motor.dc_generic", 0, 0)
    cb.add("LED", "led.generic_red", 0, 0)
    cb.add("K", "relay.srd05vdc", 0, 0)
    cb.wire("MCU.D9", "M.M+"); cb.wire("MCU.GND", "M.M-")
    cb.wire("MCU.D13", "LED.A"); cb.wire("LED.K", "MCU.GND")
    cb.wire("MCU.D7", "K.COIL+")
    c = codes(check_circuit(cb.c, registry))
    assert {"E032", "E050", "E051"} <= c


def test_pwm_capability(cb, registry):
    cb.add("PS", "supply.bench", 0, 0, voltage=5.0)
    cb.add("MCU", "mcu.arduino_uno_r3", 0, 0)
    cb.add("SV", "servo.sg90", 0, 0)
    cb.wire("PS.+", "SV.V+"); cb.wire("PS.-", "SV.GND"); cb.wire("PS.-", "MCU.GND")
    cb.wire("MCU.D4", "SV.SIG")  # D4 has no PWM on the Uno
    res = check_circuit(cb.c, registry)
    e = [i for i in res["issues"] if i["code"] == "E024"]
    assert e and "MCU.D4" in e[0]["connection"]


def test_battery_discharge_and_fuse(cb, registry):
    cb.add("B", "battery.lipo_3s_2200", 0, 0)
    cb.add("F", "fuse.blade", 0, 0, rating_a=1.0)
    cb.add("D", "driver.cytron_mdd10a", 0, 0)
    cb.wire("B.+", "F.1"); cb.wire("F.2", "D.VM"); cb.wire("B.-", "D.GND")
    for ch, m in (("A", "M1"), ("B", "M2")):
        cb.add(m, "motor.pololu_37d_50to1_12v", 0, 0)
        cb.wire(f"D.OUT{ch}1", f"{m}.M+"); cb.wire(f"D.OUT{ch}2", f"{m}.M-")
    res = check_circuit(cb.c, registry)
    assert "E042" in codes(res)  # 1 A fuse vs ~2.75 A typical motor load


def test_level_shifter_resolves_mismatch(registry):
    from roboverse.samples import warehouse_amr
    p = warehouse_amr()
    res = check_circuit(p.circuit, registry, p.firmware, p.robot.controller_ref)
    assert "E010" not in codes(res)
