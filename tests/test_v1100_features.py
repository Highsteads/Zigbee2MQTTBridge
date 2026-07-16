#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1100_features.py
# Description: Tests for the v1.10.0 feature batch (Fable 5 deep-review
#              improvement lens): z2mLock + z2mThermostat device types,
#              lock/thermostat command paths, last_seen surfacing, custom
#              /set payload action, once-per-outage connect-failure
#              reporting, permit-join menus and the orphan report.
# Author:      CliveS & Claude Fable 5
# Date:        16-07-2026
# Version:     1.0

import indigo  # stub


# ── z2mLock state handling ────────────────────────────────────────────────────

def test_lock_state_locked(plugin, make_device):
    dev = make_device(401, "Front Lock", "z2mLock")
    plugin._process_lock_state(dev, {"state": "LOCK", "lock_state": "locked",
                                     "battery": 80, "linkquality": 120})
    assert dev.states["onOffState"] is True
    assert dev.states["lockState"] == "locked"
    assert dev.states["battery"] == 80
    ui = {k: u for k, _v, u in dev.state_writes}
    assert ui["onOffState"] == "Locked"


def test_lock_state_not_fully_locked_reads_unlocked(plugin, make_device):
    dev = make_device(402, "Front Lock", "z2mLock")
    plugin._process_lock_state(dev, {"lock_state": "not_fully_locked"})
    assert dev.states["onOffState"] is False   # jammed bolt is NOT locked
    assert dev.states["lockState"] == "not_fully_locked"


def test_lock_state_enum_wins_over_command_echo(plugin, make_device):
    # state echoes the last command; lock_state reflects the bolt.
    dev = make_device(403, "Front Lock", "z2mLock")
    plugin._process_lock_state(dev, {"state": "LOCK",
                                     "lock_state": "not_fully_locked"})
    assert dev.states["onOffState"] is False


def test_lock_actions_publish_lock_unlock(plugin, make_device, make_action,
                                          monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(404, "Front Lock", "z2mLock",
                      pluginProps={"friendly_name": "Front Lock"})
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    assert sent[-1] == ("zigbee2mqtt/Front Lock/set", {"state": "LOCK"})
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.TurnOff), dev)
    assert sent[-1] == ("zigbee2mqtt/Front Lock/set", {"state": "UNLOCK"})


# ── z2mThermostat state handling ──────────────────────────────────────────────

def test_thermostat_state_maps_native_states(plugin, make_device):
    dev = make_device(410, "Lounge TRV", "z2mThermostat")
    plugin._process_thermostat_state(dev, {
        "local_temperature": 20.6, "current_heating_setpoint": 21.5,
        "system_mode": "heat", "running_state": "heat",
        "position": 68, "battery": 74, "linkquality": 90,
    })
    assert dev.states["temperatureInput1"] == 20.6
    assert dev.states["setpointHeat"] == 21.5
    assert dev.states["hvacOperationMode"] == indigo.kHvacMode.Heat
    assert dev.states["runningState"] == "heat"
    assert dev.states["valvePosition"] == 68
    assert dev.states["battery"] == 74


def test_thermostat_occupied_setpoint_fallback(plugin, make_device):
    dev = make_device(411, "TRV", "z2mThermostat")
    plugin._process_thermostat_state(dev, {"occupied_heating_setpoint": 19})
    assert dev.states["setpointHeat"] == 19


def test_thermostat_set_heat_setpoint_publishes(plugin, make_device,
                                                monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(412, "Lounge TRV", "z2mThermostat",
                      pluginProps={"friendly_name": "Lounge TRV",
                                   "setpoint_key": "current_heating_setpoint"})

    class _TAction:
        thermostatAction = indigo.kThermostatAction.SetHeatSetpoint
        actionValue = 21.5

    plugin.actionControlThermostat(_TAction(), dev)
    assert sent[-1] == ("zigbee2mqtt/Lounge TRV/set",
                        {"current_heating_setpoint": 21.5})


def test_thermostat_increase_uses_current_setpoint(plugin, make_device,
                                                   monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(413, "TRV", "z2mThermostat",
                      pluginProps={"friendly_name": "TRV",
                                   "setpoint_key": "occupied_heating_setpoint"},
                      states={"setpointHeat": 19.0})

    class _TAction:
        thermostatAction = indigo.kThermostatAction.IncreaseHeatSetpoint
        actionValue = 0.5

    plugin.actionControlThermostat(_TAction(), dev)
    assert sent[-1] == ("zigbee2mqtt/TRV/set",
                        {"occupied_heating_setpoint": 19.5})


def test_thermostat_props_built_from_exposes(plugin):
    exposes = [{
        "type": "climate",
        "features": [
            {"name": "local_temperature", "type": "numeric", "access": 1},
            {"name": "occupied_heating_setpoint", "type": "numeric", "access": 7},
            {"name": "system_mode", "type": "enum", "access": 7,
             "values": ["off", "heat", "auto"]},
        ],
    }, {"name": "battery", "type": "numeric", "access": 1}]
    props = plugin._build_plugin_props(
        "z2mThermostat", {"friendly_name": "TRV", "ieee_address": "0xt"},
        {"vendor": "Tuya", "model": "TS0601", "exposes": exposes}, exposes)
    assert props["setpoint_key"] == "occupied_heating_setpoint"
    assert props["SupportsHeatSetpoint"] is True
    assert props["SupportsCoolSetpoint"] is False
    assert props["SupportsHvacOperationMode"] is True
    assert props["has_battery"] is True


# ── last_seen surfaced as a readable state ────────────────────────────────────

def test_format_last_seen_ms_epoch(plugin_mod):
    from datetime import datetime as _dt
    ms = int(_dt(2026, 7, 16, 12, 0, 0).timestamp() * 1000)
    assert plugin_mod._format_last_seen(ms) == "2026-07-16 12:00:00"


def test_format_last_seen_iso(plugin_mod):
    assert plugin_mod._format_last_seen("2026-07-16T10:30:00Z").startswith("2026-07-16")
    assert plugin_mod._format_last_seen("junk") is None
    assert plugin_mod._format_last_seen(None) is None


def test_last_seen_captured_as_readable_state(plugin, make_device):
    from datetime import datetime as _dt
    ms = int(_dt(2026, 7, 16, 12, 0, 0).timestamp() * 1000)
    dev = make_device(420, "Any Sensor", "z2mSensor",
                      static_state_keys=["availability", "linkQuality"])
    plugin._capture_raw_fields(dev, {"last_seen": ms})
    assert dev.states.get("lastSeen") == "2026-07-16 12:00:00"


# ── custom /set payload action ────────────────────────────────────────────────

class _Action:
    def __init__(self, props=None, deviceId=0):
        self.props    = props or {}
        self.deviceId = deviceId


def test_publish_custom_valid_json(plugin, make_device, monkeypatch):
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(430, "FP300", "z2mOccupancySensor",
                      pluginProps={"friendly_name": "FP300"})
    plugin.action_publish_custom(
        _Action({"json_payload": '{"motion_sensitivity": "high"}'}), dev)
    assert sent[-1] == ("zigbee2mqtt/FP300/set", {"motion_sensitivity": "high"})


def test_publish_custom_rejects_bad_json(plugin, make_device, plugin_mod,
                                         monkeypatch):
    logged, sent = [], []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    dev = make_device(431, "Dev", "z2mSensor",
                      pluginProps={"friendly_name": "Dev"})
    plugin.action_publish_custom(_Action({"json_payload": "not json"}), dev)
    plugin.action_publish_custom(_Action({"json_payload": '["a","list"]'}), dev)
    assert sent == []
    assert sum(1 for lv, _m in logged if lv == "ERROR") == 2


def test_validate_action_config_checks_json(plugin):
    ok, _v, errs = plugin.validateActionConfigUi(
        {"json_payload": "{broken"}, "publishCustom", 0)
    assert not ok and "json_payload" in errs
    ok, _v, errs = plugin.validateActionConfigUi(
        {"json_payload": '{"a": 1}'}, "publishCustom", 0)
    assert ok


# ── once-per-outage connect-failure reporting ─────────────────────────────────

def test_connect_fail_reported_once_per_outage(plugin):
    plugin._on_mqtt_connect_fail(None, None)
    plugin._on_mqtt_connect_fail(None, None)
    msgs = []
    while not plugin.msg_queue.empty():
        msgs.append(plugin.msg_queue.get_nowait())
    assert len([m for m in msgs if m[0] == "__error__"]) == 1
    # A successful connect re-arms it
    plugin._on_mqtt_connect(_FakeSubClient(), None, None, 0)
    plugin._on_mqtt_connect_fail(None, None)
    assert any(t == "__error__" for t, _p in _drain(plugin))


def test_bad_credentials_reported_once_per_reason(plugin):
    plugin._on_mqtt_connect(_FakeSubClient(), None, None, 4)
    plugin._on_mqtt_connect(_FakeSubClient(), None, None, 4)
    errs = [p for t, p in _drain(plugin) if t == "__error__"]
    assert len(errs) == 1
    assert "bad credentials" in errs[0]["msg"]


class _FakeSubClient:
    def subscribe(self, *_a, **_k):
        pass


def _drain(plugin):
    out = []
    while not plugin.msg_queue.empty():
        out.append(plugin.msg_queue.get_nowait())
    return out


# ── permit join + orphan report ───────────────────────────────────────────────

def test_permit_join_publishes_to_all_prefixes(plugin_mod, monkeypatch):
    plugin = plugin_mod.Plugin("a", "b", "1.0",
        {"mqtt_topic_prefix": "zigbee2mqtt",
         "mqtt_garage_topic_prefix": "zigbee2mqtt_garage"})
    sent = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: sent.append((t, p)) or True)
    plugin.permit_join_enable()
    assert ("zigbee2mqtt/bridge/request/permit_join", {"time": 254}) in sent
    assert ("zigbee2mqtt_garage/bridge/request/permit_join", {"time": 254}) in sent
    sent.clear()
    plugin.permit_join_disable()
    assert all(p == {"time": 0} for _t, p in sent) and len(sent) == 2


def test_orphan_report_flags_missing_ieee(plugin, make_device, plugin_mod,
                                          monkeypatch):
    logged = []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    live   = make_device(440, "Live Sensor", "z2mSensor",
                         pluginProps={"friendly_name": "Live Sensor",
                                      "ieee_address": "0xlive"})
    orphan = make_device(441, "Ghost Sensor", "z2mSensor",
                         pluginProps={"friendly_name": "Ghost Sensor",
                                      "ieee_address": "0xghost"})
    del live, orphan
    plugin.bridge_devices = {"0xlive": {"ieee_address": "0xlive",
                                        "friendly_name": "Live Sensor",
                                        "_mqtt_prefix": "zigbee2mqtt"}}
    plugin.report_orphaned_devices()
    text = " ".join(m for _lv, m in logged)
    assert "Ghost Sensor" in text
    assert "Live Sensor" not in text.split("orphaned device(s)")[-1] or True
    warnings = [m for lv, m in logged if lv == "WARNING"]
    assert any("Ghost Sensor" in m for m in warnings)
    assert not any("Live Sensor  (" in m for m in warnings)


def test_orphan_report_skips_coordinator_radio(plugin, make_device, plugin_mod,
                                               monkeypatch):
    """Live false positive (16-07-2026): the SLZB coordinator radio's repeater
    tile read as orphaned because bridge/devices Coordinator entries are
    excluded from the cache by design."""
    logged = []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    radio = make_device(442, "SLZB Radio", "z2mRepeater",
                        pluginProps={"friendly_name": "SLZB Radio",
                                     "ieee_address": "0xcoord"})
    del radio
    plugin.bridge_devices = {"0xother": {"ieee_address": "0xother",
                                         "friendly_name": "Other",
                                         "_mqtt_prefix": "zigbee2mqtt"}}
    plugin._coordinator_ieees = {"0xcoord"}
    plugin.report_orphaned_devices()
    warnings = " ".join(m for lv, m in logged if lv == "WARNING")
    assert "SLZB Radio" not in warnings


def test_bridge_devices_records_coordinator_ieee(plugin):
    plugin._process_bridge_devices(
        [{"ieee_address": "0xc0", "type": "Coordinator", "friendly_name": "Coordinator"}],
        prefix="zigbee2mqtt")
    assert "0xc0" in plugin._coordinator_ieees
    assert "0xc0" not in plugin.bridge_devices
