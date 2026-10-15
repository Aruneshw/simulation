"""Firmware targets and their *validated* execution modes.

Building firmware does not prove it executes correctly in a simulator. Only
modes listed per target are offered; 'emulated' is listed only where an
emulator path has been verified to boot that target class.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Target:
    id: str
    name: str
    platformio_env: dict
    modes: list[str]
    max_loop_hz: float
    logic_v: float
    notes: str = ""
    emulator: str | None = None
    hal: dict = field(default_factory=dict)


TARGETS = {
    "arduino_uno": Target("arduino_uno", "Arduino Uno (ATmega328P)",
                          {"platform": "atmelavr", "board": "uno", "framework": "arduino"},
                          ["behavioral", "hal_mock", "hil"], 1000, 5.0,
                          "Emulation via simavr is possible but not integrated; use behavioural or HIL.",
                          hal={"pwm_write": "analogWrite({pin}, {duty255});", "pwm_max": 255}),
    "arduino_mega": Target("arduino_mega", "Arduino Mega 2560", {"platform": "atmelavr", "board": "megaatmega2560", "framework": "arduino"},
                           ["behavioral", "hal_mock", "hil"], 1000, 5.0,
                           hal={"pwm_write": "analogWrite({pin}, {duty255});", "pwm_max": 255}),
    "esp32": Target("esp32", "ESP32 (Arduino core)", {"platform": "espressif32", "board": "esp32dev", "framework": "arduino"},
                    ["behavioral", "hal_mock", "hil"], 1000, 3.3,
                    "Espressif's QEMU fork can boot ESP32 images but is not bundled; emulated mode is therefore not offered.",
                    hal={"pwm_write": "ledcWrite({pin}, {duty255});", "pwm_max": 255}),
    "stm32": Target("stm32", "STM32 Nucleo-F401RE (Arduino core)", {"platform": "ststm32", "board": "nucleo_f401re", "framework": "arduino"},
                    ["behavioral", "hal_mock", "hil"], 2000, 3.3,
                    "Renode/QEMU support exists for some STM32 boards; not validated for F401RE here.",
                    hal={"pwm_write": "analogWrite({pin}, {duty255});", "pwm_max": 255}),
    "rp2040": Target("rp2040", "Raspberry Pi Pico (Arduino-Pico)", {"platform": "raspberrypi", "board": "pico", "framework": "arduino"},
                     ["behavioral", "hal_mock", "hil"], 2000, 3.3,
                     hal={"pwm_write": "analogWrite({pin}, {duty255});", "pwm_max": 255}),
    "teensy41": Target("teensy41", "Teensy 4.1", {"platform": "teensy", "board": "teensy41", "framework": "arduino"},
                       ["behavioral", "hal_mock", "hil"], 5000, 3.3,
                       hal={"pwm_write": "analogWrite({pin}, {duty255});", "pwm_max": 255}),
    "raspberry_pi": Target("raspberry_pi", "Raspberry Pi (Linux, Python/ROS 2 node)", {},
                           ["behavioral", "hal_mock", "hil"], 200, 3.3,
                           "Runs Linux: deploy the generated ROS 2 package; no MCU firmware build.",
                           hal={}),
}


def target_list() -> list[dict]:
    return [{"id": t.id, "name": t.name, "modes": t.modes, "logic_v": t.logic_v, "notes": t.notes,
             "platformio": t.platformio_env, "max_loop_hz": t.max_loop_hz} for t in TARGETS.values()]
