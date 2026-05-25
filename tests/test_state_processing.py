#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_state_processing.py
# Description: Tests for the _process_*_state methods — these take an MQTT
#              payload dict and translate it into Indigo state updates. State
#              writes are captured by the FakeDevice stub.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026


def _states_dict(dev):
    return dict(dev.states)


# ── _process_light_state ─────────────────────────────────────────────────────

def test_light_state_on(plugin, make_device):
    dev = make_device(601, "Lounge Lamp", "z2mLight",
                      pluginProps={"has_color_temp": True, "has_color": True})
    dev.supportsWhiteTemperature = True
    dev.supportsColor            = True
    plugin._process_light_state(dev, {"state": "ON", "brightness": 254})
    s = _states_dict(dev)
    assert s["onOffState"]       is True
    assert s["brightnessLevel"]  == 100


def test_light_state_off_brightness_forced_zero(plugin, make_device):
    dev = make_device(602, "Lounge Lamp", "z2mLight",
                      pluginProps={"has_color_temp": True})
    dev.supportsWhiteTemperature = True
    plugin._process_light_state(dev, {"state": "OFF", "brightness": 128})
    s = _states_dict(dev)
    assert s["onOffState"]       is False
    assert s["brightnessLevel"]  == 0


def test_light_state_color_temp_to_kelvin(plugin, make_device):
    dev = make_device(603, "Lounge Lamp", "z2mLight",
                      pluginProps={"has_color_temp": True})
    dev.supportsWhiteTemperature = True
    plugin._process_light_state(dev, {"state": "ON", "color_temp": 370})  # 370 mireds
    s = _states_dict(dev)
    assert 2600 <= s["whiteTemperature"] <= 2800   # ~2700K
    assert "K" in str(dev.state_writes[-1][2])


def test_light_state_xy_color(plugin, make_device):
    dev = make_device(604, "Lounge Lamp", "z2mLight",
                      pluginProps={"has_color": True})
    dev.supportsColor = True
    plugin._process_light_state(dev, {"state": "ON", "color": {"x": 0.4, "y": 0.4}})
    s = _states_dict(dev)
    for k in ("redLevel", "greenLevel", "blueLevel"):
        assert k in s
        assert 0 <= s[k] <= 100


# ── _process_relay_state ─────────────────────────────────────────────────────

def test_relay_state_on(plugin, make_device):
    dev = make_device(701, "Plug", "z2mRelay")
    plugin._process_relay_state(dev, {"state": "ON"})
    assert dev.states["onOffState"] is True


def test_relay_state_power_and_energy(plugin, make_device):
    dev = make_device(702, "Plug", "z2mRelay")
    plugin._process_relay_state(dev, {"state": "ON", "power": 123.4, "energy": 5.678})
    assert dev.states["power"]  == 123.4
    assert dev.states["energy"] == 5.678
    # The UI value for power should include 'W'
    ui_values = [u[2] for u in dev.state_writes if u[0] == "power"]
    assert "W" in ui_values[0]


def test_relay_state_invalid_power_silently_skipped(plugin, make_device):
    dev = make_device(703, "Plug", "z2mRelay")
    plugin._process_relay_state(dev, {"state": "ON", "power": "junk"})
    # state still updated; power not present
    assert dev.states["onOffState"] is True
    assert "power" not in dev.states


# ── _process_contact_sensor_state ────────────────────────────────────────────

def test_contact_open(plugin, make_device):
    dev = make_device(801, "Door", "z2mContactSensor")
    plugin._process_contact_sensor_state(dev, {"contact": False})
    assert dev.states["contact"]    is False
    assert dev.states["onOffState"] is True   # open == sensor triggered


def test_contact_closed(plugin, make_device):
    dev = make_device(802, "Door", "z2mContactSensor")
    plugin._process_contact_sensor_state(dev, {"contact": True})
    assert dev.states["contact"]    is True
    assert dev.states["onOffState"] is False


def test_contact_battery(plugin, make_device):
    dev = make_device(803, "Door", "z2mContactSensor")
    plugin._process_contact_sensor_state(dev, {"contact": True, "battery": 85})
    assert dev.states["battery"] == 85


# ── _process_occupancy_sensor_state ──────────────────────────────────────────

def test_occupancy_motion_detected(plugin, make_device):
    dev = make_device(901, "Motion", "z2mOccupancySensor",
                      pluginProps={"has_pir": True})
    plugin._process_occupancy_sensor_state(dev, {"occupancy": True})
    assert dev.states["occupancy"]  is True
    assert dev.states["motion"]     is True
    assert dev.states["onOffState"] is True


def test_occupancy_motion_clear(plugin, make_device):
    dev = make_device(902, "Motion", "z2mOccupancySensor",
                      pluginProps={"has_pir": True})
    # First trigger so motion store is initialised
    plugin._process_occupancy_sensor_state(dev, {"occupancy": True})
    plugin._process_occupancy_sensor_state(dev, {"occupancy": False})
    assert dev.states["onOffState"] is False


def test_occupancy_partial_payload_preserves_other_motion_key(plugin, make_device):
    """A device with both PIR (occupancy) and mmWave (presence) — receiving
    a partial payload that updates only one key must NOT lose the other."""
    dev = make_device(903, "Combo Sensor", "z2mOccupancySensor",
                      pluginProps={"has_pir": True, "has_presence": True})
    # PIR fires
    plugin._process_occupancy_sensor_state(dev, {"occupancy": True})
    assert dev.states["onOffState"] is True
    # mmWave reports OFF — but PIR is still True; OR must remain True
    plugin._process_occupancy_sensor_state(dev, {"presence": False})
    assert dev.states["onOffState"] is True
    # PIR goes False — now both False
    plugin._process_occupancy_sensor_state(dev, {"occupancy": False})
    assert dev.states["onOffState"] is False


def test_occupancy_illuminance(plugin, make_device):
    dev = make_device(904, "Motion", "z2mOccupancySensor",
                      pluginProps={"has_pir": True, "has_illuminance": True})
    plugin._process_occupancy_sensor_state(dev,
        {"occupancy": True, "illuminance_lux": 123.456})
    assert abs(dev.states["illuminance"] - 123.5) < 0.01


def test_occupancy_self_heals_missing_capability_flag(plugin, make_device):
    """A device whose payload contains 'occupancy' but whose stored
    has_pir flag was False (created when exposes was incomplete) should
    self-heal: capability flags must be promoted to True."""
    dev = make_device(905, "Motion", "z2mOccupancySensor",
                      pluginProps={"has_pir": False, "has_presence": False})
    plugin._process_occupancy_sensor_state(dev, {"occupancy": True})
    assert dev.pluginProps.get("has_pir") is True


# ── _process_water_leak_sensor_state ─────────────────────────────────────────

def test_water_leak_detected(plugin, make_device):
    dev = make_device(1001, "Leak", "z2mWaterLeakSensor")
    plugin._process_water_leak_sensor_state(dev, {"water_leak": True})
    assert dev.states["waterLeak"]  is True
    assert dev.states["onOffState"] is True


def test_water_leak_clear(plugin, make_device):
    dev = make_device(1002, "Leak", "z2mWaterLeakSensor")
    plugin._process_water_leak_sensor_state(dev, {"water_leak": False})
    assert dev.states["onOffState"] is False


# ── _process_temperature_sensor_state ────────────────────────────────────────

def test_temperature_humidity_pressure(plugin, make_device):
    dev = make_device(1101, "Env", "z2mTemperatureSensor",
                      pluginProps={"has_temperature": True, "has_humidity": True,
                                   "has_pressure": True})
    plugin._process_temperature_sensor_state(dev,
        {"temperature": 21.456, "humidity": 55.5, "pressure": 1013.25})
    assert abs(dev.states["temperature"] - 21.5) < 0.01
    assert dev.states["humidity"] == 55.5
    # pressure is rounded to 1 dp (Python banker's rounding: 1013.25 -> 1013.2)
    assert abs(dev.states["pressure"] - 1013.2) < 0.05


def test_temperature_invalid_value_skipped(plugin, make_device):
    dev = make_device(1102, "Env", "z2mTemperatureSensor",
                      pluginProps={"has_temperature": True})
    plugin._process_temperature_sensor_state(dev, {"temperature": "n/a"})
    assert "temperature" not in dev.states
