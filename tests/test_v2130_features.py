#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2130_features.py
# Description: v2.13.0 — Button Pressed trigger, offline count on the
#              Coordinator, zigbee2mqtt backup, restart / router check /
#              set-up-again, Stop Blind and Fade Light.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""Reply shapes are the ones both live bridges sent on 02-10-2026:
backup -> {"data": {"zip": <base64>}, "status": "ok", "transaction": ...}
(the house bridge took 21 s), coordinator_check -> {"data":
{"missing_routers": []}, "status": "ok", ...}."""

import base64
import io
import os
import stat
import zipfile

import indigo  # stub
from indigo_stub import FakeTrigger

PREFIX = "zigbee2mqtt"
GARAGE = "zigbee2mqtt_garage"


def _published(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    return out


def _coordinator(plugin, make_device, prefix=PREFIX, dev_id=2300):
    states = {k: "" for k in ("offlineDevices", "offlineDeviceNames", "missingRouters",
                              "missingRouterNames", "lastBackup", "lastEvent",
                              "lastEventDevice", "lastEventTime", "lastUpdate")}
    dev = make_device(dev_id, f"Z2M Bridge ({prefix})", "z2mCoordinator",
                      pluginProps={"mqtt_prefix": prefix}, states=states)
    plugin.coordinator_map[prefix] = dev.id
    return dev


# ── 1. Button Pressed ────────────────────────────────────────────────────────

REMOTE_EXPOSES = [{"type": "enum", "name": "action", "property": "action", "access": 1,
                   "values": ["single", "double", "hold"]}]


def _remote(plugin, make_device, dev_id=2310, type_id="z2mButton"):
    dev = make_device(dev_id, "Hall Remote", type_id,
                      pluginProps={"friendly_name": "Hall Remote", "ieee_address": "0xrem",
                                   "mqtt_prefix": PREFIX},
                      states={"pressCount": 0})
    plugin.friendly_name_map[(PREFIX, "Hall Remote")] = dev.id
    plugin.bridge_devices["0xrem"] = {"ieee_address": "0xrem", "_mqtt_prefix": PREFIX,
                                      "definition": {"exposes": REMOTE_EXPOSES}}
    return dev


def _watch(plugin, trigger_id, dev_id, action="any"):
    trigger = FakeTrigger(trigger_id, "buttonPressed")
    trigger.pluginProps = {"deviceId": str(dev_id), "action": action}
    plugin.triggerStartProcessing(trigger)
    return trigger


def _press(plugin, action, retained=False):
    plugin.msg_queue.put((f"{PREFIX}/Hall Remote", {"action": action}, retained))
    plugin._drain_queue()


def test_every_press_fires_even_the_same_one_twice(plugin, make_device):
    indigo.trigger.reset()
    dev = _remote(plugin, make_device)
    _watch(plugin, 1, dev.id)
    _press(plugin, "single")
    _press(plugin, "single")
    assert len(indigo.trigger.executed) == 2


def test_a_trigger_for_one_press_ignores_the_others(plugin, make_device):
    indigo.trigger.reset()
    dev = _remote(plugin, make_device)
    double = _watch(plugin, 1, dev.id, "double")
    _watch(plugin, 2, 99999, "any")              # another device's trigger
    _press(plugin, "single")
    _press(plugin, "double")
    assert indigo.trigger.executed == [double]


def test_a_retained_replay_is_not_a_press(plugin, make_device):
    indigo.trigger.reset()
    dev = _remote(plugin, make_device)
    _watch(plugin, 1, dev.id)
    _press(plugin, "single", retained=True)
    assert indigo.trigger.executed == []
    assert plugin._current_retained is False, "the flag must not outlive its message"


def test_a_relay_that_sends_presses_fires_too(plugin, make_device):
    """A scene-capable wall switch: it switches a load AND sends presses."""
    indigo.trigger.reset()
    dev = _remote(plugin, make_device, dev_id=2311, type_id="z2mRelay")
    plugin.bridge_devices["0xrem"]["definition"]["exposes"] = REMOTE_EXPOSES + [
        {"type": "switch", "features": [{"type": "binary", "name": "state",
                                         "property": "state", "access": 7}]}]
    _watch(plugin, 1, dev.id, "hold")
    _press(plugin, "hold")
    assert len(indigo.trigger.executed) == 1


def test_the_dialog_lists_the_devices_and_their_presses(plugin, make_device):
    dev = _remote(plugin, make_device)
    make_device(2312, "Plain Plug", "z2mRelay",
                pluginProps={"friendly_name": "Plain Plug", "ieee_address": "0xpp"})
    assert plugin.list_action_devices() == [(str(dev.id), "Hall Remote")]
    assert plugin.list_device_actions(valuesDict={"deviceId": str(dev.id)}) == [
        ("any", "Any press"), ("single", "single"), ("double", "double"), ("hold", "hold")]


def test_the_trigger_needs_a_device(plugin):
    ok, _v, errors = plugin.validateEventConfigUi({"deviceId": "none"}, "buttonPressed", 1)
    assert not ok and "deviceId" in errors


# ── 2. offline devices on the Coordinator ────────────────────────────────────

def _sensor(plugin, make_device, name, dev_id):
    dev = make_device(dev_id, name, "z2mContactSensor",
                      pluginProps={"friendly_name": name, "ieee_address": f"0x{dev_id}",
                                   "mqtt_prefix": PREFIX})
    plugin.friendly_name_map[(PREFIX, name)] = dev.id
    return dev


def _availability(plugin, name, state, retained=False):
    plugin.msg_queue.put((f"{PREFIX}/{name}/availability", {"state": state}, retained))
    plugin._drain_queue()


def test_the_coordinator_counts_and_names_offline_devices(plugin, make_device):
    indigo.trigger.reset()
    coord = _coordinator(plugin, make_device)
    _sensor(plugin, make_device, "Back Door", 2320)
    _sensor(plugin, make_device, "Attic Hatch", 2321)
    plugin.triggerStartProcessing(FakeTrigger(1, "offlineCountChanged"))
    _availability(plugin, "Back Door", "offline")
    _availability(plugin, "Attic Hatch", "offline")
    assert coord.states["offlineDevices"] == 2
    assert coord.states["offlineDeviceNames"] == "Attic Hatch, Back Door"
    _availability(plugin, "Back Door", "online")
    assert coord.states["offlineDevices"] == 1
    assert len(indigo.trigger.executed) == 3


def test_an_unchanged_count_fires_nothing(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    _sensor(plugin, make_device, "Back Door", 2322)
    plugin.triggerStartProcessing(FakeTrigger(1, "offlineCountChanged"))
    _availability(plugin, "Back Door", "offline")
    _availability(plugin, "Back Door", "offline")
    assert len(indigo.trigger.executed) == 1


def test_the_startup_replay_counts_but_fires_nothing(plugin, make_device):
    indigo.trigger.reset()
    coord = _coordinator(plugin, make_device)
    _sensor(plugin, make_device, "Back Door", 2323)
    plugin.triggerStartProcessing(FakeTrigger(1, "offlineCountChanged"))
    _availability(plugin, "Back Door", "offline", retained=True)
    assert coord.states["offlineDevices"] == 1
    assert indigo.trigger.executed == []


def test_a_stopped_device_stops_counting(plugin, make_device, monkeypatch):
    coord = _coordinator(plugin, make_device)
    dev = _sensor(plugin, make_device, "Back Door", 2324)
    _availability(plugin, "Back Door", "offline")
    plugin.deviceStopComm(dev)
    assert coord.states["offlineDevices"] == 0


# ── 3. backup ────────────────────────────────────────────────────────────────

def _zip_b64(files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in (files or {"configuration.yaml": "a: 1\n",
                                     "database.db": "{}\n"}).items():
            zf.writestr(name, body)
    return base64.b64encode(buf.getvalue()).decode()


def _backup_prefs(plugin, folder, keep="10"):
    plugin.pluginPrefs["backupFolder"] = str(folder)
    plugin.pluginPrefs["backupKeep"] = keep


def _reply(plugin, prefix, kind, transaction, data, status="ok", error=None):
    payload = {"status": status, "data": data, "transaction": transaction}
    if error:
        payload["error"] = error
    plugin._process_message(f"{prefix}/bridge/response/{kind}", payload)


def test_a_backup_is_asked_for_and_saved_private(plugin, make_device, monkeypatch,
                                                 tmp_path, logs):
    coord = _coordinator(plugin, make_device)
    _backup_prefs(plugin, tmp_path / "z2m")
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    topic, body = out[0]
    assert topic == f"{PREFIX}/bridge/request/backup"
    _reply(plugin, PREFIX, "backup", body["transaction"], {"zip": _zip_b64()})
    saved = list((tmp_path / "z2m").iterdir())
    assert len(saved) == 1 and saved[0].name.startswith("zigbee2mqtt-backup-zigbee2mqtt-")
    assert stat.S_IMODE(os.stat(saved[0]).st_mode) == 0o600
    with zipfile.ZipFile(saved[0]) as zf:
        assert "configuration.yaml" in zf.namelist()
    assert coord.states["lastBackup"]
    assert any("Saved a backup" in m for m in logs.event_messages)
    assert not any("a: 1" in m for m in logs.event_messages), "contents are never logged"


def test_a_backup_nobody_here_asked_for_is_ignored(plugin, tmp_path):
    """zigbee2mqtt's own web page publishes its backups on the same topic."""
    _backup_prefs(plugin, tmp_path / "z2m")
    _reply(plugin, PREFIX, "backup", "frontend-123", {"zip": _zip_b64()})
    _reply(plugin, PREFIX, "backup", None, {"zip": _zip_b64()})
    assert not (tmp_path / "z2m").exists()


def test_a_damaged_backup_is_not_saved(plugin, monkeypatch, tmp_path, logs):
    _backup_prefs(plugin, tmp_path / "z2m")
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    _reply(plugin, PREFIX, "backup", out[0][1]["transaction"],
           {"zip": base64.b64encode(b"not a zip").decode()})
    assert not (tmp_path / "z2m").exists() or not list((tmp_path / "z2m").iterdir())
    assert any("not a usable zip" in m for m in logs.at("ERROR"))


def test_old_backups_are_pruned_and_nothing_else_touched(plugin, monkeypatch, tmp_path):
    folder = tmp_path / "z2m"
    folder.mkdir()
    for day in range(1, 5):
        (folder / f"zigbee2mqtt-backup-zigbee2mqtt-2026-09-0{day}-120000.zip").write_bytes(b"x")
    (folder / f"zigbee2mqtt-backup-{GARAGE}-2026-09-01-120000.zip").write_bytes(b"x")
    (folder / "my-notes.txt").write_text("keep me")
    _backup_prefs(plugin, folder, keep="2")
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    _reply(plugin, PREFIX, "backup", out[0][1]["transaction"], {"zip": _zip_b64()})
    names = sorted(p.name for p in folder.iterdir())
    mine = [n for n in names if n.startswith("zigbee2mqtt-backup-zigbee2mqtt-")]
    assert len(mine) == 2 and "zigbee2mqtt-backup-zigbee2mqtt-2026-09-04-120000.zip" in mine
    assert f"zigbee2mqtt-backup-{GARAGE}-2026-09-01-120000.zip" in names
    assert "my-notes.txt" in names


def test_a_refused_backup_says_why(plugin, monkeypatch, tmp_path, logs):
    _backup_prefs(plugin, tmp_path / "z2m")
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    _reply(plugin, PREFIX, "backup", out[0][1]["transaction"], {}, status="error",
           error="disk full")
    assert any("could not make a backup: disk full" in m for m in logs.at("WARNING"))


def test_all_bridges_are_backed_up_when_asked(plugin, monkeypatch):
    plugin.pluginPrefs["mqtt_garage_topic_prefix"] = GARAGE
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": "all"})
    assert [t for t, _ in out] == [f"{PREFIX}/bridge/request/backup",
                                   f"{GARAGE}/bridge/request/backup"]
    assert len({b["transaction"] for _, b in out}) == 2


def test_no_reply_is_reported_once(plugin, monkeypatch, logs):
    _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    for request in plugin._bridge_requests.values():
        request["sent"] -= 181
    plugin._check_bridge_requests()
    plugin._check_bridge_requests()
    assert len([m for m in logs.at("WARNING") if "did not answer the backup" in m]) == 1


def test_the_default_folder_is_beside_the_indigo_folder(plugin):
    plugin.pluginPrefs["backupFolder"] = ""
    expected = os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                            "Zigbee2MQTT Backups")
    assert plugin._backup_folder() == expected


def test_backup_settings_are_checked(plugin):
    def errors(**kv):
        values = {"mqtt_topic_prefix": PREFIX}
        values.update(kv)
        return dict(plugin.validatePrefsConfigUi(values)[2])
    assert errors(backupFolder="/Users/indigo/Backups", backupKeep="5") == {}
    assert "backupFolder" in errors(backupFolder="Backups")
    assert "backupFolder" in errors(backupFolder="/Library/x/Web Assets/public/b")
    assert "backupKeep" in errors(backupKeep="0")
    assert "backupKeep" in errors(backupKeep="lots")


# ── 4. restart, missing routers, set up again ────────────────────────────────

def test_restart_needs_one_bridge(plugin, monkeypatch, logs):
    out = _published(plugin, monkeypatch)
    plugin.menu_restart_bridge({"bridge": "all"})
    assert out == []
    plugin.menu_restart_bridge({"bridge": PREFIX})
    assert out[0][0] == f"{PREFIX}/bridge/request/restart"
    _reply(plugin, PREFIX, "restart", out[0][1]["transaction"], {})
    assert any("is restarting" in m for m in logs.event_messages)


def test_missing_routers_are_named_and_counted(plugin, make_device, monkeypatch, logs):
    coord = _coordinator(plugin, make_device)
    out = _published(plugin, monkeypatch)
    plugin.menu_check_routers({"bridge": PREFIX})
    _reply(plugin, PREFIX, "coordinator_check", out[0][1]["transaction"],
           {"missing_routers": [{"friendly_name": "Hall Repeater", "ieee_address": "0x1"},
                                {"friendly_name": "Landing Lamp", "ieee_address": "0x2"}]})
    assert coord.states["missingRouters"] == 2
    assert coord.states["missingRouterNames"] == "Hall Repeater, Landing Lamp"
    warned = logs.at("WARNING")
    assert any("2 routers are missing — Hall Repeater and Landing Lamp" in m for m in warned)


def test_no_missing_routers_is_good_news(plugin, make_device, monkeypatch, logs):
    coord = _coordinator(plugin, make_device)
    out = _published(plugin, monkeypatch)
    plugin.menu_check_routers({"bridge": PREFIX})
    _reply(plugin, PREFIX, "coordinator_check", out[0][1]["transaction"],
           {"missing_routers": []})
    assert coord.states["missingRouters"] == 0
    assert logs.at("WARNING") == []


def test_a_device_is_set_up_again(plugin, make_device, make_action, monkeypatch, logs):
    dev = _sensor(plugin, make_device, "Back Door", 2340)
    out = _published(plugin, monkeypatch)
    plugin.action_reconfigure_device(make_action(), dev)
    topic, body = out[0]
    assert topic == f"{PREFIX}/bridge/request/device/configure"
    assert body["id"] == "0x2340"
    _reply(plugin, PREFIX, "device/configure", body["transaction"], {"id": "0x2340"},
           status="error", error="Failed to configure (timeout)")
    assert any("Back Door: zigbee2mqtt could not set it up again" in m
               for m in logs.at("WARNING"))


def test_a_coordinator_or_split_out_device_is_not_set_up_again(plugin, make_device,
                                                               monkeypatch):
    coord = _coordinator(plugin, make_device)
    child = make_device(2341, "Back Door [Temperature]", "z2mTemperatureSecondary",
                        pluginProps={"ieee_address": "0xabc"})
    out = _published(plugin, monkeypatch)
    plugin._reconfigure_device(coord)
    plugin._reconfigure_device(child)
    assert out == []


# ── 5. Stop Blind and Fade Light ─────────────────────────────────────────────

def test_stop_blind(plugin, make_device, make_action, monkeypatch):
    dev = make_device(2350, "Study Blind", "z2mCover",
                      pluginProps={"friendly_name": "Study Blind"})
    out = _published(plugin, monkeypatch)
    plugin.action_stop_cover(make_action(), dev)
    assert out == [(f"{PREFIX}/Study Blind/set", {"state": "STOP"})]


def test_fade_up_and_fade_off(plugin, make_device, make_action, monkeypatch):
    dev = make_device(2351, "Hall Lamp", "z2mLight", pluginProps={"friendly_name": "Hall Lamp"})
    out = _published(plugin, monkeypatch)
    plugin.action_fade_light(make_action(props={"brightness": "50", "seconds": "10"}), dev)
    plugin.action_fade_light(make_action(props={"brightness": "0", "seconds": "2.5"}), dev)
    assert out == [(f"{PREFIX}/Hall Lamp/set", {"state": "ON", "brightness": 127,
                                                 "transition": 10}),
                   (f"{PREFIX}/Hall Lamp/set", {"state": "OFF", "transition": 2.5})]


def test_a_bad_fade_sends_nothing_and_the_dialog_says_so(plugin, make_device, make_action,
                                                         monkeypatch, logs):
    dev = make_device(2352, "Hall Lamp", "z2mLight", pluginProps={"friendly_name": "Hall Lamp"})
    out = _published(plugin, monkeypatch)
    plugin.action_fade_light(make_action(props={"brightness": "150", "seconds": "5"}), dev)
    assert out == []
    ok, _v, errors = plugin.validateActionConfigUi({"brightness": "x", "seconds": "5"},
                                                   "fadeLight", dev.id)
    assert not ok and "brightness" in errors
    ok, _v, _e = plugin.validateActionConfigUi({"brightness": "40", "seconds": "5"},
                                               "fadeLight", dev.id)
    assert ok


def test_a_bridge_action_must_name_a_bridge(plugin):
    ok, _v, errors = plugin.validateActionConfigUi({"bridge": "all"}, "restartBridge", 0)
    assert not ok and "bridge" in errors
    ok, _v, _e = plugin.validateActionConfigUi({"bridge": "all"}, "backupBridge", 0)
    assert ok


def test_an_empty_backup_is_not_saved(plugin, monkeypatch, tmp_path, logs):
    """A valid zip with nothing in it is no backup."""
    _backup_prefs(plugin, tmp_path / "z2m")
    out = _published(plugin, monkeypatch)
    plugin.menu_backup({"bridge": PREFIX})
    empty = io.BytesIO()
    zipfile.ZipFile(empty, "w").close()
    _reply(plugin, PREFIX, "backup", out[0][1]["transaction"],
           {"zip": base64.b64encode(empty.getvalue()).decode()})
    assert not (tmp_path / "z2m").exists() or not list((tmp_path / "z2m").iterdir())
    assert any("not a usable zip" in m for m in logs.at("ERROR"))


def test_the_broker_retain_flag_reaches_the_queue(plugin):
    import queue

    class Msg:
        topic = f"{PREFIX}/Hall Remote"
        payload = b'{"action": "single"}'
        retain = True

    plugin.msg_queue = queue.Queue()
    plugin._on_mqtt_message(None, None, Msg())
    assert plugin.msg_queue.get_nowait()[2] is True
