#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1916_fixes.py
# Description: Regression tests for the v1.9.16 audit fixes: the pure-Python
#              gamma-corrected _xy_to_rgb (colormath removed), the paho-thread
#              logging discipline fix (subscribed list rides the __connected__
#              queue message), and the bridge-payload type-check warnings.
# Author:      CliveS & Claude Fable 5
# Date:        10-06-2026
# Version:     1.0

import queue


# ── _xy_to_rgb: pure Python, gamma-encoded ───────────────────────────────────

def test_colormath_is_gone(plugin_mod):
    # The dependency was removed in v1.9.16 — the module must not even carry
    # the availability flag, let alone import it.
    assert not hasattr(plugin_mod, "COLORMATH_AVAILABLE")
    import sys
    assert "colormath" not in sys.modules


def test_xy_white_point_is_near_neutral(plugin_mod):
    r, g, b = plugin_mod._xy_to_rgb(0.3127, 0.3290)     # D65 white
    assert max(r, g, b) >= 95                            # peak-scaled bright
    assert max(r, g, b) - min(r, g, b) <= 10             # near-equal channels


def test_xy_primaries_dominate_the_right_channel(plugin_mod):
    r, g, b = plugin_mod._xy_to_rgb(0.64, 0.33)          # red-ish
    assert r > 90 and r > g > b
    r, g, b = plugin_mod._xy_to_rgb(0.30, 0.60)          # green-ish
    assert g > 90 and g > r > b
    r, g, b = plugin_mod._xy_to_rgb(0.15, 0.06)          # blue-ish
    assert b > 90 and b > max(r, g) - 5


def test_xy_outputs_always_in_range(plugin_mod):
    for x in (0.0, 0.1, 0.3127, 0.5, 0.7, 1.0):
        for y in (0.0, 0.1, 0.329, 0.6, 1.0):
            r, g, b = plugin_mod._xy_to_rgb(x, y)
            assert all(isinstance(c, int) and 0 <= c <= 100 for c in (r, g, b))


# ── paho-thread discipline: subscribe log moved onto the main thread ─────────

class _FakeClient:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))


def test_on_connect_queues_subscribed_list_without_logging(plugin, plugin_mod, monkeypatch):
    # The callback runs on the paho thread — it must queue, never call log()
    # (which is indigo.server.log under the bonnet).
    logged = []
    monkeypatch.setattr(plugin_mod, "log", lambda *a, **k: logged.append(a))
    client = _FakeClient()
    plugin.msg_queue = queue.Queue()

    plugin._on_mqtt_connect(client, None, None, 0)

    assert plugin.mqtt_connected is True
    assert ("zigbee2mqtt/#", 1) in client.subscriptions
    topic, payload = plugin.msg_queue.get_nowait()
    assert topic == "__connected__"
    assert payload["subscribed"] == ["zigbee2mqtt/#"]
    assert logged == [], "no Indigo log calls allowed on the paho thread"


def test_connected_handler_logs_subscriptions_on_main_thread(plugin, plugin_mod, monkeypatch):
    logged = []
    monkeypatch.setattr(plugin_mod, "log", lambda msg, **k: logged.append(msg))
    monkeypatch.setattr(plugin, "_publish", lambda *a, **k: None)

    plugin._process_message("__connected__", {"subscribed": ["zigbee2mqtt/#"]})

    assert any("MQTT subscribed to: zigbee2mqtt/#" in m for m in logged)


def test_connected_handler_tolerates_legacy_empty_payload(plugin, monkeypatch):
    # Older queue entries (or a future producer change) may carry {} — the
    # handler must not KeyError.
    monkeypatch.setattr(plugin, "_publish", lambda *a, **k: None)
    plugin._process_message("__connected__", {})


# ── Bridge payloads of the wrong type now warn instead of vanishing ──────────

def test_bridge_devices_wrong_type_warns_and_keeps_cache(plugin, plugin_mod, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        plugin_mod, "log",
        lambda msg, level="INFO": warnings.append(msg) if level == "WARNING" else None)
    plugin.bridge_devices = {"0xabc": {"_mqtt_prefix": "zigbee2mqtt"}}

    plugin._process_bridge_devices("error-string", "zigbee2mqtt")

    assert plugin.bridge_devices == {"0xabc": {"_mqtt_prefix": "zigbee2mqtt"}}
    assert any("bridge/devices" in w and "str" in w for w in warnings)


def test_bridge_info_wrong_type_warns(plugin, plugin_mod, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        plugin_mod, "log",
        lambda msg, level="INFO": warnings.append(msg) if level == "WARNING" else None)

    plugin._process_bridge_info(["not", "a", "dict"], "zigbee2mqtt")

    assert any("bridge/info" in w and "list" in w for w in warnings)
