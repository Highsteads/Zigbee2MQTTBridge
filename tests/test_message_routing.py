#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_message_routing.py
# Description: Tests for _process_message — the MQTT topic router. Covers
#              friendly-name parsing, prefix filtering, bridge/* dispatch,
#              and edge cases like the friendly_name-with-slash rule.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026


def _capture_routes(plugin, monkeypatch):
    """Stub every downstream handler so the test can assert on what
    _process_message dispatched."""
    calls = []
    monkeypatch.setattr(plugin, "_process_bridge_devices",
                        lambda payload, prefix: calls.append(("bridge_devices", prefix, payload)))
    monkeypatch.setattr(plugin, "_process_bridge_state",
                        lambda payload, prefix: calls.append(("bridge_state",   prefix, payload)))
    monkeypatch.setattr(plugin, "_process_bridge_info",
                        lambda payload, prefix: calls.append(("bridge_info",    prefix, payload)))
    # fname handlers gained a prefix kwarg in v1.9.22 (prefix-qualified lookups)
    monkeypatch.setattr(plugin, "_process_availability",
                        lambda fname, payload, prefix=None: calls.append(
                            ("availability", fname, payload, prefix)))
    monkeypatch.setattr(plugin, "_process_device_state",
                        lambda fname, payload, prefix=None: calls.append(
                            ("device_state", fname, payload, prefix)))
    return calls


# ── Topic prefix filtering ───────────────────────────────────────────────────

def test_ignores_messages_from_unknown_prefix(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("some_other_prefix/device/state", {"state": "ON"})
    assert calls == []


def test_routes_primary_prefix_device_state(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/Lounge Lamp", {"state": "ON"})
    assert calls == [("device_state", "Lounge Lamp", {"state": "ON"}, "zigbee2mqtt")]


def test_routes_garage_prefix(plugin_mod, monkeypatch):
    plugin = plugin_mod.Plugin("a", "b", "1.0",
        {"mqtt_topic_prefix": "zigbee2mqtt",
         "mqtt_garage_topic_prefix": "zigbee2mqtt_garage"})
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt_garage/Door", {"contact": True})
    assert calls == [("device_state", "Door", {"contact": True}, "zigbee2mqtt_garage")]


# ── Bridge sub-topics ────────────────────────────────────────────────────────

def test_routes_bridge_devices(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/bridge/devices", [{"ieee_address": "0x111"}])
    assert calls[0][0] == "bridge_devices"
    assert calls[0][1] == "zigbee2mqtt"


def test_routes_bridge_state(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/bridge/state", "online")
    # _capture_routes captures (label, prefix, payload)
    assert calls == [("bridge_state", "zigbee2mqtt", "online")]


def test_routes_bridge_info(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/bridge/info", {"version": "1.42.0"})
    assert calls[0][0] == "bridge_info"


def test_bridge_unknown_subtopic_ignored(plugin, monkeypatch):
    """bridge/converters, bridge/log etc. are valid Z2M topics but the plugin
    only handles devices/state/info — others must be silent no-ops."""
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/bridge/converters", {})
    plugin._process_message("zigbee2mqtt/bridge/log",        "hello")
    assert calls == []


# ── Availability topic parsing ───────────────────────────────────────────────

def test_routes_availability(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/Door/availability", {"state": "online"})
    assert calls == [("availability", "Door", {"state": "online"}, "zigbee2mqtt")]


def test_routes_availability_with_slash_in_friendly_name(plugin, monkeypatch):
    """A friendly_name like 'Hallway/Light' produces topic 'zigbee2mqtt/Hallway/Light/availability'.
    The router MUST extract 'Hallway/Light' as the friendly_name — joining
    parts[1:-1] — not just take parts[1]."""
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/Hallway/Light/availability",
                            {"state": "online"})
    assert calls == [("availability", "Hallway/Light", {"state": "online"}, "zigbee2mqtt")]


def test_routes_device_state_with_slash_in_friendly_name(plugin, monkeypatch):
    """Same rule for device-state topics."""
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt/Hallway/Light",
                            {"state": "ON"})
    assert calls == [("device_state", "Hallway/Light", {"state": "ON"}, "zigbee2mqtt")]


# ── Internal control topics ──────────────────────────────────────────────────

def test_connected_synthetic_topic_no_route(plugin, monkeypatch):
    """The __connected__ synthetic topic must not route as a device — it's
    handled inline (logs + sends bridge/request/devices). No device handler
    should be invoked."""
    calls = _capture_routes(plugin, monkeypatch)
    # Patch publish too so connect doesn't actually send
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append((t, p)))
    plugin._process_message("__connected__", {})
    assert calls == []   # no device routes
    # It SHOULD request bridge/devices though
    assert any(t.endswith("/bridge/request/devices") for t, _ in sent)


# ── Empty / malformed topics ─────────────────────────────────────────────────

def test_empty_topic_silent(plugin, monkeypatch):
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("", {})
    assert calls == []


def test_single_segment_topic_silent(plugin, monkeypatch):
    """A topic with no '/' (just 'zigbee2mqtt') is malformed — silent skip."""
    calls = _capture_routes(plugin, monkeypatch)
    plugin._process_message("zigbee2mqtt", {})
    assert calls == []
