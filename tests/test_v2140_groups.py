#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2140_groups.py
# Description: v2.14.0 — zigbee2mqtt groups as Indigo devices.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""Shapes from zigbee2mqtt 2.14.2's source: bridge.ts publishGroups sends a
retained list of {id, friendly_name, description, scenes, members:
[{ieee_address, endpoint}]}; a group is driven on <prefix>/<group>/set and
reports on <prefix>/<group> like a device. Neither bridge here had a group on
02-10-2026, so these are the only contract until one is made."""

import indigo  # stub

PREFIX = "zigbee2mqtt"

CT_BULB = [{"type": "light", "features": [
    {"name": "state", "property": "state", "type": "binary", "access": 7},
    {"name": "brightness", "property": "brightness", "type": "numeric", "access": 7},
    {"name": "color_temp", "property": "color_temp", "type": "numeric", "access": 7}]}]
COLOUR_BULB = [{"type": "light", "features": [
    {"name": "state", "property": "state", "type": "binary", "access": 7},
    {"name": "brightness", "property": "brightness", "type": "numeric", "access": 7},
    {"type": "composite", "name": "color_xy", "property": "color", "access": 7,
     "features": [{"name": "x", "property": "x", "type": "numeric", "access": 7}]}]}]
PLUG = [{"type": "switch", "features": [
    {"name": "state", "property": "state", "type": "binary", "access": 7}]}]
SENSOR = [{"name": "contact", "property": "contact", "type": "binary", "access": 1}]


def _member(plugin, make_device, ieee, name, exposes, dev_id, on=False, type_id="z2mLight"):
    plugin.bridge_devices[ieee] = {"ieee_address": ieee, "friendly_name": name,
                                   "_mqtt_prefix": PREFIX,
                                   "definition": {"exposes": exposes, "model": "X"}}
    if make_device is None:
        return None
    dev = make_device(dev_id, f"{name} (Indigo)", type_id,
                      pluginProps={"friendly_name": name, "ieee_address": ieee,
                                   "mqtt_prefix": PREFIX},
                      states={"onOffState": on}, onState=on)
    plugin.ieee_map[ieee] = dev.id
    return dev


def _group(gid, name, *ieees):
    return {"id": gid, "friendly_name": name, "description": None, "scenes": [],
            "members": [{"ieee_address": i, "endpoint": 11} for i in ieees]}


def _no_folders(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_ensure_device_folder", lambda name: 1)


def _created(prefix_types=("z2mGroupLight", "z2mGroupRelay")):
    return [d for d in indigo.devices if d.deviceTypeId in prefix_types]


# ── creating ─────────────────────────────────────────────────────────────────

def test_the_first_list_is_a_baseline_and_a_new_group_is_created(plugin, make_device,
                                                                  monkeypatch):
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2401)
    _member(plugin, make_device, "0xb", "Lamp B", CT_BULB, 2402)
    plugin._process_message(f"{PREFIX}/bridge/groups", [_group(1, "Old Group", "0xa")])
    assert _created() == [], "the startup list creates nothing"
    plugin._process_message(f"{PREFIX}/bridge/groups",
                            [_group(1, "Old Group", "0xa"),
                             _group(2, "Lounge Lamps", "0xa", "0xb")])
    made = _created()
    assert [d.name for d in made] == ["Lounge Lamps"]
    props = made[0].pluginProps
    assert made[0].deviceTypeId == "z2mGroupLight"
    assert props["group_id"] == "2" and props["friendly_name"] == "Lounge Lamps"
    assert props["has_color_temp"] is True and props["has_color"] is False


def test_a_group_made_empty_then_filled_is_created_when_filled(plugin, make_device,
                                                               monkeypatch):
    """zigbee2mqtt's web page makes the group first and adds members after."""
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2403)
    plugin._process_bridge_groups([], PREFIX)
    plugin._process_bridge_groups([_group(3, "Hall", )], PREFIX)
    assert _created() == []
    plugin._process_bridge_groups([_group(3, "Hall", "0xa")], PREFIX)
    assert [d.name for d in _created()] == ["Hall"]


def test_a_group_of_plugs_is_a_switch_and_sensors_or_bind_group_are_nothing(
        plugin, make_device, monkeypatch):
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xp", "Plug", PLUG, 2404, type_id="z2mRelay")
    _member(plugin, make_device, "0xs", "Door", SENSOR, 2405, type_id="z2mContactSensor")
    plugin._process_bridge_groups([], PREFIX)
    plugin._process_bridge_groups([_group(4, "Plugs", "0xp"),
                                   _group(5, "Doors", "0xs"),
                                   _group(901, "default_bind_group", "0xp")], PREFIX)
    made = _created()
    assert [(d.name, d.deviceTypeId) for d in made] == [("Plugs", "z2mGroupRelay")]


def test_discover_and_create_makes_groups_once(plugin, make_device, monkeypatch, logs):
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xa", "Lamp A", COLOUR_BULB, 2406)
    plugin._process_bridge_groups([_group(6, "Kitchen", "0xa")], PREFIX)
    plugin.discover_create_devices()
    plugin.discover_create_devices()
    made = _created()
    assert len(made) == 1 and made[0].pluginProps["has_color"] is True
    assert any("1 group(s) created" in m for m in logs.event_messages)
    assert any("0 group(s) created, 1 already existed" in m for m in logs.event_messages)


def test_a_name_already_used_in_indigo_gets_group_added(plugin, make_device, monkeypatch):
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2407)
    make_device(2408, "Landing", "z2mLight", pluginProps={"friendly_name": "x"})
    plugin._process_bridge_groups([_group(7, "Landing", "0xa")], PREFIX)
    plugin.discover_create_devices()
    assert [d.name for d in _created()] == ["Landing (group)"]


# ── running ──────────────────────────────────────────────────────────────────

def _group_dev(plugin, make_device, type_id="z2mGroupLight", dev_id=2420, gid=10,
               name="Lounge Lamps", props=None):
    base = {"friendly_name": name, "mqtt_prefix": PREFIX, "group_id": str(gid),
            "has_brightness": True, "has_color_temp": True, "has_color": False}
    base.update(props or {})
    return make_device(dev_id, name, type_id, pluginProps=base,
                       states={"onOffState": False, "brightnessLevel": 0})


def test_starting_a_group_routes_it_and_never_asks_for_state(plugin, make_device,
                                                            monkeypatch):
    asked = []
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: asked.append(a))
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2421, on=False)
    _member(plugin, make_device, "0xb", "Lamp B", CT_BULB, 2422, on=True)
    plugin.bridge_groups[PREFIX] = {10: _group(10, "Lounge Lamps", "0xa", "0xb")}
    dev = _group_dev(plugin, make_device)
    plugin.deviceStartComm(dev)
    assert plugin.friendly_name_map[(PREFIX, "Lounge Lamps")] == dev.id
    assert asked == []
    assert dev.states["onOffState"] is True, "on when any member is on"


def test_group_state_arrives_like_a_light(plugin, make_device):
    dev = _group_dev(plugin, make_device, dev_id=2423)
    plugin.friendly_name_map[(PREFIX, "Lounge Lamps")] = dev.id
    plugin._process_message(f"{PREFIX}/Lounge Lamps",
                            {"state": "ON", "brightness": 254, "color_temp": 370})
    assert dev.states["onOffState"] is True
    assert dev.states["brightnessLevel"] == 100


def test_group_commands_go_to_the_group(plugin, make_device, make_action, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    light = _group_dev(plugin, make_device, dev_id=2424)
    switch = _group_dev(plugin, make_device, type_id="z2mGroupRelay", dev_id=2425,
                        gid=11, name="All Plugs")
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDimmerRelayAction.TurnOn), light)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOff), switch)
    plugin.action_set_brightness(make_action(props={"brightness": "40"}), light)
    assert out == [(f"{PREFIX}/Lounge Lamps/set", {"state": "ON"}),
                   (f"{PREFIX}/All Plugs/set", {"state": "OFF"}),
                   (f"{PREFIX}/Lounge Lamps/set", {"brightness": 102, "state": "ON"})]


def test_a_status_request_on_a_group_sends_nothing(plugin, make_device, make_action,
                                                   monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2426, on=True)
    plugin.bridge_groups[PREFIX] = {10: _group(10, "Lounge Lamps", "0xa")}
    light = _group_dev(plugin, make_device, dev_id=2427)
    switch = _group_dev(plugin, make_device, type_id="z2mGroupRelay", dev_id=2428,
                        gid=12, name="Plugs")
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDimmerRelayAction.RequestStatus), light)
    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.RequestStatus), switch)
    assert out == []
    assert light.states["onOffState"] is True


# ── keeping current ──────────────────────────────────────────────────────────

def test_members_rename_and_colour_follow_zigbee2mqtt(plugin, make_device):
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2430)
    _member(plugin, make_device, "0xc", "Lamp C", COLOUR_BULB, 2431)
    dev = _group_dev(plugin, make_device, dev_id=2432)
    plugin.friendly_name_map[(PREFIX, "Lounge Lamps")] = dev.id
    plugin._process_bridge_groups([_group(10, "Lounge Lamps", "0xa")], PREFIX)
    assert dev.states["memberCount"] == 1
    assert dev.states["members"] == "Lamp A (Indigo)"
    plugin._process_bridge_groups([_group(10, "Front Room Lamps", "0xa", "0xc")], PREFIX)
    dev = indigo.devices[dev.id]
    assert dev.pluginProps["friendly_name"] == "Front Room Lamps"
    assert dev.name == "Front Room Lamps"
    assert plugin.friendly_name_map[(PREFIX, "Front Room Lamps")] == dev.id
    assert (PREFIX, "Lounge Lamps") not in plugin.friendly_name_map
    assert dev.pluginProps["has_color"] is True, "a colour member makes it a colour group"
    assert dev.states["memberCount"] == 2


def test_a_renamed_indigo_device_keeps_its_own_name(plugin, make_device):
    dev = _group_dev(plugin, make_device, dev_id=2433, name="My Name")
    props = dict(dev.pluginProps)
    props["friendly_name"] = "Lounge Lamps"
    dev.replacePluginPropsOnServer(props)
    plugin._process_bridge_groups([_group(10, "Snug Lamps")], PREFIX)
    assert indigo.devices[dev.id].name == "My Name"
    assert indigo.devices[dev.id].pluginProps["friendly_name"] == "Snug Lamps"


def test_a_group_is_not_an_offline_device(plugin, make_device):
    coord = make_device(2440, "Z2M Bridge", "z2mCoordinator",
                        pluginProps={"mqtt_prefix": PREFIX},
                        states={"offlineDevices": 0, "offlineDeviceNames": "",
                                "lastUpdate": ""})
    plugin.coordinator_map[PREFIX] = coord.id
    dev = _group_dev(plugin, make_device, dev_id=2441)
    plugin.friendly_name_map[(PREFIX, "Lounge Lamps")] = dev.id
    plugin._process_message(f"{PREFIX}/Lounge Lamps/availability", {"state": "offline"})
    assert dev.states["availability"] == "offline"
    assert coord.states["offlineDevices"] == 0


def test_the_orphan_report_knows_groups(plugin, make_device, logs):
    _member(plugin, None, "0xa", "Lamp A", CT_BULB, 0)
    _group_dev(plugin, make_device, dev_id=2450, gid=10, name="Kept")
    _group_dev(plugin, make_device, dev_id=2451, gid=99, name="Gone")
    plugin.bridge_groups[PREFIX] = {10: _group(10, "Kept", "0xa")}
    plugin.report_orphaned_devices()
    text = "\n".join(logs.event_messages)
    assert "Gone" in text and "group 99" in text
    assert "Kept" not in text


def test_groups_are_not_offered_where_a_radio_is_needed(plugin, make_device):
    _group_dev(plugin, make_device, dev_id=2460)
    assert plugin.list_radio_devices() == [("none", "-- no devices --")]


def test_emptying_and_refilling_a_group_does_not_make_a_second_device(plugin, make_device,
                                                                      monkeypatch):
    _no_folders(plugin, monkeypatch)
    _member(plugin, make_device, "0xa", "Lamp A", CT_BULB, 2470)
    plugin._process_bridge_groups([], PREFIX)
    plugin._process_bridge_groups([_group(20, "Porch", "0xa")], PREFIX)
    plugin._process_bridge_groups([_group(20, "Porch")], PREFIX)
    plugin._process_bridge_groups([_group(20, "Porch", "0xa")], PREFIX)
    assert [d.name for d in _created()] == ["Porch"]


def test_member_names_fill_in_when_the_device_list_arrives_after(plugin, make_device):
    """At start-up the group list can come before the device list."""
    dev = _group_dev(plugin, make_device, dev_id=2471)
    plugin._process_bridge_groups([_group(10, "Lounge Lamps", "0xlate")], PREFIX)
    assert dev.states["members"] == "0xlate"
    plugin._process_bridge_devices(
        [{"ieee_address": "0xlate", "friendly_name": "Late Lamp", "type": "Router",
          "definition": {"exposes": CT_BULB, "model": "X"}}], PREFIX)
    assert dev.states["members"] == "Late Lamp"
