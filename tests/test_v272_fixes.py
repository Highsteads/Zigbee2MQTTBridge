#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v272_fixes.py
# Description: v2.7.2 — the stored IEEE follows the friendly_name; the rename
#              detector cannot steal a name another device owns; a device seen
#              before z2m interviewed it is still created.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0
"""Live case: Living Room Right Presence Sensor was made by duplicating Centre in
the Indigo client, so it carried Centre's IEEE while zigbee2mqtt had the Right
radio elsewhere. The dialog shows the field read-only, so only the plugin can
put it right."""


def _z2m(ieee, fname, exposes=None, model="", interviewed=True):
    d = {"ieee_address": ieee, "friendly_name": fname, "type": "EndDevice"}
    d["definition"] = ({"exposes": exposes or [], "model": model, "vendor": "TestVendor"}
                       if interviewed else None)
    return d


def _props(fname, ieee):
    return {"friendly_name": fname, "ieee_address": ieee, "mqtt_prefix": "zigbee2mqtt"}


def test_stored_ieee_follows_the_friendly_name(plugin, make_device):
    centre = make_device(150, "Centre", "z2mSensor", pluginProps=_props("Centre", "0xA"))
    right  = make_device(151, "Right",  "z2mSensor", pluginProps=_props("Right",  "0xA"))
    plugin.ieee_map["0xA"] = right.id          # last deviceStartComm wins, as live
    plugin.friendly_name_map[("zigbee2mqtt", "Centre")] = centre.id
    plugin.friendly_name_map[("zigbee2mqtt", "Right")]  = right.id

    plugin._process_bridge_devices([_z2m("0xA", "Centre"), _z2m("0xB", "Right")],
                                   prefix="zigbee2mqtt")

    assert right.pluginProps["ieee_address"]  == "0xB"
    assert centre.pluginProps["ieee_address"] == "0xA"
    # the rename detector must NOT have rewritten the copy to the original's name
    assert right.pluginProps["friendly_name"]  == "Right"
    assert centre.pluginProps["friendly_name"] == "Centre"
    assert plugin.ieee_map["0xB"] == right.id
    assert plugin.ieee_map["0xA"] == centre.id, "the old address goes back to its real owner"
    assert plugin.friendly_name_map[("zigbee2mqtt", "Centre")] == centre.id
    assert plugin.friendly_name_map[("zigbee2mqtt", "Right")]  == right.id


def test_rename_detector_will_not_steal_a_name_another_device_owns(plugin, make_device):
    real  = make_device(152, "Sensor", "z2mSensor", pluginProps=_props("Sensor", "0xC"))
    ghost = make_device(153, "Ghost",  "z2mSensor", pluginProps=_props("Ghost",  "0xC"))
    plugin.ieee_map["0xC"] = ghost.id
    plugin.friendly_name_map[("zigbee2mqtt", "Sensor")] = real.id
    plugin.friendly_name_map[("zigbee2mqtt", "Ghost")]  = ghost.id

    for _ in range(2):    # a second refresh must not warn or act again
        plugin._process_bridge_devices([_z2m("0xC", "Sensor")], prefix="zigbee2mqtt")

    assert ghost.pluginProps["friendly_name"] == "Ghost"
    assert ghost.name == "Ghost"
    assert plugin.friendly_name_map[("zigbee2mqtt", "Sensor")] == real.id
    assert plugin._dup_binding_warned == {ghost.id}


def test_a_genuine_rename_still_lands(plugin, make_device):
    dev = make_device(154, "Old", "z2mSensor", pluginProps=_props("Old", "0xD"))
    plugin.ieee_map["0xD"] = dev.id
    plugin.friendly_name_map[("zigbee2mqtt", "Old")] = dev.id

    plugin._process_bridge_devices([_z2m("0xD", "New")], prefix="zigbee2mqtt")

    assert dev.pluginProps["friendly_name"] == "New"
    assert plugin.friendly_name_map.get(("zigbee2mqtt", "New")) == dev.id
    assert ("zigbee2mqtt", "Old") not in plugin.friendly_name_map


def test_uninterviewed_device_is_created_once_z2m_finishes(plugin, monkeypatch):
    import indigo
    from indigo_stub import DeviceShim
    monkeypatch.setattr(indigo, "device", DeviceShim(indigo.devices), raising=False)
    relay = [{"type": "switch",
              "features": [{"name": "state", "type": "binary", "access": 7}]}]
    # Baseline for the prefix must be non-empty (startup flood guard).
    plugin.bridge_devices = {"0x1": {"ieee_address": "0x1", "friendly_name": "Existing",
                                     "_mqtt_prefix": "zigbee2mqtt",
                                     "definition": {"exposes": []}}}

    plugin._process_bridge_devices(
        [_z2m("0x1", "Existing"), _z2m("0x2", "Joiner", interviewed=False)],
        prefix="zigbee2mqtt")
    assert not [d for d in indigo.devices if d.name == "Joiner"], "not interviewed yet"

    plugin._process_bridge_devices(
        [_z2m("0x1", "Existing"), _z2m("0x2", "Joiner", exposes=relay, model="TS011F")],
        prefix="zigbee2mqtt")
    created = [d for d in indigo.devices if d.name == "Joiner"]
    assert created, "a device first seen uninterviewed must be created once it is"
    assert created[0].deviceTypeId == "z2mRelay"
