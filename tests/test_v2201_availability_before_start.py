#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2201_availability_before_start.py
# Description: v2.20.1 — review finding 4. An availability report that arrives
#              BEFORE Indigo has started the device (the retained replay at
#              startup, or a device Discover & Create has not made yet) was
#              dropped, so a sensor already dead at restart stayed green until
#              zigbee2mqtt's verdict next changed — for a dead sensor, never.
#              It is now remembered and applied by deviceStartComm.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import json
import queue

import pytest

NAME = "Utility Leak"


class _Msg:
    def __init__(self, topic, payload, retain=True):
        self.topic   = topic
        self.payload = json.dumps(payload).encode("utf-8")
        self.retain  = retain


@pytest.fixture
def events(plugin, monkeypatch):
    fired = []
    monkeypatch.setattr(plugin, "_fire_event",
                        lambda event_id, *a, **k: fired.append(event_id))
    return fired


@pytest.fixture
def leak(make_device):
    """Exists in Indigo but NOT yet started — not in friendly_name_map."""
    return make_device(9601, NAME, "z2mWaterLeakSensor",
                       pluginProps={"friendly_name": NAME, "ieee_address": "0xul"})


def _start(plugin, dev):
    plugin.deviceStartComm(dev)
    plugin._cancel_state_request(dev.id)


def test_offline_heard_before_start_is_applied_at_start(plugin, leak):
    """The real path: retained message through paho callback and queue first."""
    plugin.msg_queue = queue.Queue()
    plugin._on_mqtt_message(None, None, _Msg(f"zigbee2mqtt/{NAME}/availability",
                                             {"state": "offline"}))
    plugin._drain_queue()
    assert not leak.errorState, "nothing can be written before the device is routed"
    _start(plugin, leak)
    assert leak.errorState == "offline"
    assert leak.states["availability"] == "offline"


def test_the_replay_counts_the_device_offline_without_firing_a_trigger(
        plugin, leak, events):
    plugin._process_availability(NAME, {"state": "offline"})
    _start(plugin, leak)
    assert leak.id in plugin._offline_by_prefix["zigbee2mqtt"]
    assert "offlineCountChanged" not in events


def test_online_heard_before_start_clears_a_stale_error(plugin, leak):
    leak.setErrorStateOnServer("offline")        # left over from before the restart
    plugin._process_availability(NAME, {"state": "online"})
    _start(plugin, leak)
    assert not leak.errorState
    assert leak.states["availability"] == "online"


def test_bare_string_payload_is_remembered_too(plugin, leak):
    plugin._process_availability(NAME, "offline")
    _start(plugin, leak)
    assert leak.errorState == "offline"


def test_nothing_heard_writes_nothing(plugin, leak):
    _start(plugin, leak)
    assert not leak.errorState
    assert not [w for w in leak.state_writes
                if w[0] == "availability" and w[1] in ("online", "offline")]


def test_the_newest_report_wins(plugin, leak):
    plugin._process_availability(NAME, {"state": "offline"})
    plugin._process_availability(NAME, {"state": "online"})
    _start(plugin, leak)
    assert not leak.errorState


def test_another_bridges_report_is_not_applied(plugin, leak):
    """Prefix-qualified, like the routing: the garage's same-named device."""
    plugin._process_availability(NAME, {"state": "offline"}, prefix="garage")
    _start(plugin, leak)
    assert not leak.errorState


def test_a_live_report_after_start_still_fires_the_trigger(plugin, leak, events):
    _start(plugin, leak)
    plugin._process_availability(NAME, {"state": "offline"})
    assert "offlineCountChanged" in events


def test_a_restarted_device_gets_its_verdict_back(plugin, leak):
    """deviceStopComm then deviceStartComm (an edit, or a disable/enable)."""
    _start(plugin, leak)
    plugin._process_availability(NAME, {"state": "offline"})
    plugin.deviceStopComm(leak)
    leak.setErrorStateOnServer(None)
    _start(plugin, leak)
    assert leak.errorState == "offline"


def test_a_group_started_late_gets_its_verdict(plugin, make_device, monkeypatch):
    monkeypatch.setattr(plugin, "_seed_group_state", lambda *a, **k: None)
    group = make_device(9602, "Hall Lamps", "z2mGroupLight",
                        pluginProps={"friendly_name": "Hall Lamps",
                                     "mqtt_prefix": "zigbee2mqtt", "group_id": "7"})
    plugin._process_availability("Hall Lamps", {"state": "offline"})
    plugin.deviceStartComm(group)
    assert group.errorState == "offline"
