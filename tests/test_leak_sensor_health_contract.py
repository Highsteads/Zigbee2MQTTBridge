#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_leak_sensor_health_contract.py
# Description: The contract other plugins (WaterLeakMonitor, DeviceHealthMonitor)
#              rely on, driven END-TO-END: raw MQTT bytes go in through the
#              paho callback (_on_mqtt_message), through the queue, and out
#              through _drain_queue — the same path a real message takes.
#
#              The existing suite tests each handler directly. These tests
#              prove the pieces are wired together, so a routing change
#              cannot quietly stop a dead leak sensor reaching its error state.
#
#              Also: reconnect re-subscribes every prefix and (v2.18.0)
#              re-requests device state.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import json
import queue

import pytest

from conftest import RC_OK

LEAK_ID   = 9101
LEAK_NAME = "Kitchen Leak"


class _Msg:
    """Just enough of a paho MQTTMessage for _on_mqtt_message."""
    def __init__(self, topic, payload, retain=False):
        self.topic   = topic
        self.payload = payload if isinstance(payload, bytes) else (
            payload.encode("utf-8") if isinstance(payload, str)
            else json.dumps(payload).encode("utf-8"))
        self.retain  = retain


class _FakeClient:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return (0, 1)


def _deliver(plugin, topic, payload, retain=False):
    """Push one message down the real paho-thread -> main-thread path."""
    plugin._on_mqtt_message(None, None, _Msg(topic, payload, retain))
    plugin._drain_queue()


@pytest.fixture
def leak(plugin, make_device):
    plugin.msg_queue = queue.Queue()
    dev = make_device(LEAK_ID, LEAK_NAME, "z2mWaterLeakSensor",
                      pluginProps={"friendly_name": LEAK_NAME,
                                   "ieee_address": "0xleak"},
                      states={"availability": "online", "waterLeak": False,
                              "onOffState": False, "battery": 80})
    plugin.friendly_name_map[("zigbee2mqtt", LEAK_NAME)] = LEAK_ID
    return dev


# ── availability -> Indigo error state ──────────────────────────────────────

def test_offline_over_the_wire_puts_the_sensor_in_error(plugin, leak):
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability", {"state": "offline"})
    assert leak.errorState == "offline"
    assert leak.states["availability"] == "offline"


def test_retained_offline_at_startup_still_sets_the_error(plugin, leak):
    """After a restart the broker replays the retained verdict — a sensor
    that died while Indigo was down must still come up red."""
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability",
             {"state": "offline"}, retain=True)
    assert leak.errorState == "offline"


def test_legacy_bare_string_offline_sets_the_error(plugin, leak):
    """Older zigbee2mqtt publishes availability as the bare word."""
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability", "offline")
    assert leak.errorState == "offline"


def test_a_late_report_while_offline_does_not_clear_the_error(plugin, leak):
    """Only zigbee2mqtt saying 'online' ends the fault (v2.10.0)."""
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability", {"state": "offline"})
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", {"battery": 3, "linkquality": 10})
    assert leak.errorState == "offline"


def test_online_over_the_wire_clears_the_error(plugin, leak):
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability", {"state": "offline"})
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}/availability", {"state": "online"})
    assert not leak.errorState


# ── battery / lastSeen state names other plugins read ───────────────────────

def test_flat_battery_reaches_both_battery_states(plugin, leak):
    """A genuinely flat cell (0) from a live report is a real reading and must
    land in the custom `battery` state AND Indigo's native `batteryLevel`."""
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", {"battery": 0})
    assert leak.states["battery"] == 0
    assert leak.states.get("batteryLevel") == 0


def test_last_seen_becomes_the_lastSeen_state(plugin, leak):
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}",
             {"water_leak": False, "last_seen": "2026-11-01T10:00:00Z"})
    assert isinstance(leak.states.get("lastSeen"), str)
    assert leak.states["lastSeen"].startswith("2026-11-01")


# ── payload parsing over the wire ───────────────────────────────────────────

@pytest.mark.parametrize("token", ["false", "OFF", "0", "no"])
def test_string_false_is_dry_not_a_leak(plugin, leak, token):
    leak.states["waterLeak"] = True
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", {"water_leak": token})
    assert leak.states["waterLeak"] is False
    assert leak.states["onOffState"] is False


@pytest.mark.parametrize("token", [True, "true", "ON"])
def test_leak_tokens_raise_the_alarm(plugin, leak, token):
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", {"water_leak": token})
    assert leak.states["waterLeak"] is True
    assert leak.states["onOffState"] is True


def test_unrecognised_leak_value_changes_nothing(plugin, leak):
    """A junk value must neither raise nor clear a standing alarm."""
    leak.states["waterLeak"] = True
    leak.states["onOffState"] = True
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", {"water_leak": "maybe"})
    assert leak.states["waterLeak"] is True
    assert leak.states["onOffState"] is True


@pytest.mark.parametrize("raw", [b"\xff\xfe\x00", b"not json", b"[1, 2, 3]",
                                 b"null", b"42"])
def test_junk_on_a_device_topic_does_not_crash_or_change_state(plugin, leak, raw):
    before = dict(leak.states)
    _deliver(plugin, f"zigbee2mqtt/{LEAK_NAME}", raw)
    assert leak.states == before


# ── reconnect ───────────────────────────────────────────────────────────────

def test_every_reconnect_resubscribes_every_prefix(plugin):
    """paho starts each connection with a clean session, so the subscriptions
    must be re-made on EVERY connect, not just the first — for both bridges."""
    plugin.msg_queue = queue.Queue()
    plugin._subscribed_prefixes = ("zigbee2mqtt", "garage")
    client = _FakeClient()
    plugin._on_mqtt_connect(client, None, None, RC_OK, None)
    plugin.mqtt_connected = False          # simulate the drop
    plugin._on_mqtt_connect(client, None, None, RC_OK, None)
    topics = [t for t, _ in client.subscriptions]
    assert topics.count("zigbee2mqtt/#") == 2
    assert topics.count("garage/#") == 2
    assert plugin.mqtt_connected is True


def test_reconnect_asks_started_devices_for_their_state(plugin, make_device,
                                                        monkeypatch):
    """Review finding 1, fixed in v2.18.0: zigbee2mqtt does not retain device
    state by default, so a reconnect must ask mains devices again."""
    make_device(9102, "Hall Plug", "z2mRelay",
                pluginProps={"friendly_name": "Hall Plug"})
    plugin.friendly_name_map[("zigbee2mqtt", "Hall Plug")] = 9102
    plugin.mqtt_connected = True
    asked = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: asked.append(t) or True)
    monkeypatch.setattr(plugin, "_schedule_state_request",
                        lambda dev_id, fname, *a, **k: asked.append(fname))
    plugin._process_message("__connected__", {"subscribed": ["zigbee2mqtt/#"]})
    assert any("Hall Plug" in a for a in asked)
