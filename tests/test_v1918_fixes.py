#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1918_fixes.py
# Description: Regression tests for the v1.9.18/1.9.19 deep-review batches:
#              the runtime reclassify guard, the MQTT liveness watchdog + paho
#              ingress paths (previously untested), the atomic MQTT rebuild, the
#              catch-all sensor motion store, the lastAction "other" fallback,
#              and the colour/port robustness folds.
# Author:      CliveS & Claude Opus 4.8
# Date:        26-06-2026
# Version:     1.0

import queue
import time

import pytest


# ── Robustness folds: colour + port coercion ─────────────────────────────────

def test_hs_to_rgb_clamps_out_of_range(plugin_mod):
    # A malformed payload (saturation > 255, hue > 360) must NOT push channels
    # negative or above 100 — the xy path already clamps, hs now does too.
    for hue, sat in [(720, 999), (-30, -10), (0, 0), (360, 255), (180, 128)]:
        r, g, b = plugin_mod._hs_to_rgb(hue, sat)
        assert all(isinstance(c, int) and 0 <= c <= 100 for c in (r, g, b)), (hue, sat, (r, g, b))


def test_effective_port_coerces_string_secret(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "MQTT_PORT", "1884")   # IndigoSecrets as a string
    assert plugin._effective_port() == 1884
    assert isinstance(plugin._effective_port(), int)


def test_effective_port_invalid_secret_falls_back(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "log", lambda *a, **k: None)
    monkeypatch.setattr(plugin_mod, "MQTT_PORT", "not-a-port")
    assert plugin._effective_port() == 1883


# ── wake_up resets the liveness clock ────────────────────────────────────────

def test_wake_up_resets_last_rx_ts(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_start_mqtt", lambda: None)
    plugin.last_rx_ts = time.time() - 100_000      # pretend it's hours stale
    plugin.wake_up()
    assert time.time() - plugin.last_rx_ts < 5, "wake_up must give a fresh silence window"


# ── _rebuild_mqtt is atomic: stop THEN start, under one lock, clock reset ─────

def test_rebuild_mqtt_orders_stop_then_start_and_resets_clock(plugin, monkeypatch):
    order = []
    monkeypatch.setattr(plugin, "_stop_mqtt_locked", lambda: order.append("stop"))
    monkeypatch.setattr(plugin, "_start_mqtt_locked", lambda: order.append("start"))
    plugin.last_rx_ts = time.time() - 100_000
    plugin._rebuild_mqtt()
    assert order == ["stop", "start"]
    assert time.time() - plugin.last_rx_ts < 5


# ── MQTT liveness watchdog (was entirely untested) ───────────────────────────

def test_liveness_rebuilds_when_silent_too_long(plugin, plugin_mod, monkeypatch):
    monkeypatch.setattr(plugin_mod, "log", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: calls.append(1))
    plugin.mqtt_client    = object()          # a live-looking client
    plugin._last_mqtt_check = 0.0             # throttle window already elapsed
    plugin.last_rx_ts     = time.time() - (plugin_mod.MQTT_SILENCE_LIMIT + 5)
    plugin._mqtt_liveness_check()
    assert calls == [1], "a too-long silence must trigger exactly one rebuild"


def test_liveness_no_rebuild_when_recent_traffic(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: calls.append(1))
    plugin.mqtt_client    = object()
    plugin._last_mqtt_check = 0.0
    plugin.last_rx_ts     = time.time()       # fresh traffic
    plugin._mqtt_liveness_check()
    assert calls == []


def test_liveness_throttled_between_checks(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: calls.append(1))
    plugin.mqtt_client    = object()
    plugin._last_mqtt_check = time.time()      # just checked — throttle holds
    plugin.last_rx_ts     = 0.0                # ancient, but throttle wins
    plugin._mqtt_liveness_check()
    assert calls == []


def test_liveness_noop_when_client_none(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: calls.append(1))
    plugin.mqtt_client    = None               # stopped / never started
    plugin._last_mqtt_check = 0.0
    plugin.last_rx_ts     = 0.0
    plugin._mqtt_liveness_check()
    assert calls == []


# ── _on_mqtt_message: paho ingress (binary skip, JSON, bare string, stamp) ───

class _FakeMsg:
    def __init__(self, topic, payload_bytes):
        self.topic   = topic
        self.payload = payload_bytes


def test_on_message_valid_json_enqueued_and_stamped(plugin):
    plugin.msg_queue = queue.Queue()
    plugin.last_rx_ts = 0.0
    plugin._on_mqtt_message(None, None, _FakeMsg("zigbee2mqtt/Lamp", b'{"state":"ON"}'))
    topic, payload = plugin.msg_queue.get_nowait()
    assert topic == "zigbee2mqtt/Lamp"
    assert payload == {"state": "ON"}
    assert time.time() - plugin.last_rx_ts < 5, "every inbound message stamps last_rx_ts"


def test_on_message_bare_string_fallback(plugin):
    plugin.msg_queue = queue.Queue()
    plugin._on_mqtt_message(None, None, _FakeMsg("zigbee2mqtt/bridge/state", b"online"))
    topic, payload = plugin.msg_queue.get_nowait()
    assert topic == "zigbee2mqtt/bridge/state"
    assert payload == "online"               # raw string passed through, not JSON


def test_on_message_binary_skipped_but_still_stamps(plugin):
    plugin.msg_queue = queue.Queue()
    plugin.last_rx_ts = 0.0
    plugin._on_mqtt_message(None, None, _FakeMsg("zigbee2mqtt/Lamp", b"\xff\xfe\x00"))
    assert plugin.msg_queue.empty(), "non-utf-8 payload must be skipped, not queued"
    assert time.time() - plugin.last_rx_ts < 5, "liveness stamps even on a skipped binary frame"


# ── _on_mqtt_connect failure + _on_mqtt_disconnect routes ────────────────────

def test_on_connect_failure_queues_error(plugin):
    plugin.msg_queue = queue.Queue()
    from conftest import RC_BAD_AUTH
    plugin._on_mqtt_connect(object(), None, None, RC_BAD_AUTH, None)  # paho 2.x
    topic, payload = plugin.msg_queue.get_nowait()
    assert topic == "__error__"
    assert "Bad user name or password" in payload["msg"]  # str(ReasonCode) since v2.0.0
    assert plugin.mqtt_connected is False


def test_on_disconnect_clears_connected_and_queues(plugin):
    plugin.msg_queue = queue.Queue()
    plugin.mqtt_connected = True
    from conftest import RC_DROPPED
    plugin._on_mqtt_disconnect(object(), None, None, RC_DROPPED, None)  # paho 2.x
    assert plugin.mqtt_connected is False
    topic, payload = plugin.msg_queue.get_nowait()
    assert topic == "__disconnected__"
    assert payload["rc"] == 1


def test_disconnect_route_warns_on_unexpected_clean_on_zero(plugin, plugin_mod, monkeypatch):
    logs = []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": logs.append((level, msg)))
    plugin._process_message("__disconnected__", {"rc": 1})
    plugin._process_message("__disconnected__", {"rc": 0})
    assert any(lvl == "WARNING" for lvl, _ in logs)      # rc=1 unexpected
    assert any(lvl == "INFO" and "cleanly" in m for lvl, m in logs)  # rc=0 clean


# ── Catch-all z2mSensor: partial payload must not drop a present person ───────

def test_catchall_sensor_partial_payload_preserves_motion(plugin, make_device):
    dev = make_device(720, "Combo Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Combo Sensor"})
    plugin._process_sensor_state(dev, {"presence": True})
    assert dev.states["motion"] is True
    # A partial payload that only carries occupancy=False must NOT clear motion —
    # presence is still True in the per-device store.
    plugin._process_sensor_state(dev, {"occupancy": False})
    assert dev.states["motion"] is True, "partial payload dropped a still-present person"
    # Once the still-active key also clears, motion finally clears.
    plugin._process_sensor_state(dev, {"presence": False})
    assert dev.states["motion"] is False


# ── lastAction "other" fallback + known multi-function action ─────────────────

def test_button_exotic_action_maps_to_other(plugin, make_device):
    dev = make_device(721, "Scene Remote", "z2mButton", states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "recall_1"})
    assert dev.states["lastAction"] == "other"    # declared Option, not a vanished token
    assert dev.states["onOffState"] is True
    assert dev.states["pressCount"] == 1


def test_button_known_multifunction_action_surfaces(plugin, make_device):
    dev = make_device(722, "STYRBAR", "z2mButton", states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "arrow_left_click"})
    assert dev.states["lastAction"] == "arrowLeftClick"
