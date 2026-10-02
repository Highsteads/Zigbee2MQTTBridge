#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2120_improvements.py
# Description: v2.12.0 — declared numeric presets in Device Settings, and a
#              device per channel for multi-channel switches.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""Neither has hardware in this house to test against, so both are built from
zigbee2mqtt's own definitions: the presets from the real Hue expose captured
in zoo_real/light_bulb.json, the channels from zigbee-herdsman-converters'
Base.withEndpoint, which suffixes each feature's property with the channel
(state -> state_l1) and stamps `endpoint` on the switch and its feature."""

import json
from pathlib import Path

import indigo  # stub

PREFIX = "zigbee2mqtt"
HUE = json.loads((Path(__file__).parent / "zoo_real" / "light_bulb.json")
                 .read_text(encoding="utf-8"))["exposes"]


def _spec(name):
    for feature in HUE[0]["features"]:
        if feature.get("name") == name:
            return feature
    raise KeyError(name)


def _published(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    return out


# ── presets ──────────────────────────────────────────────────────────────────

def test_a_preset_name_or_value_is_accepted(plugin_mod):
    coerce = plugin_mod.Plugin._coerce_setting
    spec = _spec("color_temp_startup")
    assert coerce(spec, "previous") == 65535
    assert coerce(spec, "Previous") == 65535
    assert coerce(spec, "65535") == 65535, "a preset's value may sit outside the range"
    assert coerce(spec, "warm") == 454
    assert coerce(spec, "300") == 300
    assert coerce(spec, "600") is None, "an ordinary number outside the range is still refused"
    assert coerce(spec, "toasty") is None


def test_saving_a_preset_sends_its_value(plugin, make_device, monkeypatch):
    dev = make_device(2201, "Hue", "z2mLight",
                      pluginProps={"friendly_name": "Hue", "ieee_address": "0xhue",
                                   "mqtt_prefix": PREFIX},
                      states={"colorTempStartup": 370})
    plugin.bridge_devices["0xhue"] = {"ieee_address": "0xhue", "_mqtt_prefix": PREFIX,
                                      "definition": {"exposes": HUE}}
    out = _published(plugin, monkeypatch)
    plugin.closedDeviceConfigUi({"z2mset_color_temp_startup": "previous"},
                                False, "z2mLight", dev.id)
    assert out == [(f"{PREFIX}/Hue/set", {"color_temp_startup": 65535})]


def test_a_device_holding_the_preset_is_not_drift(plugin, make_device, monkeypatch):
    dev = make_device(2202, "Hue", "z2mLight",
                      pluginProps={"friendly_name": "Hue", "ieee_address": "0xhue",
                                   "mqtt_prefix": PREFIX,
                                   "z2mset_color_temp_startup": "previous"})
    plugin.bridge_devices["0xhue"] = {"ieee_address": "0xhue", "_mqtt_prefix": PREFIX,
                                      "definition": {"exposes": HUE}}
    out = _published(plugin, monkeypatch)
    plugin._check_setting_drift(dev, {"color_temp_startup": 65535})
    assert out == []
    plugin._check_setting_drift(dev, {"color_temp_startup": 250})
    assert out == [(f"{PREFIX}/Hue/set", {"color_temp_startup": 65535})]


def test_the_dialog_offers_the_presets_and_names_the_current_one(plugin, make_device):
    dev = make_device(2203, "Hue", "z2mLight",
                      pluginProps={"friendly_name": "Hue", "ieee_address": "0xhue",
                                   "mqtt_prefix": PREFIX},
                      states={"colorTempStartup": 65535})
    plugin.bridge_devices["0xhue"] = {"ieee_address": "0xhue", "_mqtt_prefix": PREFIX,
                                      "definition": {"exposes": HUE}}
    xml = plugin._build_settings_fields(dev, plugin._managed_settings_for(dev))
    assert "Or type one of: coolest, cool, neutral, warm, warmest, previous." in xml
    assert "Currently reporting: 65535 (previous)." in xml


# ── switch channels ──────────────────────────────────────────────────────────

def _switch(endpoint=None):
    feature = {"type": "binary", "name": "state", "label": "State", "access": 7,
               "property": f"state_{endpoint}" if endpoint else "state",
               "value_on": "ON", "value_off": "OFF", "value_toggle": "TOGGLE"}
    entry = {"type": "switch", "features": [feature]}
    if endpoint:
        feature["endpoint"] = endpoint
        entry["endpoint"] = endpoint
    return entry


TS0002 = [_switch("l1"), _switch("l2"),
          {"type": "enum", "name": "power_on_behavior", "property": "power_on_behavior",
           "access": 7, "values": ["off", "on", "previous"]}]


def test_layout_of_each_kind_of_switch(plugin_mod):
    from z2m_detection import _switch_layout
    assert _switch_layout([_switch()]) == ("state", [])
    assert _switch_layout(TS0002) == ("state_l1", ["l2"])
    assert _switch_layout([_switch(), _switch("l1"), _switch("l2")]) == ("state", ["l1", "l2"])
    assert _switch_layout([_switch("left"), _switch("right")]) == ("state_left", ["right"])


def test_a_two_channel_switch_is_a_relay(plugin_mod):
    assert plugin_mod._detect_device_type(TS0002, "TS0002") == "z2mRelay"


def _two_gang(plugin, make_device, dev_id=2210):
    dev = make_device(dev_id, "Landing Switch", "z2mRelay",
                      pluginProps={"friendly_name": "Landing", "ieee_address": "0xgang",
                                   "mqtt_prefix": PREFIX},
                      states={"onOffState": False})
    plugin.bridge_devices["0xgang"] = {"ieee_address": "0xgang", "friendly_name": "Landing",
                                       "_mqtt_prefix": PREFIX,
                                       "definition": {"exposes": TS0002}}
    plugin.friendly_name_map[(PREFIX, "Landing")] = dev.id
    plugin.ieee_map["0xgang"] = dev.id
    return dev


def test_the_device_follows_its_first_channel(plugin, make_device):
    dev = _two_gang(plugin, make_device)
    plugin._process_device_state("Landing", {"state_l1": "ON", "state_l2": "OFF"},
                                 prefix=PREFIX)
    assert dev.states["onOffState"] is True


def test_the_device_switches_its_first_channel(plugin, make_device, make_action,
                                               monkeypatch):
    dev = _two_gang(plugin, make_device)
    out = _published(plugin, monkeypatch)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.RequestStatus),
                               dev)
    assert out == [(f"{PREFIX}/Landing/set", {"state_l1": "ON"}),
                   (f"{PREFIX}/Landing/get", {"state_l1": ""})]


def test_an_ordinary_relay_is_unchanged(plugin, make_device, make_action, monkeypatch):
    dev = make_device(2211, "Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Plug", "ieee_address": "0xplug",
                                   "mqtt_prefix": PREFIX})
    plugin.bridge_devices["0xplug"] = {"definition": {"exposes": [_switch()]}}
    out = _published(plugin, monkeypatch)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOff), dev)
    assert out == [(f"{PREFIX}/Plug/set", {"state": "OFF"})]


def test_the_second_channel_is_offered_and_made(plugin, make_device):
    dev = _two_gang(plugin, make_device)
    assert plugin._offered_secondaries(dev) == ["channel_l2"]
    plugin._sync_secondaries(dev, {"z2msec_channel_l2": "true"})
    child = indigo.devices[plugin._secondary_dev_id(dev, "channel_l2")]
    assert child.deviceTypeId == "z2mRelayChannel"
    assert child.name == "Landing Switch [Channel L2]"
    assert child.pluginProps["channel_endpoint"] == "l2"
    assert child.id in indigo.device.groups.get(dev.id, set())


def test_the_channel_follows_and_switches_its_own_channel(plugin, make_device, make_action,
                                                         monkeypatch):
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: None)
    dev = _two_gang(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_channel_l2": "true"})
    child = indigo.devices[plugin._secondary_dev_id(dev, "channel_l2")]
    plugin.deviceStartComm(child)
    assert plugin.friendly_name_map[(PREFIX, "Landing")] == dev.id, "a channel is not a radio"

    plugin._process_device_state("Landing", {"state_l1": "OFF", "state_l2": "ON"},
                                 prefix=PREFIX)
    assert child.states["onOffState"] is True
    assert dev.states["onOffState"] is False

    out = _published(plugin, monkeypatch)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.Toggle), child)
    assert out == [(f"{PREFIX}/Landing/set", {"state_l2": "OFF"})]


def test_the_channel_follows_a_rename_of_its_parent(plugin, make_device, make_action,
                                                   monkeypatch):
    dev = _two_gang(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_channel_l2": "true"})
    child = indigo.devices[plugin._secondary_dev_id(dev, "channel_l2")]
    props = dict(dev.pluginProps)
    props["friendly_name"] = "Upstairs Landing"
    dev.replacePluginPropsOnServer(props)
    out = _published(plugin, monkeypatch)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), child)
    assert out == [(f"{PREFIX}/Upstairs Landing/set", {"state_l2": "ON"})]


def test_a_channel_without_its_parent_sends_nothing(plugin, make_device, make_action,
                                                   monkeypatch, logs):
    child = make_device(2212, "Orphan [Channel L2]", "z2mRelayChannel",
                        pluginProps={"primary_device_id": "999999",
                                     "channel_endpoint": "l2"})
    out = _published(plugin, monkeypatch)
    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), child)
    assert out == []
    assert any("cannot find the switch" in m for m in logs.at("ERROR"))


def test_unticking_a_channel_never_deletes_it(plugin, make_device):
    dev = _two_gang(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_channel_l2": "true"})
    child_id = plugin._secondary_dev_id(dev, "channel_l2")
    plugin._sync_secondaries(dev, {"z2msec_channel_l2": "false"})
    assert child_id in indigo.devices
    assert "[UNUSED" in indigo.devices[child_id].name


def test_the_channel_type_is_declared_as_a_relay():
    import xml.etree.ElementTree as ET
    server = Path(__file__).resolve().parent.parent / "Zigbee2MQTTBridge.indigoPlugin" \
        / "Contents" / "Server Plugin" / "Devices.xml"
    node = ET.parse(server).getroot().find("Device[@id='z2mRelayChannel']")
    assert node is not None and node.get("type") == "relay"
    assert node.get("allowUserCreation") == "false"
