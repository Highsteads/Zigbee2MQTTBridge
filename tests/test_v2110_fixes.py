#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2110_fixes.py
# Description: v2.11.0 — the nine faults found by the 02-10-2026 independent
#              review, each pinned by a test that fails on 2.10.0.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""Every test here was run against the 2.10.0 source first and watched fail.

The order follows the review: secondary routing, mixed smoke alarms, the
device-list request zigbee2mqtt does not support, composite settings, the
doubled firmware failure, the rename race, motion after a restart,
multi-level prefixes and the first device on an empty network."""

import json
import threading
import time
import types
from pathlib import Path

import indigo  # stub
from indigo_stub import FakeTrigger

PREFIX = "zigbee2mqtt"


def _no_state_requests(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: None)


# ── 1. a secondary device never takes its parent's routing ──────────────────

SEC_EXPOSES = [
    {"property": "presence", "type": "binary", "access": 1},
    {"property": "temperature", "type": "numeric", "access": 1},
]


def _parent_with_secondary(plugin, make_device, dev_id=2101):
    parent = make_device(dev_id, "Study Presence", "z2mOccupancySensor",
                         pluginProps={"friendly_name": "Study", "ieee_address": "0xsec",
                                      "mqtt_prefix": PREFIX, "has_presence": True,
                                      "has_temperature": True},
                         states={"presence": False, "temperature": 19.0,
                                 "onOffState": False})
    plugin.bridge_devices["0xsec"] = {
        "ieee_address": "0xsec", "friendly_name": "Study", "_mqtt_prefix": PREFIX,
        "definition": {"exposes": SEC_EXPOSES, "supports_ota": True}}
    plugin._sync_secondaries(parent, {"z2msec_temperature": "true"})
    child = indigo.devices[plugin._secondary_dev_id(parent, "temperature")]
    return parent, child


def test_starting_a_secondary_leaves_the_parent_routed(plugin, make_device, monkeypatch):
    _no_state_requests(plugin, monkeypatch)
    for first_parent in (True, False):
        plugin.friendly_name_map.clear()
        plugin.ieee_map.clear()
        parent, child = _parent_with_secondary(plugin, make_device,
                                               dev_id=2101 if first_parent else 2102)
        order = (parent, child) if first_parent else (child, parent)
        for dev in order:
            plugin.deviceStartComm(dev)
        assert plugin.friendly_name_map[(PREFIX, "Study")] == parent.id
        assert plugin.ieee_map["0xsec"] == parent.id
        indigo.devices._by_id.pop(child.id, None)
        indigo.devices._by_id.pop(parent.id, None)


def test_reports_reach_the_parent_and_then_the_secondary(plugin, make_device, monkeypatch):
    _no_state_requests(plugin, monkeypatch)
    parent, child = _parent_with_secondary(plugin, make_device)
    plugin.deviceStartComm(parent)
    plugin.deviceStartComm(child)       # Indigo starts a new device itself
    plugin._process_device_state("Study", {"presence": True, "temperature": 25.4},
                                 prefix=PREFIX)
    assert parent.states["presence"] is True
    assert parent.states["temperature"] == 25.4
    assert child.states["sensorValue"] == 25.4


def test_stopping_a_secondary_keeps_the_parents_route(plugin, make_device, monkeypatch):
    _no_state_requests(plugin, monkeypatch)
    parent, child = _parent_with_secondary(plugin, make_device)
    plugin.deviceStartComm(parent)
    plugin.deviceStartComm(child)
    plugin.deviceStopComm(child)
    assert plugin.friendly_name_map[(PREFIX, "Study")] == parent.id
    assert plugin.ieee_map["0xsec"] == parent.id


def test_a_secondary_is_not_asked_about_firmware(plugin, make_device, monkeypatch):
    _parent_with_secondary(plugin, make_device)
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append(p) or True)
    plugin.check_firmware_updates()
    assert sent == [{"id": "0xsec"}], "one radio, asked once"


# ── 2. a smoke alarm that also measures temperature is still an alarm ───────

SMOKE_228WZH = [
    {"name": "smoke", "property": "smoke", "type": "binary", "access": 1,
     "value_on": True, "value_off": False},
    {"name": "temperature", "property": "temperature", "type": "numeric", "access": 1},
    {"name": "humidity", "property": "humidity", "type": "numeric", "access": 1},
    {"name": "battery", "property": "battery", "type": "numeric", "access": 1},
]


def test_a_mixed_smoke_alarm_is_classified_as_an_alarm(plugin_mod):
    assert plugin_mod._detect_device_type(SMOKE_228WZH, "228WZH") == "z2mSensor"


def test_its_native_state_goes_on_for_smoke(plugin, make_device):
    dev = make_device(2110, "Hall Smoke", "z2mSensor",
                      pluginProps={"friendly_name": "Hall Smoke", "ieee_address": "0xsm",
                                   "mqtt_prefix": PREFIX})
    plugin.friendly_name_map[(PREFIX, "Hall Smoke")] = dev.id
    plugin._process_device_state("Hall Smoke", {"smoke": True, "temperature": 21},
                                 prefix=PREFIX)
    assert dev.states["onOffState"] is True


def test_an_alarm_created_as_a_temperature_sensor_says_so(plugin, make_device, logs):
    dev = make_device(2111, "Old Smoke", "z2mTemperatureSensor",
                      pluginProps={"friendly_name": "Old Smoke", "ieee_address": "0xsm2",
                                   "mqtt_prefix": PREFIX})
    plugin.friendly_name_map[(PREFIX, "Old Smoke")] = dev.id
    plugin._process_device_state("Old Smoke", {"smoke": True}, prefix=PREFIX)
    assert any("reports smoke" in m for m in logs.at("ERROR"))
    logs.event.clear()
    plugin._process_device_state("Old Smoke", {"smoke": False}, prefix=PREFIX)
    assert logs.at("ERROR") == []


# ── 3. no device-list request; the retained list is replayed instead ───────

class _FakeClient:
    def __init__(self):
        self.published, self.subscribed = [], []

    def publish(self, topic, payload, qos=0):
        self.published.append(topic)
        return types.SimpleNamespace(rc=0)

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)
        return (0, 1)


def _connected(plugin, prefixes=(PREFIX, "zigbee2mqtt_garage")):
    client = _FakeClient()
    plugin.mqtt_client = client
    plugin.mqtt_connected = True
    plugin._subscribed_prefixes = prefixes
    return client


def test_nothing_ever_asks_for_bridge_request_devices(plugin):
    """zigbee2mqtt 2.13.0's request table has no `devices` key and ignores
    unknown requests, so the connect fallback, the Refresh menu and the
    watchdog probe all went unanswered."""
    client = _connected(plugin)
    plugin._process_message("__connected__",
                            {"subscribed": [f"{PREFIX}/#", "zigbee2mqtt_garage/#"]})
    plugin.refresh_bridge_devices()
    plugin.last_rx_ts = time.time() - 4000
    plugin._last_mqtt_check = 0.0
    plugin._mqtt_liveness_check()
    assert not any(t.endswith("/bridge/request/devices") for t in client.published)
    assert f"{PREFIX}/bridge/request/health_check" in client.published


def test_refresh_resubscribes_so_the_broker_resends_the_list(plugin, logs):
    client = _connected(plugin)
    plugin.refresh_bridge_devices()
    assert client.subscribed == [f"{PREFIX}/#", "zigbee2mqtt_garage/#"]
    assert set(plugin._device_list_wait) == {PREFIX, "zigbee2mqtt_garage"}


def test_refresh_says_so_when_not_connected(plugin, logs):
    plugin.mqtt_client = None
    plugin.mqtt_connected = False
    plugin.refresh_bridge_devices()
    assert any("not connected" in m for m in logs.at("WARNING"))
    assert plugin._device_list_wait == {}


def test_a_list_that_arrives_clears_the_wait(plugin):
    plugin._await_device_list([PREFIX])
    plugin._process_bridge_devices([], PREFIX)
    assert plugin._device_list_wait == {}


def test_a_list_that_never_arrives_is_reported_once(plugin, logs):
    plugin._await_device_list([PREFIX])
    plugin._device_list_wait[PREFIX] -= 31
    plugin._check_device_list_wait()
    plugin._check_device_list_wait()
    warned = [m for m in logs.at("WARNING") if "No device list" in m]
    assert len(warned) == 1 and f"'{PREFIX}'" in warned[0]


def test_a_quiet_wait_says_nothing_early(plugin, logs):
    plugin._await_device_list([PREFIX])
    plugin._check_device_list_wait()
    assert logs.at("WARNING") == []


# ── 4. a composite's settings travel inside their parent ────────────────────

HUE = json.loads((Path(__file__).parent / "zoo_real" / "light_bulb.json")
                 .read_text(encoding="utf-8"))["exposes"]

COLOR_OPTIONS = [{"type": "composite", "name": "color_options",
                  "property": "color_options", "label": "Color options", "access": 7,
                  "features": [{"type": "binary", "name": "execute_if_off",
                                "property": "execute_if_off", "access": 7,
                                "value_on": True, "value_off": False}]}]


def _light(plugin, make_device, exposes, props=None, states=None, dev_id=2140):
    base = {"friendly_name": "Hue", "ieee_address": "0xhue", "mqtt_prefix": PREFIX}
    base.update(props or {})
    dev = make_device(dev_id, "Hue", "z2mLight", pluginProps=base, states=states or {})
    plugin.bridge_devices["0xhue"] = {"ieee_address": "0xhue", "friendly_name": "Hue",
                                      "_mqtt_prefix": PREFIX,
                                      "definition": {"exposes": exposes}}
    return dev


def _published(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    return out


def test_saving_a_composite_setting_sends_it_nested(plugin, make_device, monkeypatch):
    dev = _light(plugin, make_device, HUE)
    out = _published(plugin, monkeypatch)
    plugin.closedDeviceConfigUi({"z2mset_color__x": "0.4", "z2mset_color__y": "0.3"},
                                False, "z2mLight", dev.id)
    assert out == [(f"{PREFIX}/Hue/set", {"color": {"x": 0.4, "y": 0.3}})]


def test_composite_drift_is_seen_and_corrected_nested(plugin, make_device, monkeypatch):
    dev = _light(plugin, make_device, COLOR_OPTIONS,
                 props={"z2mset_color_options__execute_if_off": "true"})
    out = _published(plugin, monkeypatch)
    plugin._check_setting_drift(dev, {"color_options": {"execute_if_off": False}})
    assert out == [(f"{PREFIX}/Hue/set", {"color_options": {"execute_if_off": True}})]
    out.clear()
    plugin._check_setting_drift(dev, {"color_options": {"execute_if_off": True}})
    assert out == [], "agreement is not drift"


def test_a_top_level_setting_keeps_its_stored_name(plugin, make_device, monkeypatch):
    """Nothing already pinned may move: power_on_behavior is stored as
    z2mset_power_on_behavior, exactly as before 2.11.0."""
    dev = _light(plugin, make_device, HUE,
                 props={"z2mset_power_on_behavior": "off"})
    out = _published(plugin, monkeypatch)
    plugin._check_setting_drift(dev, {"power_on_behavior": "on"})
    assert out == [(f"{PREFIX}/Hue/set", {"power_on_behavior": "off"})]


def test_the_dialog_names_a_composite_field_by_its_path(plugin, make_device):
    dev = _light(plugin, make_device, COLOR_OPTIONS,
                 states={"colorOptions": json.dumps({"execute_if_off": True})})
    xml = plugin._build_settings_fields(dev, plugin._managed_settings_for(dev))
    assert 'id="z2mset_color_options__execute_if_off"' in xml
    assert "Color options: " in xml
    assert "Currently reporting: True." in xml


# ── 5. one failed firmware update fires one failure ─────────────────────────

def _ota_light(plugin, make_device, dev_id):
    dev = make_device(dev_id, "Porch Light", "z2mLight",
                      pluginProps={"friendly_name": "Porch", "ieee_address": "0xota9",
                                   "mqtt_prefix": PREFIX})
    plugin.ieee_map["0xota9"] = dev.id
    plugin.friendly_name_map[(PREFIX, "Porch")] = dev.id
    return dev


def _fired(plugin, monkeypatch):
    out = []
    real = plugin._fire_event


    def record(event, prefix, name):
        if event == "otaUpdateFailed":
            out.append((event, name))
        return real(event, prefix, name)

    monkeypatch.setattr(plugin, "_fire_event", record)
    return out


RUNNING = {"installed_version": 1, "latest_version": 2, "state": "updating", "progress": 40}
BACK = {"installed_version": 1, "latest_version": 2, "state": "available"}


def test_state_and_reply_fire_one_failure(plugin, make_device, monkeypatch):
    """zigbee2mqtt 2.13.0 publishes the state back to `available`, then an
    error reply with empty data and our transaction."""
    indigo.trigger.reset()
    dev = _ota_light(plugin, make_device, 2150)
    plugin.triggerStartProcessing(FakeTrigger(1, "otaUpdateFailed"))
    fired = _fired(plugin, monkeypatch)
    plugin._process_update_object(dev, RUNNING)
    plugin._process_update_object(dev, BACK)
    plugin._process_ota_response(
        "update", {"status": "error", "data": {}, "transaction": "0xota9",
                   "error": "OTA update of 'Porch' failed (Timeout)"}, PREFIX)
    assert fired == [("otaUpdateFailed", "Porch Light")]
    assert [t.pluginTypeId for t in indigo.trigger.executed] == ["otaUpdateFailed"]


def test_the_reply_alone_names_the_device_from_its_error_text(plugin, make_device,
                                                             monkeypatch):
    """No transaction (an update started from zigbee2mqtt's own frontend):
    the error text still names the device."""
    _ota_light(plugin, make_device, 2151)
    fired = _fired(plugin, monkeypatch)
    plugin._process_ota_response(
        "update", {"status": "error", "data": {},
                   "error": "Update of 'Porch' failed (No image currently available)"},
        PREFIX)
    assert fired == [("otaUpdateFailed", "Porch Light")]


def test_a_later_failure_fires_again(plugin, make_device, monkeypatch):
    dev = _ota_light(plugin, make_device, 2152)
    fired = _fired(plugin, monkeypatch)
    plugin._process_update_object(dev, RUNNING)
    plugin._process_update_object(dev, BACK)
    plugin._ota_failed_at[dev.id] -= 301
    plugin._process_update_object(dev, RUNNING)
    plugin._process_update_object(dev, BACK)
    assert len(fired) == 2


def test_the_update_request_carries_a_transaction(plugin, make_device, monkeypatch):
    dev = _ota_light(plugin, make_device, 2153)
    dev.states["updateState"] = "available"
    plugin.bridge_devices["0xota9"] = {"definition": {"supports_ota": True}}
    out = _published(plugin, monkeypatch)
    plugin._start_firmware_update(dev)
    assert out[0][1] == {"id": "0xota9", "transaction": "0xota9"}


def test_a_check_reply_says_whether_an_update_is_waiting(plugin, make_device, logs):
    _ota_light(plugin, make_device, 2154)
    plugin._process_ota_response(
        "check", {"status": "ok", "data": {"id": "0xota9", "update_available": False}},
        PREFIX)
    assert any("already current" in m for m in logs.event_messages)


# ── 6. a rename cannot undo a capability refresh saved in between ───────────

def test_rename_waits_for_and_keeps_a_capability_refresh(plugin, make_device):
    dev = make_device(2160, "Old", "z2mLight",
                      pluginProps={"friendly_name": "Old", "ieee_address": "0xren",
                                   "mqtt_prefix": PREFIX, "has_color_temp": False})
    plugin.ieee_map["0xren"] = dev.id
    plugin.friendly_name_map[(PREFIX, "Old")] = dev.id
    entry = {"ieee_address": "0xren", "type": "Router", "friendly_name": "New",
             "definition": {"exposes": [{"type": "light", "features": [
                 {"name": "state", "type": "binary", "access": 7},
                 {"name": "brightness", "type": "numeric", "access": 7},
                 {"name": "color_temp", "type": "numeric", "access": 7}]}]}}

    reached, proceed = threading.Event(), threading.Event()
    real_replace = dev.replacePluginPropsOnServer

    def replace(props):
        if threading.current_thread().name == "rename":
            reached.set()
            proceed.wait(2)
        return real_replace(props)

    dev.replacePluginPropsOnServer = replace
    rename = threading.Thread(target=plugin._process_bridge_devices,
                              args=([entry], PREFIX), name="rename")
    rename.start()
    assert reached.wait(2)
    refresh = threading.Thread(target=plugin.refresh_device_capabilities, name="menu")
    refresh.start()
    refresh.join(0.3)
    refresh_finished_inside_the_rename = not refresh.is_alive()
    proceed.set()
    rename.join(2)
    refresh.join(2)
    assert not rename.is_alive() and not refresh.is_alive()
    assert dev.pluginProps["friendly_name"] == "New"
    assert dev.pluginProps["has_color_temp"] is True
    assert not refresh_finished_inside_the_rename, \
        "the refresh must wait for the rename's read-modify-write"


# ── 7. a partial motion report after a restart cannot clear motion ──────────

def _presence(plugin, make_device, dev_id):
    dev = make_device(dev_id, "Lounge Presence", "z2mOccupancySensor",
                      pluginProps={"friendly_name": "Lounge", "ieee_address": f"0xm{dev_id}",
                                   "mqtt_prefix": PREFIX})
    plugin.friendly_name_map[(PREFIX, "Lounge")] = dev.id
    return dev


def test_motion_survives_a_comm_restart(plugin, make_device, monkeypatch):
    _no_state_requests(plugin, monkeypatch)
    dev = _presence(plugin, make_device, 2170)
    plugin._process_occupancy_sensor_state(dev, {"presence": True, "occupancy": False})
    plugin.deviceStopComm(dev)
    plugin.deviceStartComm(dev)
    plugin._process_occupancy_sensor_state(dev, {"occupancy": False})
    assert dev.states["onOffState"] is True
    assert dev.states["motion"] is True


def test_motion_survives_a_plugin_restart(plugin, make_device):
    """A new plugin process has an empty store; the device's own source states
    still say someone is there."""
    dev = _presence(plugin, make_device, 2171)
    dev.states.update({"presence": True, "occupancy": False, "motion": True})
    plugin._motion_states.clear()
    plugin._process_occupancy_sensor_state(dev, {"occupancy": False})
    assert dev.states["onOffState"] is True


def test_a_seeded_false_is_not_taken_as_a_reading(plugin, make_device):
    """occupancy is seeded False on every occupancy sensor, PIR or not.
    Carrying that into the store made the capability self-heal mark a radar
    as having a PIR — live on the first restart of 2.11.0."""
    dev = _presence(plugin, make_device, 2173)
    dev.states.update({"presence": False, "occupancy": False, "motion": False})
    plugin._motion_states.clear()
    plugin._process_occupancy_sensor_state(dev, {"presence": True})
    assert "has_pir" not in dev.pluginProps
    assert plugin._motion_states[dev.id] == {"presence": True}


def test_the_combined_state_never_votes_for_itself(plugin, make_device):
    """`motion` is the answer, not a source: reading it back would hold motion
    on after every real source has cleared."""
    dev = _presence(plugin, make_device, 2172)
    dev.states.update({"presence": False, "occupancy": False, "motion": True})
    plugin._motion_states.clear()
    plugin._process_occupancy_sensor_state(dev, {"occupancy": False})
    assert dev.states["onOffState"] is False


# ── 8. a base topic of several levels routes ────────────────────────────────

def test_a_multi_level_prefix_routes_every_kind_of_message(plugin_mod, monkeypatch):
    p = plugin_mod.Plugin("com.clives.indigoplugin.z2mbridge", "Z2M", "test",
                          {"mqtt_topic_prefix": "house/zigbee2mqtt",
                           "mqtt_garage_topic_prefix": "house/garage"})
    calls = []
    monkeypatch.setattr(p, "_process_bridge_devices",
                        lambda payload, prefix: calls.append(("devices", prefix)))
    monkeypatch.setattr(p, "_process_availability",
                        lambda n, payload, prefix=None: calls.append(("avail", prefix, n)))
    monkeypatch.setattr(p, "_process_device_state",
                        lambda n, payload, prefix=None: calls.append(("state", prefix, n)))
    p._process_message("house/zigbee2mqtt/bridge/devices", [])
    p._process_message("house/zigbee2mqtt/Hall/Lamp", {"state": "ON"})
    p._process_message("house/zigbee2mqtt/Hall/Lamp/availability", {"state": "online"})
    p._process_message("house/garage/Door", {"contact": True})
    p._process_message("house/other/Door", {"contact": True})
    assert calls == [("devices", "house/zigbee2mqtt"),
                     ("state", "house/zigbee2mqtt", "Hall/Lamp"),
                     ("avail", "house/zigbee2mqtt", "Hall/Lamp"),
                     ("state", "house/garage", "Door")]


def test_prefix_validation(plugin):
    def errors(main, garage=""):
        ok, _v, errs = plugin.validatePrefsConfigUi(
            {"mqtt_topic_prefix": main, "mqtt_garage_topic_prefix": garage})
        return dict(errs)

    assert errors("house/zigbee2mqtt", "house/garage") == {}
    assert "mqtt_topic_prefix" in errors("zigbee2mqtt/#")
    assert "mqtt_garage_topic_prefix" in errors("zigbee2mqtt", "z2m/+/x")
    assert "mqtt_topic_prefix" in errors("/zigbee2mqtt")
    assert "mqtt_garage_topic_prefix" in errors("zigbee2mqtt", "zigbee2mqtt/garage")
    assert "mqtt_garage_topic_prefix" in errors("zigbee2mqtt", "zigbee2mqtt")


# ── 9. the first device on an empty network is created ─────────────────────

def test_first_device_after_a_coordinator_only_list_is_created(plugin, monkeypatch):
    created = []
    monkeypatch.setattr(plugin, "_ensure_device_folder", lambda name: 1)
    monkeypatch.setattr(plugin, "_try_create_device",
                        lambda entry, folder, existing: created.append(entry["ieee_address"]))
    coordinator = {"ieee_address": "0x00", "type": "Coordinator"}
    first = {"ieee_address": "0x01", "type": "EndDevice", "friendly_name": "First",
             "definition": {"exposes": []}}
    plugin._process_bridge_devices([coordinator], PREFIX)
    plugin._process_bridge_devices([coordinator, first], PREFIX)
    assert created == ["0x01"]


def test_the_startup_list_is_still_not_auto_created(plugin, monkeypatch):
    created = []
    monkeypatch.setattr(plugin, "_try_create_device",
                        lambda entry, folder, existing: created.append(entry["ieee_address"]))
    plugin._process_bridge_devices([{"ieee_address": "0x05", "type": "EndDevice",
                                     "friendly_name": "Old",
                                     "definition": {"exposes": []}}], PREFIX)
    assert created == []
