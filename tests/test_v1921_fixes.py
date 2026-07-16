#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1921_fixes.py
# Description: Regression tests for the v1.9.21 deep-review batch (Fable 5
#              review, 16-07-2026): per-type _HANDLED_KEYS capture (smoke/
#              vibration/tamper/voltage/current no longer silently dropped),
#              smoke -> onOffState semantics, _payload_bool string tokens,
#              button/cover classification gates, reclassify-gate motion/pir
#              extension, ieee_map repoint on reclassify, bridge/devices
#              rename + prefix-migration + auto-create paths, and the
#              getDeviceStateList dynamic-state declarations (previously
#              untestable — the stub gained the state-dict builders).
# Author:      CliveS & Claude Fable 5
# Date:        16-07-2026
# Version:     1.0

import json

import pytest


# ── _payload_bool — string-token coercion ─────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False),
    (1, True), (0, False), (0.0, False), (2.5, True),
    ("true", True), ("True", True), ("ON", True), ("yes", True), ("1", True),
    ("false", False), ("OFF", False), ("no", False), ("0", False), ("", False),
    ("weird", None), (None, None), ({"x": 1}, None),
])
def test_payload_bool_tokens(plugin_mod, raw, expected):
    assert plugin_mod._payload_bool(raw) is expected


# ── smoke semantics on the generic sensor ─────────────────────────────────────

def test_smoke_true_writes_state_and_onoff(plugin, make_device):
    dev = make_device(101, "Smoke Alarm", "z2mSensor")
    plugin._process_sensor_state(dev, {"smoke": True})
    assert dev.states["smoke"] is True
    assert dev.states["onOffState"] is True
    ui = {k: u for k, _v, u in dev.state_writes}
    assert ui["onOffState"] == "Smoke!"


def test_smoke_false_clears_onoff(plugin, make_device):
    dev = make_device(102, "Smoke Alarm", "z2mSensor")
    plugin._process_sensor_state(dev, {"smoke": False})
    assert dev.states["smoke"] is False
    assert dev.states["onOffState"] is False


def test_smoke_string_false_not_read_as_true(plugin, make_device):
    # raw bool("false") would be True — _payload_bool must not.
    dev = make_device(103, "Smoke Alarm", "z2mSensor")
    plugin._process_sensor_state(dev, {"smoke": "false"})
    assert dev.states["smoke"] is False
    assert dev.states["onOffState"] is False


def test_smoke_unrecognisable_value_skipped(plugin, make_device):
    dev = make_device(104, "Smoke Alarm", "z2mSensor")
    plugin._process_sensor_state(dev, {"smoke": "sometimes"})
    assert "smoke" not in dev.states
    assert "onOffState" not in dev.states


def test_smoke_outranks_water_leak_for_onoff(plugin, make_device):
    dev = make_device(105, "Combo", "z2mSensor")
    plugin._process_sensor_state(dev, {"smoke": True, "water_leak": False})
    assert dev.states["onOffState"] is True
    ui = {k: u for k, _v, u in dev.state_writes}
    assert ui["onOffState"] == "Smoke!"


def test_water_leak_still_drives_onoff_without_smoke(plugin, make_device):
    dev = make_device(106, "Leak", "z2mSensor")
    plugin._process_sensor_state(dev, {"water_leak": True})
    assert dev.states["onOffState"] is True
    ui = {k: u for k, _v, u in dev.state_writes}
    assert ui["onOffState"] == "Leak!"


# ── per-type dynamic capture (the _HANDLED_PAYLOAD_KEYS rework) ───────────────

def test_handled_keys_per_type(plugin_mod):
    # smoke is semantically owned by the generic sensor…
    assert "smoke" in plugin_mod._handled_keys_for("z2mSensor")
    # …but nothing else claims it, or vibration/tamper/voltage/current anywhere.
    for t in ("z2mLight", "z2mRelay", "z2mContactSensor", "z2mButton"):
        keys = plugin_mod._handled_keys_for(t)
        assert not {"vibration", "tamper", "voltage", "current"} & keys
    # linkquality is consumed for every type (written as linkQuality).
    assert "linkquality" in plugin_mod._handled_keys_for("z2mRepeater")
    # Unknown types get the conservative union fallback.
    assert "state" in plugin_mod._handled_keys_for("z2mFutureType")


def test_contact_sensor_temperature_now_captured(plugin, make_device):
    dev = make_device(110, "Door", "z2mContactSensor",
                      static_state_keys=["contact", "battery", "availability",
                                         "linkQuality"])
    plugin._capture_raw_fields(dev, {"temperature": 21.5})
    assert dev.states.get("temperature") == 21.5


def test_relay_voltage_current_now_captured(plugin, make_device):
    dev = make_device(111, "Plug", "z2mRelay",
                      static_state_keys=["power", "energy", "availability",
                                         "linkQuality"])
    plugin._capture_raw_fields(dev, {"voltage": 233.4, "current": 0.42})
    assert dev.states.get("voltage") == 233.4
    assert dev.states.get("current") == 0.42


def test_light_power_now_captured(plugin, make_device):
    dev = make_device(112, "Bulb", "z2mLight",
                      static_state_keys=["colorMode", "colorTemp",
                                         "availability", "linkQuality"])
    plugin._capture_raw_fields(dev, {"power": 5.2})
    assert dev.states.get("power") == 5.2


def test_sensor_vibration_tamper_now_captured(plugin, make_device):
    dev = make_device(113, "Shaker", "z2mSensor",
                      static_state_keys=["availability", "linkQuality"])
    plugin._capture_raw_fields(dev, {"vibration": True, "tamper": False})
    assert dev.states.get("vibration") is True
    assert dev.states.get("tamper") is False


def test_linkquality_never_captured_dynamically(plugin, make_device):
    dev = make_device(114, "Any", "z2mRepeater",
                      static_state_keys=["availability", "linkQuality"])
    plugin._capture_raw_fields(dev, {"linkquality": 120})
    assert "linkquality" not in dev.states


# ── reclassify gate — motion/pir extension ────────────────────────────────────

def _bridge_entry(ieee, fname, exposes):
    return {ieee: {"ieee_address": ieee, "friendly_name": fname,
                   "definition": {"exposes": exposes}}}


def test_reclassify_gate_blocks_motion_devices(plugin, make_device):
    dev = make_device(120, "Hall Motion", "z2mSensor",
                      pluginProps={"ieee_address": "0xm1",
                                   "friendly_name": "Hall Motion"})
    plugin.bridge_devices = _bridge_entry("0xm1", "Hall Motion", [
        {"name": "motion", "type": "binary", "access": 1},
        {"name": "action", "type": "enum", "access": 1, "values": ["motion_x"]},
    ])
    assert plugin._should_reclassify_as_button(dev) is False


def test_reclassify_gate_still_allows_pure_button(plugin, make_device):
    dev = make_device(121, "Puck", "z2mSensor",
                      pluginProps={"ieee_address": "0xb1",
                                   "friendly_name": "Puck"})
    plugin.bridge_devices = _bridge_entry("0xb1", "Puck", [
        {"name": "action", "type": "enum", "access": 1, "values": ["single"]},
        {"name": "battery", "type": "numeric", "access": 1},
    ])
    assert plugin._should_reclassify_as_button(dev) is True


# ── reclassify repoints BOTH maps to the new device id (v1.9.18 fix, untested) ─

def test_reclassify_repoints_friendly_and_ieee_maps(plugin, make_device, monkeypatch):
    import indigo
    from indigo_stub import DeviceShim
    monkeypatch.setattr(indigo, "device", DeviceShim(indigo.devices), raising=False)

    dev = make_device(130, "Mystery Button", "z2mRelay",
                      pluginProps={"friendly_name": "Mystery Button",
                                   "ieee_address": "0xfeed"})
    plugin.friendly_name_map["Mystery Button"] = dev.id
    plugin.ieee_map["0xfeed"] = dev.id

    plugin._reclassify_as_button(dev, {"action": "single"})

    new_id = plugin.friendly_name_map.get("Mystery Button")
    assert new_id is not None and new_id != 130
    assert plugin.ieee_map.get("0xfeed") == new_id
    assert 130 not in indigo.devices._by_id          # old device deleted
    new_dev = indigo.devices[new_id]
    assert new_dev.deviceTypeId == "z2mButton"
    assert new_dev.states.get("lastAction")          # action processed on new dev
    indigo.devices._by_id.pop(new_id, None)          # cleanup


# ── bridge/devices: rename, prefix migration, auto-create ─────────────────────

def _z2m_dev(ieee, fname, dtype="Router", exposes=None, model=""):
    return {"ieee_address": ieee, "friendly_name": fname, "type": dtype,
            "definition": {"exposes": exposes or [], "model": model,
                           "vendor": "TestVendor"}}


def test_bridge_devices_rename_updates_device_and_maps(plugin, make_device):
    dev = make_device(140, "Old Name", "z2mSensor",
                      pluginProps={"friendly_name": "Old Name",
                                   "ieee_address": "0xr1",
                                   "mqtt_prefix": "zigbee2mqtt"})
    plugin.ieee_map["0xr1"] = dev.id
    plugin.friendly_name_map["Old Name"] = dev.id

    plugin._process_bridge_devices([_z2m_dev("0xr1", "New Name")],
                                   prefix="zigbee2mqtt")

    assert dev.pluginProps["friendly_name"] == "New Name"
    assert dev.name == "New Name"
    assert plugin.friendly_name_map.get("New Name") == dev.id
    assert "Old Name" not in plugin.friendly_name_map


def test_bridge_devices_prefix_migration(plugin, make_device):
    dev = make_device(141, "Garage Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Garage Sensor",
                                   "ieee_address": "0xp1",
                                   "mqtt_prefix": "zigbee2mqtt"})
    plugin.ieee_map["0xp1"] = dev.id

    plugin._process_bridge_devices([_z2m_dev("0xp1", "Garage Sensor")],
                                   prefix="garage")

    assert dev.pluginProps["mqtt_prefix"] == "garage"


def test_bridge_devices_autocreates_new_ieee(plugin, monkeypatch):
    import indigo
    from indigo_stub import DeviceShim
    monkeypatch.setattr(indigo, "device", DeviceShim(indigo.devices), raising=False)

    # Baseline for the prefix must be non-empty (startup flood guard).
    plugin.bridge_devices = {"0x1": {"ieee_address": "0x1",
                                     "friendly_name": "Existing",
                                     "_mqtt_prefix": "zigbee2mqtt"}}
    relay_exposes = [{"type": "switch",
                      "features": [{"name": "state", "type": "binary",
                                    "access": 7}]}]
    plugin._process_bridge_devices(
        [_z2m_dev("0x1", "Existing"),
         _z2m_dev("0x2", "Brand New Plug", exposes=relay_exposes, model="TS011F")],
        prefix="zigbee2mqtt")

    created = [d for d in indigo.devices if d.name == "Brand New Plug"]
    assert created, "new IEEE on a known prefix must be auto-created"
    assert created[0].deviceTypeId == "z2mRelay"
    for d in created:
        indigo.devices._by_id.pop(d.id, None)        # cleanup


def test_bridge_devices_startup_flood_guard(plugin, monkeypatch):
    import indigo
    from indigo_stub import DeviceShim
    shim = DeviceShim(indigo.devices)
    created_names = []
    real_create = shim.create

    def _tracking_create(**kwargs):
        created_names.append(kwargs.get("name"))
        return real_create(**kwargs)

    shim.create = _tracking_create
    monkeypatch.setattr(indigo, "device", shim, raising=False)

    # Empty cache -> first bridge/devices load must NOT auto-create anything.
    plugin.bridge_devices = {}
    plugin._process_bridge_devices([_z2m_dev("0x9", "Fresh Load")],
                                   prefix="zigbee2mqtt")
    assert created_names == []


# ── getDeviceStateList — dynamic declarations (previously untestable) ─────────

def test_getDeviceStateList_declares_typed_dynamic_states(plugin, make_device):
    dev = make_device(150, "Dyn", "z2mSensor",
                      pluginProps={
                          "seenDynamicKeys": "customField,mode,vibration",
                          "dynamicKeyTypes": json.dumps(
                              {"customField": "real", "mode": "str",
                               "vibration": "bool"}),
                      },
                      static_state_keys=["temperature", "linkQuality"])
    states = plugin.getDeviceStateList(dev)
    by_key = {s["Key"]: s for s in states}
    # Static states from Devices.xml survive…
    assert "temperature" in by_key
    # …and dynamic keys are declared with their persisted types.
    assert by_key["customField"]["Type"] == "Real"
    assert by_key["vibration"]["Type"] == "BoolTrueFalse"
    assert by_key["mode"]["Type"] == "String"
