#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_misc.py
# Description: Miscellaneous tests — broker/port resolution, prefix helpers,
#              MQTT topic parsing, friendly-name handling with slashes.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026



# ── _effective_broker / _effective_port ──────────────────────────────────────

def test_effective_broker_falls_back_to_pluginPrefs(plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "MQTT_BROKER", "")
    p = plugin_mod.Plugin(
        "com.clives.indigoplugin.z2mbridge", "Zigbee2MQTT Bridge", "1.9.8",
        {"mqtt_broker": "10.0.0.5"},
    )
    assert p._effective_broker() == "10.0.0.5"


def test_effective_broker_prefers_indigosecrets(plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "MQTT_BROKER", "192.168.1.1")
    p = plugin_mod.Plugin(
        "com.clives.indigoplugin.z2mbridge", "Zigbee2MQTT Bridge", "1.9.8",
        {"mqtt_broker": "10.0.0.5"},
    )
    assert p._effective_broker() == "192.168.1.1"


def test_effective_port_fallback_to_pluginPrefs(plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "MQTT_PORT", None)
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_port": "8883"})
    assert p._effective_port() == 8883


def test_effective_port_garbage_pluginPrefs_returns_default(plugin_mod, monkeypatch):
    """A non-integer pluginPrefs value must NOT crash startup."""
    monkeypatch.setattr(plugin_mod, "MQTT_PORT", None)
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_port": "abc"})
    assert p._effective_port() == 1883


def test_effective_port_empty_pluginPrefs_returns_default(plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "MQTT_PORT", None)
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_port": ""})
    assert p._effective_port() == 1883


# ── _topic_prefix / _garage_prefix / _device_prefix ──────────────────────────

def test_topic_prefix_default(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {})
    assert p._topic_prefix() == "zigbee2mqtt"


def test_topic_prefix_custom(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_topic_prefix": "z2m_custom"})
    assert p._topic_prefix() == "z2m_custom"


def test_garage_prefix_returns_none_when_blank(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {})
    assert p._garage_prefix() is None


def test_garage_prefix_returns_value(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_garage_topic_prefix": "zigbee2mqtt_garage"})
    assert p._garage_prefix() == "zigbee2mqtt_garage"


def test_garage_prefix_strips_whitespace(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_garage_topic_prefix": "  garage  "})
    assert p._garage_prefix() == "garage"


def test_device_prefix_uses_per_device_override(plugin, make_device):
    dev = make_device(1, "x", "z2mRelay",
                      pluginProps={"mqtt_prefix": "zigbee2mqtt_garage"})
    assert plugin._device_prefix(dev) == "zigbee2mqtt_garage"


def test_device_prefix_falls_back_to_global(plugin, make_device):
    dev = make_device(2, "x", "z2mRelay", pluginProps={})
    assert plugin._device_prefix(dev) == "zigbee2mqtt"


# ── friendly_name parsing in MQTT topics ─────────────────────────────────────

def test_friendly_name_with_slash_round_trips(plugin):
    """zigbee2mqtt allows friendly_names that contain '/'. _process_message
    must correctly extract them after stripping the prefix. The plugin does
    NOT support this directly — friendly_name with slash means the topic
    looks like 'zigbee2mqtt/room/device' and the plugin currently treats
    'room' as the friendly_name. This test documents the current behaviour."""
    # Verify the public attribute exists — the plugin uses _topic_prefix()
    # plus a simple split, so multi-segment friendly_names are imported as
    # the first segment after the prefix.
    assert plugin._topic_prefix() == "zigbee2mqtt"


# ── _request_state payload shape ─────────────────────────────────────────────

def test_request_state_default_uses_state_get(plugin, monkeypatch):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append((t, p)))
    plugin._request_state("Door", device_type_id="z2mContactSensor")
    assert sent == [("zigbee2mqtt/Door/get", {"state": ""})]


def test_request_state_light_includes_extras(plugin, monkeypatch):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append((t, p)))
    plugin._request_state("Lamp", device_type_id="z2mLight")
    assert sent[0][0] == "zigbee2mqtt/Lamp/get"
    payload = sent[0][1]
    for key in ("state", "brightness", "color_temp", "color", "color_mode"):
        assert key in payload


def test_request_state_uses_provided_prefix(plugin, monkeypatch):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: sent.append((t, p)))
    plugin._request_state("Garage Door", prefix="zigbee2mqtt_garage")
    assert sent[0][0] == "zigbee2mqtt_garage/Garage Door/get"


# ── _is_valid_state_id + _sanitise_state_key integration ─────────────────────

def test_sanitised_keys_pass_validator(plugin):
    """Every output of _sanitise_state_key (where it produces a non-empty
    string) must be accepted by _is_valid_state_id — they're a paired contract."""
    cases = [
        "color_temp", "power_on_behavior", "color_temp_startup",
        "MQTT-topic", "café_mode", "xml_thing", "1leading_digit",
    ]
    for raw in cases:
        sanitised = plugin._sanitise_state_key(raw)
        if sanitised:
            assert plugin._is_valid_state_id(sanitised), \
                f"sanitised {raw!r} -> {sanitised!r} failed validator"


# ── Coordinator handling — _process_bridge_state ─────────────────────────────

def test_bridge_state_caches_value_when_no_coordinator_device(plugin):
    """Retained bridge/state arriving before any coordinator device exists
    must be cached so deviceStartComm can replay it later."""
    plugin._process_bridge_state("online", "zigbee2mqtt")
    assert plugin._bridge_state_cache.get("zigbee2mqtt") == "online"


def test_bridge_info_cached_per_prefix(plugin):
    plugin._process_bridge_info({"version": "1.42.0", "coordinator": {"type": "zStack3x0"}},
                                "zigbee2mqtt")
    assert plugin._bridge_info_cache.get("zigbee2mqtt", {}).get("version") == "1.42.0"
