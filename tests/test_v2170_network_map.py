#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2170_network_map.py
# Description: v2.17.0 — Report Network Map.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""The map is built the way zigbee2mqtt 2.14.2 networkMap.ts builds it: each
router's neighbour table becomes links whose TARGET is that router and whose
SOURCE is the neighbour, `lqi` being how well the target hears it, and
relationship 1 meaning the source is the target's child. Names and addresses
are made up; the shape and the kinds of trouble come from a real scan of the
house network on 02-10-2026."""

import z2m_network_map as nm

PREFIX = "zigbee2mqtt"
COORD, HALL, LAMP, DEAD = "0xc0", "0xr1", "0xr2", "0xr3"
DOOR, WINDOW, BOILER, BUSY = "0xe1", "0xe2", "0xe3", "0xe4"


def _node(ieee, name, kind, failed=None):
    node = {"ieeeAddr": ieee, "friendlyName": name, "type": kind}
    if failed:
        node["failed"] = failed
    return node


def _link(source, target, lqi, relationship):
    return {"source": {"ieeeAddr": source}, "target": {"ieeeAddr": target},
            "lqi": lqi, "linkquality": lqi, "relationship": relationship, "routes": []}


MAP = {
    "nodes": [_node(COORD, "Coordinator", "Coordinator"),
              _node(HALL, "Hall Repeater", "Router"),
              _node(LAMP, "Landing Lamp", "Router"),
              _node(DEAD, "Loft Repeater", "Router", failed=["lqi", "routingTable"]),
              _node(DOOR, "Back Door", "EndDevice"),
              _node(WINDOW, "Study Window", "EndDevice"),
              _node(BOILER, "Boiler Leak", "EndDevice"),
              _node(BUSY, "Landing Motion", "EndDevice")],
    "links": [_link(HALL, COORD, 150, 2), _link(COORD, HALL, 160, 2),
              _link(LAMP, COORD, 20, 2),
              _link(DOOR, HALL, 200, 1),
              # The best parent wins, whichever order the links come in.
              _link(WINDOW, LAMP, 70, 1), _link(WINDOW, HALL, 30, 1),
              _link(BUSY, LAMP, 12, 1),
              # Heard better by the lamp, but not its child: not a parent.
              _link(DOOR, LAMP, 240, 3)],
}


def _summary(is_light=lambda ieee: ieee == LAMP):
    return nm.summarise_network_map(MAP, lambda ieee, name: name, is_light)


def test_counts():
    assert _summary()["counts"] == {"Coordinator": 1, "Router": 3, "EndDevice": 4}


def test_each_device_takes_its_best_parent_and_weakest_comes_first():
    assert _summary()["devices"] == [("Landing Motion", "Landing Lamp", 12),
                                     ("Study Window", "Landing Lamp", 70),
                                     ("Back Door", "Hall Repeater", 200)]


def test_trouble_is_found():
    summary = _summary()
    assert summary["no_route"] == ["Boiler Leak"]
    assert summary["weak"] == [("Landing Motion", "Landing Lamp", 12)]
    assert summary["not_scanned"] == ["Loft Repeater"]


def test_routers_busiest_first_with_what_the_coordinator_hears():
    assert _summary()["routers"] == [("Landing Lamp", 2, 20, True, True),
                                     ("Hall Repeater", 1, 150, False, True),
                                     ("Loft Repeater", 0, None, False, False)]


def test_an_empty_or_broken_map_is_survivable():
    for value in (None, {}, {"nodes": None, "links": None}, {"nodes": ["x"], "links": [1]}):
        assert nm.summarise_network_map(value, lambda i, n: n)["devices"] == []


# ── the report ───────────────────────────────────────────────────────────────

def test_the_report_names_the_trouble_in_plain_words(plugin, logs, monkeypatch):
    monkeypatch.setattr(plugin, "_map_is_light", lambda ieee: ieee == LAMP)
    plugin._report_network_map(PREFIX, {"value": MAP}, True, None, seconds=130.4)
    warned = logs.at("WARNING")
    assert any("Boiler Leak: no router lists it" in m for m in warned)
    assert any("Landing Motion: talks through Landing Lamp, and the link is weak "
               "(12 out of 255)" in m for m in warned)
    assert any("Loft Repeater did not answer the scan" in m for m in warned)
    text = "\n".join(logs.event_messages)
    assert "1 coordinator" not in text and "3 routers that pass messages on" in text
    assert "The scan took 130 seconds." in text
    assert "Landing Lamp: 2 devices rely on it, and the coordinator hears it at 20 " \
           "out of 255. It is a light" in text
    assert "Hall Repeater: 1 device relies on it, and the coordinator hears it at " \
           "150 out of 255." in text
    assert not any("Hall Repeater" in m and "It is a light" in m for m in logs.event_messages)
    assert "Nothing needs attention" not in text
    assert "Loft Repeater: did not answer the scan, so what relies on it is not known." in text
    assert "Back Door: through Hall Repeater, at 200 out of 255." in text


def test_a_healthy_network_says_so(plugin, logs):
    healthy = {"nodes": [_node(COORD, "C", "Coordinator"), _node(HALL, "Hall", "Router"),
                         _node(DOOR, "Door", "EndDevice")],
               "links": [_link(HALL, COORD, 200, 2), _link(DOOR, HALL, 200, 1)]}
    plugin._report_network_map(PREFIX, {"value": healthy}, True, None)
    assert logs.at("WARNING") == []
    assert any("Nothing needs attention" in m for m in logs.event_messages)


def test_a_refused_map_says_why(plugin, logs):
    plugin._report_network_map(PREFIX, {}, False, "Type 'raw' not supported")
    assert any("could not map the network: Type 'raw' not supported" in m
               for m in logs.at("WARNING"))


# ── asking for it ────────────────────────────────────────────────────────────

def test_the_menu_asks_for_a_raw_map_with_routes(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    plugin.menu_network_map({"bridge": PREFIX})
    topic, body = out[0]
    assert topic == f"{PREFIX}/bridge/request/networkmap"
    assert body["type"] == "raw" and body["routes"] is True and body["transaction"]


def test_the_reply_is_reported_and_timed(plugin, monkeypatch, logs):
    monkeypatch.setattr(plugin, "_publish", lambda t, p: True)
    plugin.menu_network_map({"bridge": PREFIX})
    transaction, request = next(iter(plugin._bridge_requests.items()))
    request["sent"] -= 42
    plugin._process_message(f"{PREFIX}/bridge/response/networkmap",
                            {"status": "ok", "transaction": transaction,
                             "data": {"type": "raw", "routes": True, "value": MAP}})
    assert any("The scan took 42 seconds." in m for m in logs.event_messages)
    assert plugin._bridge_requests == {}


def test_someone_elses_map_is_ignored(plugin, logs):
    plugin._process_message(f"{PREFIX}/bridge/response/networkmap",
                            {"status": "ok", "transaction": "frontend-1",
                             "data": {"value": MAP}})
    assert not any("network map" in m for m in logs.event_messages)


def test_a_large_network_gets_time_to_answer(plugin, monkeypatch, logs):
    monkeypatch.setattr(plugin, "_publish", lambda t, p: True)
    plugin.menu_network_map({"bridge": PREFIX})
    for request in plugin._bridge_requests.values():
        request["sent"] -= 600
    plugin._check_bridge_requests()
    assert logs.at("WARNING") == [], "ten minutes is not yet too long"
    for request in plugin._bridge_requests.values():
        request["sent"] -= 301
    plugin._check_bridge_requests()
    assert any("did not answer the network map" in m for m in logs.at("WARNING"))


def test_the_action_needs_a_bridge(plugin):
    ok, _v, errors = plugin.validateActionConfigUi({"bridge": "none"}, "networkMap", 0)
    assert not ok and "bridge" in errors
