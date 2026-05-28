#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_dynamic_state_types.py
# Description: Unit tests for dynamic-state TYPE inference — _infer_state_type,
#              _merge_state_type, _coerce_dynamic_value, _load_dynamic_types and
#              the type-persistence behaviour of _capture_raw_fields. Ensures
#              captured payload fields are declared with the correct Indigo state
#              type (Integer / Real / BoolOnOff / BoolTrueFalse) rather than all
#              String, and that existing String states migrate cleanly.
# Author:      CliveS & Claude Opus 4.7
# Date:        28-05-2026
# Version:     1.0

import json


# ── _infer_state_type ─────────────────────────────────────────────────────────

def test_infer_bool(plugin):
    assert plugin._infer_state_type(True) == "bool"
    assert plugin._infer_state_type(False) == "bool"


def test_infer_int_not_bool(plugin):
    # bool is a subclass of int — must NOT be classed as int
    assert plugin._infer_state_type(3) == "int"
    assert plugin._infer_state_type(0) == "int"


def test_infer_real(plugin):
    assert plugin._infer_state_type(24.5) == "real"
    assert plugin._infer_state_type(-1.0) == "real"


def test_infer_onoff(plugin):
    assert plugin._infer_state_type("ON") == "onoff"
    assert plugin._infer_state_type("off") == "onoff"
    assert plugin._infer_state_type("  On  ") == "onoff"


def test_infer_str(plugin):
    assert plugin._infer_state_type("previous") == "str"
    assert plugin._infer_state_type("LOCK") == "str"        # not ON/OFF
    assert plugin._infer_state_type({"a": 1}) == "str"
    assert plugin._infer_state_type([1, 2]) == "str"


# ── _merge_state_type ─────────────────────────────────────────────────────────

def test_merge_same(plugin):
    for t in ("bool", "int", "real", "onoff", "str"):
        assert plugin._merge_state_type(t, t) == t


def test_merge_int_real_widens_to_real(plugin):
    assert plugin._merge_state_type("int", "real") == "real"
    assert plugin._merge_state_type("real", "int") == "real"


def test_merge_drift_falls_back_to_str(plugin):
    assert plugin._merge_state_type("bool", "int") == "str"
    assert plugin._merge_state_type("onoff", "str") == "str"
    assert plugin._merge_state_type("onoff", "int") == "str"
    assert plugin._merge_state_type("bool", "onoff") == "str"


# ── _coerce_dynamic_value ─────────────────────────────────────────────────────

def test_coerce_bool(plugin):
    assert plugin._coerce_dynamic_value(True, "bool") is True
    assert plugin._coerce_dynamic_value(0, "bool") is False


def test_coerce_onoff_to_real_bool(plugin):
    assert plugin._coerce_dynamic_value("ON", "onoff") is True
    assert plugin._coerce_dynamic_value("off", "onoff") is False


def test_coerce_int(plugin):
    assert plugin._coerce_dynamic_value(3, "int") == 3
    assert isinstance(plugin._coerce_dynamic_value(3, "int"), int)


def test_coerce_real(plugin):
    v = plugin._coerce_dynamic_value(2, "real")
    assert v == 2.0 and isinstance(v, float)


def test_coerce_str(plugin):
    assert plugin._coerce_dynamic_value("previous", "str") == "previous"


def test_coerce_dict_to_json(plugin):
    out = plugin._coerce_dynamic_value({"a": 1}, "str")
    assert json.loads(out) == {"a": 1}


# ── _load_dynamic_types ───────────────────────────────────────────────────────

def test_load_types_empty(plugin, make_device):
    dev = make_device(300, "Dev", "z2mSensor", pluginProps={})
    assert plugin._load_dynamic_types(dev) == {}


def test_load_types_valid(plugin, make_device):
    dev = make_device(301, "Dev", "z2mSensor",
                      pluginProps={"dynamicKeyTypes": '{"deviceTemperature":"real"}'})
    assert plugin._load_dynamic_types(dev) == {"deviceTemperature": "real"}


def test_load_types_corrupt_returns_empty(plugin, make_device):
    dev = make_device(302, "Dev", "z2mSensor",
                      pluginProps={"dynamicKeyTypes": "not json"})
    assert plugin._load_dynamic_types(dev) == {}


# ── _capture_raw_fields — type persistence + typed writes ─────────────────────

def _writes_dict(dev):
    return {k: v for (k, v, _ui) in dev.state_writes}


def test_capture_persists_inferred_types(plugin, make_device):
    dev = make_device(310, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    # NB: payload keys must NOT be in _HANDLED_PAYLOAD_KEYS (those are routed to
    # type-specific dispatchers and are deliberately skipped by _capture_raw_fields).
    # child_lock / device_temperature / restart_count / led_state /
    # power_on_behavior are all genuinely dynamic (un-handled) fields.
    plugin._capture_raw_fields(dev, {
        "child_lock":         True,        # bool
        "device_temperature": 24.5,        # real
        "restart_count":      3,           # int
        "led_state":          "ON",        # onoff -> bool
        "power_on_behavior":  "previous",  # str
    })
    types = json.loads(dev.pluginProps["dynamicKeyTypes"])
    assert types["childLock"]         == "bool"
    assert types["deviceTemperature"] == "real"
    assert types["restartCount"]      == "int"
    assert types["ledState"]          == "onoff"
    assert types["powerOnBehavior"]   == "str"

    w = _writes_dict(dev)
    assert w["childLock"] is True
    assert w["deviceTemperature"] == 24.5 and isinstance(w["deviceTemperature"], float)
    assert w["restartCount"] == 3 and isinstance(w["restartCount"], int)
    assert w["ledState"] is True            # "ON" coerced to a real bool
    assert w["powerOnBehavior"] == "previous"


def test_capture_migrates_legacy_string_state(plugin, make_device):
    """A device seen before dynamicKeyTypes existed (no type map, value stored as
    a String) must adopt the proper type on the next payload."""
    dev = make_device(311, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": "deviceTemperature"},
                      states={"deviceTemperature": "24.5"})
    plugin._capture_raw_fields(dev, {"device_temperature": 24.5})
    types = json.loads(dev.pluginProps["dynamicKeyTypes"])
    assert types["deviceTemperature"] == "real"
    w = _writes_dict(dev)
    assert w["deviceTemperature"] == 24.5 and isinstance(w["deviceTemperature"], float)


def test_capture_type_drift_widens_int_to_real(plugin, make_device):
    # "distance" is a genuinely dynamic field (not in _HANDLED_PAYLOAD_KEYS,
    # unlike "current"/"power"/"voltage" which are routed to metering handlers).
    dev = make_device(312, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"distance": 1})        # int first
    assert json.loads(dev.pluginProps["dynamicKeyTypes"])["distance"] == "int"
    plugin._capture_raw_fields(dev, {"distance": 1.5})      # float later -> real
    assert json.loads(dev.pluginProps["dynamicKeyTypes"])["distance"] == "real"
    w = _writes_dict(dev)
    assert w["distance"] == 1.5 and isinstance(w["distance"], float)


def test_capture_drift_to_string_when_incompatible(plugin, make_device):
    dev = make_device(313, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"mode": True})        # bool first
    assert json.loads(dev.pluginProps["dynamicKeyTypes"])["mode"] == "bool"
    plugin._capture_raw_fields(dev, {"mode": 5})           # int later -> str
    assert json.loads(dev.pluginProps["dynamicKeyTypes"])["mode"] == "str"
