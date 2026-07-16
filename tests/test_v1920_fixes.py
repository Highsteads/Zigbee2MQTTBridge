#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1920_fixes.py
# Description: Regression tests for the v1.9.20 deep-review deferred-queue batch:
#              dynamic/static state-key collision skip (#13), dimmer brightness=0
#              consistency (#16), reclassify named-action gate (#17), map-lock
#              presence (#18), orphan dynamicKeyTypes prune (#29), colour peak
#              rounding (#30), and the previously-untested seams: _drain_queue
#              per-message isolation (#23), _process_device_state dispatch (#8),
#              and deviceStartComm config guards (#24).
# Author:      CliveS & Claude Opus 4.8
# Date:        27-06-2026
# Version:     1.0

import queue
import threading

import pytest


# ── #30 colour helpers: fully-saturated channel reports 100, not 99 ──────────

def test_xy_primary_channel_peaks_at_100(plugin_mod):
    r, g, b = plugin_mod._xy_to_rgb(0.70, 0.30)      # deep red
    assert r == 100 and r >= g >= b


def test_hs_primary_channel_peaks_at_100(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(0, 255)          # pure red
    assert (r, g, b) == (100, 0, 0)
    r, g, b = plugin_mod._hs_to_rgb(120, 255)        # pure green
    assert g == 100 and g >= r and g >= b


# ── #16 dimmer brightness=0 + state ON -> onOffState forced False ────────────

def test_light_brightness_zero_forces_off(plugin, make_device):
    dev = make_device(800, "Fade Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Fade Lamp"})
    plugin._process_light_state(dev, {"state": "ON", "brightness": 0})
    assert dev.states["brightnessLevel"] == 0
    assert dev.states["onOffState"] is False, "0 brightness must read as off in Indigo"


def test_light_brightness_nonzero_stays_on(plugin, make_device):
    dev = make_device(801, "Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lamp"})
    plugin._process_light_state(dev, {"state": "ON", "brightness": 200})
    assert dev.states["brightnessLevel"] > 0
    assert dev.states["onOffState"] is True


# ── #17 reclassify only on a NAMED action (not a bare index / junk) ──────────

def _eligible_sensor(plugin, make_device, dev_id):
    dev = make_device(dev_id, "Maybe Button", "z2mSensor",
                      pluginProps={"friendly_name": "Maybe Button", "ieee_address": f"0x{dev_id}"})
    plugin.friendly_name_map[("zigbee2mqtt", "Maybe Button")] = dev.id
    plugin.bridge_devices = {}   # no exposes -> empty-exposes z2mSensor is eligible
    return dev


def test_reclassify_skips_bare_index_action(plugin, make_device, monkeypatch):
    dev = _eligible_sensor(plugin, make_device, 810)
    monkeypatch.setattr(plugin, "_should_reclassify_as_button", lambda d: True)
    monkeypatch.setattr(plugin, "_capture_raw_fields", lambda *a, **k: None)
    called = []
    monkeypatch.setattr(plugin, "_reclassify_as_button", lambda d, p: called.append(1))
    plugin._process_device_state("Maybe Button", {"action": "2"})    # bare index, no name
    assert called == [], "a bare-index action must not drive a destructive reclassify"


def test_reclassify_fires_on_named_action(plugin, make_device, monkeypatch):
    dev = _eligible_sensor(plugin, make_device, 811)
    monkeypatch.setattr(plugin, "_should_reclassify_as_button", lambda d: True)
    monkeypatch.setattr(plugin, "_capture_raw_fields", lambda *a, **k: None)
    called = []
    monkeypatch.setattr(plugin, "_reclassify_as_button", lambda d, p: called.append(1))
    plugin._process_device_state("Maybe Button", {"action": "single"})
    assert called == [1]


# ── #18 map lock exists and guarded ops still behave correctly ───────────────

def test_maps_lock_is_reentrant(plugin):
    assert isinstance(plugin.maps_lock, type(threading.RLock()))
    # RLock: the same thread may acquire twice without deadlock.
    with plugin.maps_lock:
        with plugin.maps_lock:
            pass


def test_device_stop_clears_all_maps(plugin, make_device):
    dev = make_device(820, "Gone", "z2mContactSensor",
                      pluginProps={"friendly_name": "Gone", "ieee_address": "0xgone"})
    plugin.friendly_name_map[("zigbee2mqtt", "Gone")] = dev.id
    plugin.ieee_map["0xgone"] = dev.id
    plugin._motion_states[dev.id] = {"presence": True}
    plugin.deviceStopComm(dev)
    assert ("zigbee2mqtt", "Gone") not in plugin.friendly_name_map
    assert "0xgone" not in plugin.ieee_map
    assert dev.id not in plugin._motion_states


# ── #13 dynamic field colliding with a static state is NOT captured ──────────

def test_static_collision_field_not_captured_dynamically(plugin, make_device):
    dev = make_device(830, "Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Sensor"},
                      static_state_keys=["onOffState", "linkQuality", "battery"])
    plugin._capture_raw_fields(dev, {"link_quality": 200, "custom_field": 5})
    seen = dev.pluginProps.get("seenDynamicKeys", "")
    assert "linkQuality" not in seen.split(","), "must not shadow the static linkQuality state"
    assert "customField" in seen.split(","), "genuinely-dynamic field should still be captured"
    assert dev.states.get("customField") == 5


# ── #29 orphan dynamicKeyTypes entries pruned to match seenDynamicKeys ───────

def test_orphan_dynamic_type_pruned(plugin, make_device):
    import json
    dev = make_device(840, "Drifty", "z2mSensor",
                      pluginProps={
                          "friendly_name": "Drifty",
                          "seenDynamicKeys": "customField",
                          # orphanKey is in the type map but NOT in seenDynamicKeys
                          "dynamicKeyTypes": json.dumps({"customField": "int", "orphanKey": "str"}),
                      },
                      static_state_keys=["onOffState"])
    plugin._capture_raw_fields(dev, {"custom_field": 7})
    types = json.loads(dev.pluginProps.get("dynamicKeyTypes", "{}"))
    assert "orphanKey" not in types, "orphan type entry should be pruned in lock-step with seen"
    assert "customField" in types


# ── #23 _drain_queue: one bad message logs-and-continues, liveness still runs ─

def test_drain_queue_isolates_a_bad_message(plugin, plugin_mod, monkeypatch):
    errors = []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": errors.append((level, msg)))
    processed = []

    def fake_process(topic, payload):
        if topic == "poison":
            raise RuntimeError("boom")
        processed.append(topic)

    liveness = []
    monkeypatch.setattr(plugin, "_process_message", fake_process)
    monkeypatch.setattr(plugin, "_mqtt_liveness_check", lambda: liveness.append(1))

    plugin.msg_queue = queue.Queue()
    plugin.msg_queue.put(("poison", {}))
    plugin.msg_queue.put(("good", {}))

    plugin._drain_queue()   # must NOT raise

    assert processed == ["good"], "a poison message must not stop the rest of the drain"
    assert liveness == [1], "liveness check still runs after a bad message"
    assert any(lvl == "ERROR" for lvl, _ in errors)


def test_drain_queue_liveness_error_isolated(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "log", lambda *a, **k: None)
    monkeypatch.setattr(plugin, "_mqtt_liveness_check",
                        lambda: (_ for _ in ()).throw(RuntimeError("rebuild boom")))
    plugin.msg_queue = queue.Queue()
    plugin._drain_queue()   # a liveness exception must not escape / kill the thread


# ── #8 _process_device_state dispatch routes each type to its handler ─────────

DISPATCH = [
    ("z2mLight",            "_process_light_state"),
    ("z2mRelay",            "_process_relay_state"),
    ("z2mContactSensor",    "_process_contact_sensor_state"),
    ("z2mOccupancySensor",  "_process_occupancy_sensor_state"),
    ("z2mWaterLeakSensor",  "_process_water_leak_sensor_state"),
    ("z2mTemperatureSensor", "_process_temperature_sensor_state"),
    ("z2mSensor",           "_process_sensor_state"),
    ("z2mRepeater",         "_process_repeater_state"),
    ("z2mCover",            "_process_cover_state"),
    ("z2mButton",           "_process_button_state"),
]


@pytest.mark.parametrize("type_id,handler", DISPATCH)
def test_dispatch_routes_to_correct_handler(plugin, make_device, monkeypatch, type_id, handler):
    fired = []
    for _t, h in DISPATCH:
        monkeypatch.setattr(plugin, h, (lambda hh: (lambda dev, payload: fired.append(hh)))(h))
    monkeypatch.setattr(plugin, "_capture_raw_fields", lambda *a, **k: None)
    monkeypatch.setattr(plugin, "_should_reclassify_as_button", lambda d: False)

    dev = make_device(850, "Dev", type_id, pluginProps={"friendly_name": "Dev"})
    plugin.friendly_name_map[("zigbee2mqtt", "Dev")] = dev.id
    plugin._process_device_state("Dev", {"state": "ON"})

    assert fired == [handler], f"{type_id} should route only to {handler}, got {fired}"


def test_dispatch_unknown_friendly_name_is_noop(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_capture_raw_fields", lambda *a, **k: None)
    # No device registered under this name -> early return, no exception.
    plugin._process_device_state("Nobody", {"state": "ON"})


# ── #24 deviceStartComm config-guard paths ───────────────────────────────────

def test_device_start_blank_friendly_name_skips(plugin, make_device):
    dev = make_device(860, "Blank", "z2mContactSensor",
                      pluginProps={"friendly_name": "  "})   # blank after strip
    plugin.deviceStartComm(dev)   # must not raise
    assert dev.id not in plugin.friendly_name_map.values()


def test_coordinator_blank_prefix_skips(plugin, make_device):
    dev = make_device(861, "Coord", "z2mCoordinator",
                      pluginProps={"mqtt_prefix": ""})
    plugin.deviceStartComm(dev)   # must not raise
    assert dev.id not in plugin.coordinator_map.values()


def test_coordinator_replays_cached_bridge_info(plugin, make_device, monkeypatch):
    replayed = []
    monkeypatch.setattr(plugin, "_process_bridge_info",
                        lambda info, prefix: replayed.append(("info", prefix)))
    monkeypatch.setattr(plugin, "_ensure_device_states", lambda dev: None)
    plugin._bridge_info_cache["zigbee2mqtt"] = {"version": "1.x"}
    dev = make_device(862, "Coord2", "z2mCoordinator",
                      pluginProps={"mqtt_prefix": "zigbee2mqtt"})
    plugin.deviceStartComm(dev)
    assert ("info", "zigbee2mqtt") in replayed
    assert plugin.coordinator_map.get("zigbee2mqtt") == dev.id
