#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1923_fixes.py
# Description: Regression tests for the v1.9.23 deep-review batch (Fable 5
#              review, 16-07-2026, lows/infos): repeater command guard,
#              colorMode capability gate, rename-collision resilience,
#              reclassify has_battery derivation, warn-once state-write
#              failures, prefs validation, string-token binary payloads on
#              the per-type handlers, capability-gated /get payloads, and the
#              previously-untested Actions.xml callbacks (#52) and
#              not-connected error paths (#53).
# Author:      CliveS & Claude Fable 5
# Date:        16-07-2026
# Version:     1.0

import indigo  # stub


# ── repeater command guard ────────────────────────────────────────────────────

def test_repeater_rejects_on_off_commands(plugin, make_device, make_action,
                                          monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append(t) or True)
    dev = make_device(301, "Hall Repeater", "z2mRepeater",
                      pluginProps={"friendly_name": "Hall Repeater"})
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    assert sent == [], "a repeater must not receive /set commands"


def test_repeater_still_answers_status_request(plugin, make_device, make_action,
                                               monkeypatch):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append(t) or True)
    dev = make_device(302, "Hall Repeater", "z2mRepeater",
                      pluginProps={"friendly_name": "Hall Repeater"})
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.RequestStatus), dev)
    assert any(t.endswith("/get") for t in sent)


# ── colorMode gated on colour capability ──────────────────────────────────────

def test_colormode_not_written_on_plain_dimmer(plugin, make_device):
    dev = make_device(303, "Plain Bulb", "z2mLight")   # no colour caps
    plugin._process_light_state(dev, {"state": "ON", "color_mode": "color_temp"})
    assert "colorMode" not in dev.states


def test_colormode_written_on_ct_bulb(plugin, make_device):
    dev = make_device(304, "CT Bulb", "z2mLight",
                      pluginProps={"has_color_temp": True})
    dev.supportsWhiteTemperature = True
    plugin._process_light_state(dev, {"state": "ON", "color_mode": "color_temp"})
    assert dev.states.get("colorMode") == "color_temp"


# ── rename collision keeps routing intact ─────────────────────────────────────

def test_rename_collision_keeps_map_on_new_name(plugin, make_device):
    dev = make_device(305, "Old", "z2mSensor",
                      pluginProps={"friendly_name": "Old",
                                   "ieee_address": "0xrc1",
                                   "mqtt_prefix": "zigbee2mqtt"})
    plugin.ieee_map["0xrc1"] = dev.id
    plugin.friendly_name_map[("zigbee2mqtt", "Old")] = dev.id

    def _boom():
        raise ValueError("duplicate name")
    dev.replaceOnServer = _boom

    plugin._process_bridge_devices(
        [{"ieee_address": "0xrc1", "friendly_name": "New", "type": "Router",
          "definition": {"exposes": []}}], prefix="zigbee2mqtt")

    # Indigo rename failed, but props + map must still follow z2m
    assert dev.pluginProps["friendly_name"] == "New"
    assert plugin.friendly_name_map.get(("zigbee2mqtt", "New")) == dev.id
    assert ("zigbee2mqtt", "Old") not in plugin.friendly_name_map


# ── reclassify derives has_battery from current exposes ──────────────────────

def test_reclassify_derives_has_battery(plugin, make_device, monkeypatch):
    from indigo_stub import DeviceShim
    monkeypatch.setattr(indigo, "device", DeviceShim(indigo.devices),
                        raising=False)
    dev = make_device(306, "Batt Button", "z2mSensor",
                      pluginProps={"friendly_name": "Batt Button",
                                   "ieee_address": "0xbb1"})
    plugin.bridge_devices = {"0xbb1": {
        "ieee_address": "0xbb1", "friendly_name": "Batt Button",
        "definition": {"exposes": [
            {"name": "action",  "type": "enum", "access": 1, "values": ["single"]},
            {"name": "battery", "type": "numeric", "access": 1}]},
    }}
    plugin._reclassify_as_button(dev, {"action": "single"})
    new_id = plugin.friendly_name_map.get(("zigbee2mqtt", "Batt Button"))
    assert new_id is not None
    new_dev = indigo.devices[new_id]
    assert new_dev.pluginProps.get("has_battery") is True
    indigo.devices._by_id.pop(new_id, None)


# ── _apply_updates warns once per (device, state) ─────────────────────────────

def test_apply_updates_warns_once_per_state(plugin, make_device, plugin_mod,
                                            monkeypatch, helpers_mod):
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    dev = make_device(307, "Strict", "z2mSensor",
                      static_state_keys=["temperature"])
    dev.strict_states = True
    plugin._apply_updates(dev, [("ghostState", 1)])
    plugin._apply_updates(dev, [("ghostState", 2)])
    warnings = [m for lv, m in logged if lv == "WARNING" and "ghostState" in m]
    assert len(warnings) == 1, "first failure WARNS, repeats stay quiet"


# ── prefs validation ──────────────────────────────────────────────────────────

def test_validate_prefs_rejects_bad_port_and_limit(plugin):
    ok, _vals, errs = plugin.validatePrefsConfigUi(
        {"mqtt_topic_prefix": "zigbee2mqtt", "mqtt_port": "banana",
         "mqtt_silence_limit": "5"})
    assert not ok
    assert "mqtt_port" in errs
    assert "mqtt_silence_limit" in errs


def test_validate_prefs_accepts_good_values(plugin):
    ok, _vals, errs = plugin.validatePrefsConfigUi(
        {"mqtt_topic_prefix": "zigbee2mqtt", "mqtt_port": "1883",
         "mqtt_silence_limit": "600"})
    assert ok and len(errs) == 0


# ── string-token binary payloads on per-type handlers ─────────────────────────

def test_contact_string_false_not_true(plugin, make_device):
    dev = make_device(308, "Door", "z2mContactSensor")
    plugin._process_contact_sensor_state(dev, {"contact": "false"})
    assert dev.states["contact"] is False
    assert dev.states["onOffState"] is True   # contact False = open = triggered


def test_water_leak_string_false_not_true(plugin, make_device):
    dev = make_device(309, "Leak", "z2mWaterLeakSensor")
    plugin._process_water_leak_sensor_state(dev, {"water_leak": "OFF"})
    assert dev.states["waterLeak"] is False
    assert dev.states["onOffState"] is False


def test_occupancy_string_tokens_safe(plugin, make_device):
    dev = make_device(310, "PIR", "z2mOccupancySensor",
                      pluginProps={"has_pir": True})
    plugin._process_occupancy_sensor_state(dev, {"occupancy": "false"})
    assert dev.states["onOffState"] is False


# ── capability-gated /get payloads ────────────────────────────────────────────

def test_request_state_gates_colour_fields(plugin, monkeypatch):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    # Plain dimmable bulb: no colour keys requested
    plugin._request_state("Plain", "z2mLight", "zigbee2mqtt",
                          dev_props={"has_color_temp": False,
                                     "has_color": False})
    assert sent[-1][1] == {"state": "", "brightness": ""}
    # CT bulb: color_temp + color_mode but no color
    plugin._request_state("CT", "z2mLight", "zigbee2mqtt",
                          dev_props={"has_color_temp": True,
                                     "has_color": False})
    assert "color_temp" in sent[-1][1] and "color_mode" in sent[-1][1]
    assert "color" not in sent[-1][1]
    # Legacy call without props still requests everything (safe fallback)
    plugin._request_state("Legacy", "z2mLight", "zigbee2mqtt")
    assert "color" in sent[-1][1]


# ── Actions.xml callbacks (#52 — first coverage) ──────────────────────────────

class _Action:
    def __init__(self, props=None, deviceId=0):
        self.props    = props or {}
        self.deviceId = deviceId


def test_action_set_color_temperature_publishes_mireds(plugin, make_device,
                                                       monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(320, "CT Bulb", "z2mLight",
                      pluginProps={"friendly_name": "CT Bulb",
                                   "has_color_temp": True})
    plugin.action_set_color_temperature(_Action({"kelvin": "4000"}), dev)
    topic, payload = sent[-1]
    assert topic == "zigbee2mqtt/CT Bulb/set"
    assert payload["color_temp"] == 250   # 1e6 / 4000
    assert payload["state"] == "ON"


def test_action_set_brightness_scales_and_clamps(plugin, make_device,
                                                 monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(321, "Bulb", "z2mLight",
                      pluginProps={"friendly_name": "Bulb"})
    plugin.action_set_brightness(_Action({"brightness": "150"}), dev)  # >100
    _t, payload = sent[-1]
    assert payload["brightness"] == 254   # clamped to 100% -> z2m max
    assert payload["state"] == "ON"


def test_action_set_cover_position_publishes(plugin, make_device, monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(322, "Blind", "z2mCover",
                      pluginProps={"friendly_name": "Blind"})
    plugin.action_set_cover_position(_Action({"position": "40"}), dev)
    assert sent[-1] == ("zigbee2mqtt/Blind/set", {"position": 40})


def test_action_bad_numeric_value_logs_error_not_crash(plugin, make_device,
                                                       plugin_mod, monkeypatch, helpers_mod):
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(323, "Bulb", "z2mLight",
                      pluginProps={"friendly_name": "Bulb"})
    plugin.action_set_brightness(_Action({"brightness": "up a bit"}), dev)
    assert sent == []
    assert any(lv == "ERROR" for lv, _m in logged)


# ── not-connected error paths (#53) ───────────────────────────────────────────

# _start_mqtt_locked's first line is `if mqtt is None: log(ERROR); return` — the
# paho-missing guard. Both tests below are about what happens AFTER it, so they
# must assert that paho is present rather than assume it. Without this the two
# tests passed on a Mac with paho in site-packages and failed on CI, which
# installs pytest only — the suite is deliberately paho-free (see conftest's
# FakeReasonCode), so nothing else in it noticed. Red from 02-Aug to 04-Aug-2026.
def _pretend_paho_is_installed(monkeypatch, mqtt_mod):
    """Satisfy the import guard. Neither test touches the module beyond the
    None check, so a bare sentinel is enough and keeps the suite paho-free.

    Patched on z2m_mqtt, which OWNS the handle. It used to patch plugin.py,
    which stopped meaning anything at the v2.2.0 split — and the breakage was
    invisible on any machine with paho actually installed, because the real
    module satisfied the guard regardless. CI, which has no paho, failed for
    eight consecutive runs while local stayed green."""
    monkeypatch.setattr(mqtt_mod, "mqtt", object())


def test_start_mqtt_without_broker_is_not_an_error(plugin, mqtt_mod,
                                                   monkeypatch, helpers_mod, secrets_mod):
    """First-run 'not configured' logs INFO, never ERROR (estate convention)."""
    _pretend_paho_is_installed(monkeypatch, mqtt_mod)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    monkeypatch.setattr(secrets_mod, "MQTT_BROKER", "")
    plugin.pluginPrefs["mqtt_broker"] = ""
    plugin._start_mqtt()
    assert plugin.mqtt_client is None
    broker_lines = [(lv, m) for lv, m in logged if "not configured" in m]
    assert broker_lines and all(lv == "INFO" for lv, _m in broker_lines)


def test_start_mqtt_guards_against_double_start(plugin, mqtt_mod, monkeypatch, secrets_mod):
    _pretend_paho_is_installed(monkeypatch, mqtt_mod)
    stopped = []
    monkeypatch.setattr(plugin, "_stop_mqtt_locked",
                        lambda: stopped.append(1) or setattr(
                            plugin, "mqtt_client", None))
    monkeypatch.setattr(secrets_mod, "MQTT_BROKER", "")
    plugin.pluginPrefs["mqtt_broker"] = ""
    plugin.mqtt_client = object()          # a client is already live
    plugin._start_mqtt()
    assert stopped == [1], "existing client must be stopped before a new start"


def test_start_mqtt_without_paho_is_an_error(plugin, monkeypatch, helpers_mod, mqtt_mod):
    """The guard those two step over deserves its own cover: with paho missing,
    _start_mqtt must say so at ERROR and build no client."""
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    monkeypatch.setattr(mqtt_mod, "mqtt", None)
    plugin._start_mqtt()
    assert plugin.mqtt_client is None
    assert any(lv == "ERROR" and "paho-mqtt not available" in m for lv, m in logged)
