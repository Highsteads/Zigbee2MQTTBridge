#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2202_leftover_bridge_down.py
# Description: v2.20.2 — a "bridge down" error left by a PREVIOUS run is lifted
#              when the device starts. Before, _link_marked (in memory) did not
#              know it, so nothing ever cleared it when zigbee2mqtt's
#              availability was off — and Water Leak Monitor, which ignores a
#              sensor in error, stopped watching for leaks for good.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import pytest

import z2m_link_health
from z2m_constants import LINK_DOWN_GRACE

LINK = z2m_link_health.LINK_ERROR
NAME = "Utility Leak"


@pytest.fixture
def leak(make_device):
    return make_device(9701, NAME, "z2mWaterLeakSensor",
                       pluginProps={"friendly_name": NAME, "ieee_address": "0xlb"})


def _start(plugin, dev):
    plugin.deviceStartComm(dev)
    plugin._cancel_state_request(dev.id)


def test_a_mark_from_the_previous_run_is_lifted_at_start(plugin, leak, logs):
    """The bug: restart mid-outage, availability off, bridge now fine."""
    leak.setErrorStateOnServer(LINK)
    _start(plugin, leak)
    assert not leak.errorState
    assert logs.activity_has("left over")
    assert not logs.at("WARNING"), "routine housekeeping, not news"


def test_offline_from_zigbee2mqtt_takes_over(plugin, leak):
    """Cleared first, then the cached availability replay puts 'offline' back."""
    leak.setErrorStateOnServer(LINK)
    plugin._process_availability(NAME, {"state": "offline"})
    _start(plugin, leak)
    assert leak.errorState == "offline"


def test_a_mark_set_this_session_is_left_to_the_link_check(plugin, leak):
    """A device restarted mid-outage keeps its mark; the link check lifts it."""
    plugin.friendly_name_map[("zigbee2mqtt", NAME)] = leak.id
    plugin.mqtt_connected = False
    plugin.mqtt_client = None
    t0 = 1_000_000.0
    plugin._last_link_check = 0.0
    plugin._check_link_health(now=t0)
    plugin._last_link_check = 0.0
    plugin._check_link_health(now=t0 + LINK_DOWN_GRACE)
    assert leak.errorState == LINK
    _start(plugin, leak)
    assert leak.errorState == LINK


@pytest.mark.parametrize("other", ["offline", "something else"])
def test_other_errors_are_not_touched(plugin, leak, other):
    leak.setErrorStateOnServer(other)
    _start(plugin, leak)
    assert leak.errorState == other


def test_still_down_is_marked_again_after_the_grace(plugin, leak):
    """Lifting a leftover never hides a real, continuing outage for long."""
    leak.setErrorStateOnServer(LINK)
    _start(plugin, leak)
    assert not leak.errorState
    plugin.mqtt_connected = False
    plugin.mqtt_client = None
    t0 = 1_000_000.0
    plugin._last_link_check = 0.0
    plugin._check_link_health(now=t0)
    plugin._last_link_check = 0.0
    plugin._check_link_health(now=t0 + LINK_DOWN_GRACE)
    assert leak.errorState == LINK


def test_a_group_with_a_leftover_mark_is_lifted_too(plugin, make_device, monkeypatch):
    monkeypatch.setattr(plugin, "_seed_group_state", lambda *a, **k: None)
    group = make_device(9702, "Hall Lamps", "z2mGroupLight",
                        pluginProps={"friendly_name": "Hall Lamps",
                                     "mqtt_prefix": "zigbee2mqtt", "group_id": "7"})
    group.setErrorStateOnServer(LINK)
    plugin.deviceStartComm(group)
    assert not group.errorState
