#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2150_scenes.py
# Description: v2.15.0 — recall, store and remove Zigbee scenes for a group or
#              a single light.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""Payloads from zigbee-herdsman-converters toZigbee.ts (scene_recall,
scene_store, scene_remove); scene lists from zigbee2mqtt bridge.ts, which puts
{id, name} under a group's `scenes` and under each device endpoint's
`scenes`."""

PREFIX = "zigbee2mqtt"


def _published(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    return out


def _group(plugin, make_device, scenes, dev_id=2501):
    dev = make_device(dev_id, "Lounge Lamps", "z2mGroupLight",
                      pluginProps={"friendly_name": "Lounge Lamps", "mqtt_prefix": PREFIX,
                                   "group_id": "5"})
    plugin.bridge_groups[PREFIX] = {5: {"id": 5, "friendly_name": "Lounge Lamps",
                                        "members": [], "scenes": scenes}}
    return dev


def _light(plugin, make_device, endpoint_scenes, dev_id=2502):
    dev = make_device(dev_id, "Hall Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Hall Lamp", "ieee_address": "0xhl",
                                   "mqtt_prefix": PREFIX})
    plugin.bridge_devices["0xhl"] = {
        "ieee_address": "0xhl", "_mqtt_prefix": PREFIX,
        "endpoints": {str(ep): {"scenes": s} for ep, s in endpoint_scenes.items()}}
    return dev


EVENING = {"id": 1, "name": "Evening"}
READING = {"id": 3, "name": "Reading"}


def test_a_groups_scenes_are_listed(plugin, make_device):
    dev = _group(plugin, make_device, [READING, EVENING])
    assert plugin.list_device_scenes(targetId=dev.id) == [("1", "Evening (1)"),
                                                          ("3", "Reading (3)")]
    assert plugin.list_device_scenes(filter="store", targetId=dev.id)[0] == ("new",
                                                                             "A new scene")


def test_a_lights_scenes_come_from_every_endpoint_once(plugin, make_device):
    dev = _light(plugin, make_device, {11: [EVENING], 12: [EVENING, READING]})
    assert plugin._scenes_for(dev) == [(1, "Evening"), (3, "Reading")]


def test_no_scenes_says_so(plugin, make_device):
    dev = _group(plugin, make_device, [])
    assert plugin.list_device_scenes(targetId=dev.id) == [("none",
                                                           "-- no scenes stored yet --")]


def test_recall(plugin, make_device, make_action, monkeypatch):
    dev = _group(plugin, make_device, [EVENING])
    out = _published(plugin, monkeypatch)
    plugin.action_recall_scene(make_action(props={"scene": "1"}), dev)
    assert out == [(f"{PREFIX}/Lounge Lamps/set", {"scene_recall": 1})]


def test_a_new_scene_takes_the_lowest_free_number(plugin, make_device, make_action,
                                                  monkeypatch):
    dev = _group(plugin, make_device, [EVENING, READING])
    out = _published(plugin, monkeypatch)
    plugin.action_store_scene(make_action(props={"scene": "new", "sceneName": "Film"}), dev)
    plugin.action_store_scene(make_action(props={"scene": "new", "sceneName": ""}), dev)
    assert out == [(f"{PREFIX}/Lounge Lamps/set", {"scene_store": {"ID": 2, "name": "Film"}}),
                   (f"{PREFIX}/Lounge Lamps/set", {"scene_store": {"ID": 2, "name": "Scene 2"}})]


def test_overwriting_keeps_the_name_unless_given_one(plugin, make_device, make_action,
                                                     monkeypatch):
    dev = _group(plugin, make_device, [EVENING])
    out = _published(plugin, monkeypatch)
    plugin.action_store_scene(make_action(props={"scene": "1", "sceneName": ""}), dev)
    plugin.action_store_scene(make_action(props={"scene": "1", "sceneName": "Late"}), dev)
    assert [p for _, p in out] == [{"scene_store": {"ID": 1, "name": "Evening"}},
                                   {"scene_store": {"ID": 1, "name": "Late"}}]


def test_every_number_used_sends_nothing(plugin, make_device, make_action, monkeypatch,
                                         logs):
    dev = _group(plugin, make_device, [{"id": n, "name": f"S{n}"} for n in range(1, 256)])
    out = _published(plugin, monkeypatch)
    plugin.action_store_scene(make_action(props={"scene": "new"}), dev)
    assert out == []
    assert any("every scene number is in use" in m for m in logs.at("WARNING"))


def test_remove(plugin, make_device, make_action, monkeypatch):
    dev = _light(plugin, make_device, {11: [READING]})
    out = _published(plugin, monkeypatch)
    plugin.action_remove_scene(make_action(props={"scene": "3"}), dev)
    assert out == [(f"{PREFIX}/Hall Lamp/set", {"scene_remove": 3})]


def test_no_scene_chosen_sends_nothing(plugin, make_device, make_action, monkeypatch, logs):
    dev = _group(plugin, make_device, [])
    out = _published(plugin, monkeypatch)
    for method in (plugin.action_recall_scene, plugin.action_remove_scene):
        method(make_action(props={"scene": "none"}), dev)
    plugin.action_store_scene(make_action(props={"scene": "0"}), dev)
    assert out == []
    assert len(logs.at("WARNING")) == 3


def test_the_dialogs_are_checked(plugin):
    def errors(type_id, **values):
        return dict(plugin.validateActionConfigUi(values, type_id, 0)[2])
    assert "scene" in errors("recallScene", scene="none")
    assert errors("recallScene", scene="4") == {}
    assert errors("storeScene", scene="new", sceneName="Evening") == {}
    assert "sceneName" in errors("storeScene", scene="new", sceneName="x" * 65)
    assert "scene" in errors("removeScene", scene="")


def test_a_group_device_shows_its_scenes(plugin, make_device):
    dev = _group(plugin, make_device, [], dev_id=2503)
    plugin._process_bridge_groups([{"id": 5, "friendly_name": "Lounge Lamps",
                                    "members": [], "scenes": [EVENING, READING]}], PREFIX)
    assert dev.states["scenes"] == "Evening (1), Reading (3)"
