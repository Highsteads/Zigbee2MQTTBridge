#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v240_ota.py
# Description: Firmware update reporting and explicit, user-driven updates.
#
#              The refusals matter most here. An over-the-air update runs for
#              minutes over a battery radio link and a failed one can leave a
#              device unusable, so nothing may start one except a person asking
#              for it — and only when an update is genuinely waiting.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import indigo  # stub
from indigo_stub import FakeTrigger

# Real shape, captured from a live Aqara sensor.
UPDATE_IDLE = {"installed_version": 16682, "latest_version": 16682,
               "state": "idle"}
UPDATE_AVAILABLE = {"installed_version": 16600, "latest_version": 16682,
                    "state": "available"}
UPDATE_RUNNING = {"installed_version": 16600, "latest_version": 16682,
                  "state": "updating", "progress": 42.5}


def _dev(plugin, make_device, dev_id=900, ota=True, states=None):
    d = make_device(dev_id, "Front Door Light", "z2mLight",
                    pluginProps={"friendly_name": "Front Door Light",
                                 "ieee_address": "0xota1",
                                 "mqtt_prefix": "zigbee2mqtt"},
                    states=states or {})
    plugin.bridge_devices["0xota1"] = {
        "ieee_address": "0xota1", "friendly_name": "Front Door Light",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"supports_ota": ota, "exposes": []},
    }
    plugin.ieee_map["0xota1"] = d.id
    return d


def _sent(monkeypatch, plugin):
    out = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda topic, payload: out.append((topic, payload)) or True)
    return out


# ── reading the update object ─────────────────────────────────────────────────

def test_idle_update_populates_states(plugin, make_device):
    dev = _dev(plugin, make_device)
    plugin._process_update_object(dev, UPDATE_IDLE)
    assert dev.states["updateState"] == "idle"
    assert dev.states["updateAvailable"] is False
    assert dev.states["updateInstalledVersion"] == "16682"


def test_available_update_sets_the_flag(plugin, make_device):
    dev = _dev(plugin, make_device)
    plugin._process_update_object(dev, UPDATE_AVAILABLE)
    assert dev.states["updateState"] == "available"
    assert dev.states["updateAvailable"] is True


def test_progress_is_recorded_while_updating(plugin, make_device):
    dev = _dev(plugin, make_device)
    plugin._process_update_object(dev, UPDATE_RUNNING)
    assert dev.states["updateProgress"] == 42.5


def test_the_event_fires_on_the_rising_edge_only(plugin, make_device):
    """This object rides along with ordinary state payloads, so a device with a
    pending update republishes 'available' every few minutes. Firing each time
    would turn one pending update into a trigger storm."""
    indigo.trigger.reset()
    dev = _dev(plugin, make_device)
    plugin.coordinator_map["zigbee2mqtt"] = 999999   # no coordinator device
    plugin.triggerStartProcessing(FakeTrigger(1, "otaUpdateAvailable"))
    for _ in range(4):
        plugin._process_update_object(dev, UPDATE_AVAILABLE)
    assert [t.pluginTypeId for t in indigo.trigger.executed] == ["otaUpdateAvailable"]


def test_no_event_while_idle(plugin, make_device):
    indigo.trigger.reset()
    dev = _dev(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "otaUpdateAvailable"))
    plugin._process_update_object(dev, UPDATE_IDLE)
    assert indigo.trigger.executed == []


def test_a_malformed_update_object_is_ignored(plugin, make_device):
    dev = _dev(plugin, make_device)
    plugin._process_update_object(dev, "not a dict")
    plugin._process_update_object(dev, {})
    assert "updateState" not in dev.states


# ── starting an update ────────────────────────────────────────────────────────

def test_update_is_refused_when_none_is_available(plugin, make_device,
                                                  make_action, monkeypatch):
    dev = _dev(plugin, make_device, states={"updateState": "idle"})
    sent = _sent(monkeypatch, plugin)
    plugin.action_update_firmware(make_action(), dev)
    assert sent == []


def test_update_is_refused_when_state_is_unknown(plugin, make_device,
                                                 make_action, monkeypatch):
    """Never fire an update at a device we have not checked."""
    dev = _dev(plugin, make_device)
    sent = _sent(monkeypatch, plugin)
    plugin.action_update_firmware(make_action(), dev)
    assert sent == []


def test_update_is_refused_when_the_device_cannot_take_one(plugin, make_device,
                                                           make_action, monkeypatch):
    dev = _dev(plugin, make_device, ota=False, states={"updateState": "available"})
    sent = _sent(monkeypatch, plugin)
    plugin.action_update_firmware(make_action(), dev)
    assert sent == []


def test_update_is_refused_while_one_is_already_running(plugin, make_device,
                                                        make_action, monkeypatch):
    dev = _dev(plugin, make_device, states={"updateState": "updating"})
    sent = _sent(monkeypatch, plugin)
    plugin.action_update_firmware(make_action(), dev)
    assert sent == [], "interrupting a running update can brick the device"


def test_update_starts_when_one_is_genuinely_waiting(plugin, make_device,
                                                     make_action, monkeypatch):
    dev = _dev(plugin, make_device, states={"updateState": "available"})
    sent = _sent(monkeypatch, plugin)
    plugin.action_update_firmware(make_action(), dev)
    assert sent == [("zigbee2mqtt/bridge/request/device/ota_update/update",
                     {"id": "0xota1"})]


def test_update_with_no_device_does_not_crash(plugin, make_action):
    plugin.action_update_firmware(make_action(), None)


# ── checking ──────────────────────────────────────────────────────────────────

def test_check_only_asks_about_capable_devices(plugin, make_device, monkeypatch):
    _dev(plugin, make_device, dev_id=901, ota=True)
    incapable = make_device(902, "Old Sensor", "z2mSensor",
                            pluginProps={"friendly_name": "Old Sensor",
                                         "ieee_address": "0xnoota"})
    plugin.bridge_devices["0xnoota"] = {
        "ieee_address": "0xnoota", "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"supports_ota": False, "exposes": []},
    }
    sent = _sent(monkeypatch, plugin)
    plugin.check_firmware_updates()
    ids = [p["id"] for _, p in sent]
    assert ids == ["0xota1"]
    assert "0xnoota" not in ids
    assert incapable.id


def test_check_never_starts_an_update(plugin, make_device, monkeypatch):
    """Checking is read-only. Nothing here may install anything."""
    _dev(plugin, make_device)
    sent = _sent(monkeypatch, plugin)
    plugin.check_firmware_updates()
    assert all(t.endswith("/ota_update/check") for t, _ in sent)


# ── replies ───────────────────────────────────────────────────────────────────

def test_a_sleeping_device_is_not_reported_as_an_error(plugin, make_device,
                                                       monkeypatch, helpers_mod):
    """A battery sensor spends nearly all its life asleep and simply will not
    answer. Eight red lines from one routine check across 19 devices is how a
    log stops being worth reading."""
    _dev(plugin, make_device)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    for reason in ("Failed to check if OTA update available for 'X' "
                   "(Device didn't respond to OTA request)",
                   "Failed to check ... (No endpoint found with OTA cluster support)",
                   "OTA update or check for update already in progress for 'X'"):
        plugin._process_ota_response("check", {"status": "error", "error": reason,
                                               "data": {}}, "zigbee2mqtt")
    assert logged, "it still says something"
    assert not any(lv == "ERROR" for lv, _ in logged), \
        "but none of these are faults"


def test_an_unidentifiable_reply_does_not_invent_a_device_name(plugin,
                                                               monkeypatch,
                                                               helpers_mod):
    """zigbee2mqtt sends `data: {}` on an error, so there is no id to look up.
    The error text names the device itself."""
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    plugin._process_ota_response(
        "check", {"status": "error", "data": {},
                  "error": "Failed for 'Bathroom Basin Presence Sensor'"},
        "zigbee2mqtt")
    assert not any(m.startswith("?") for _, m in logged)
    assert any("Bathroom Basin Presence Sensor" in m for _, m in logged)


def test_an_unexpected_failure_is_still_an_error(plugin, make_device,
                                                 monkeypatch, helpers_mod):
    """Demoting the routine ones must not silence a real fault."""
    _dev(plugin, make_device)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    plugin._process_ota_response(
        "check", {"status": "error", "error": "image signature invalid",
                  "data": {"id": "0xota1"}}, "zigbee2mqtt")
    assert any(lv == "ERROR" for lv, _ in logged)


def test_an_error_reply_is_reported(plugin, make_device, monkeypatch, helpers_mod):
    _dev(plugin, make_device)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    plugin._process_ota_response(
        "check", {"status": "error", "error": "coordinator refused the request",
                  "data": {"id": "0xota1"}}, "zigbee2mqtt")
    assert any(lv == "ERROR" and "refused" in m for lv, m in logged)


def test_a_successful_check_reply_is_reported(plugin, make_device, monkeypatch,
                                              helpers_mod):
    _dev(plugin, make_device)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    plugin._process_ota_response(
        "check", {"status": "ok", "data": {"id": "0xota1", "updateAvailable": True}},
        "zigbee2mqtt")
    assert any("update is available" in m for _, m in logged)


def test_a_malformed_reply_is_survivable(plugin):
    plugin._process_ota_response("check", "not a dict", "zigbee2mqtt")
    plugin._process_ota_response("update", None, "zigbee2mqtt")


def test_ota_responses_are_routed(plugin, monkeypatch):
    seen = []
    monkeypatch.setattr(plugin, "_process_ota_response",
                        lambda action, payload, prefix: seen.append(action))
    plugin._process_message(
        "zigbee2mqtt/bridge/response/device/ota_update/check", {"status": "ok"})
    plugin._process_message(
        "zigbee2mqtt/bridge/response/device/ota_update/update", {"status": "ok"})
    assert seen == ["check", "update"]


# ── the menu picker (v2.6.0) ──────────────────────────────────────────────────

def test_the_picker_lists_only_devices_with_an_update(plugin, make_device):
    """Offering the whole estate and refusing most of it afterwards would be a
    worse dialog than one showing only what can actually be done."""
    _dev(plugin, make_device, dev_id=910, states={
        "updateState": "available", "updateInstalledVersion": "100",
        "updateLatestVersion": "101"})
    make_device(911, "Up To Date Lamp", "z2mLight",
                pluginProps={"ieee_address": "0xb"},
                states={"updateState": "idle"})
    make_device(912, "Never Checked", "z2mLight", pluginProps={"ieee_address": "0xc"})
    rows = plugin.list_devices_with_updates()
    assert len(rows) == 1
    value, label = rows[0]
    assert value == "910"
    assert "100 -> 101" in label


def test_an_empty_picker_says_why(plugin, make_device):
    """A menu with no options looks broken."""
    make_device(913, "Up To Date Lamp", "z2mLight", states={"updateState": "idle"})
    rows = plugin.list_devices_with_updates()
    assert rows == [("", "-- no updates waiting --")]


def test_the_menu_starts_the_update_for_the_chosen_device(plugin, make_device,
                                                          monkeypatch):
    dev = _dev(plugin, make_device, dev_id=914, states={"updateState": "available"})
    sent = _sent(monkeypatch, plugin)
    plugin.menu_update_firmware({"targetDevice": str(dev.id)}, None)
    assert sent == [("zigbee2mqtt/bridge/request/device/ota_update/update",
                     {"id": "0xota1"})]


def test_the_menu_refuses_the_empty_placeholder(plugin, monkeypatch):
    """Menu ConfigUIs are never validated by Indigo, so the callback must check
    rather than assume the dialog did."""
    sent = _sent(monkeypatch, plugin)
    plugin.menu_update_firmware({"targetDevice": ""}, None)
    assert sent == []


def test_the_menu_survives_a_device_deleted_mid_dialog(plugin, monkeypatch):
    sent = _sent(monkeypatch, plugin)
    plugin.menu_update_firmware({"targetDevice": "99999999"}, None)
    assert sent == []


def test_the_menu_obeys_the_same_guards_as_the_action(plugin, make_device,
                                                      monkeypatch):
    """Both routes go through one guarded path — the menu must not be a way
    round the checks."""
    dev = _dev(plugin, make_device, dev_id=915, states={"updateState": "idle"})
    sent = _sent(monkeypatch, plugin)
    plugin.menu_update_firmware({"targetDevice": str(dev.id)}, None)
    assert sent == [], "no update waiting, so nothing sent"
