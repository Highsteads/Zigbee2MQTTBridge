#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2180_link_health.py
# Description: v2.18.0 — z2m_link_health.py.
#              * A broker connection lost, or a bridge reporting itself offline,
#                for longer than LINK_DOWN_GRACE marks that bridge's devices
#                "bridge down"; the link returning lifts only those marks.
#              * The coordinator's mqttConnected state follows the broker link.
#              * A reconnect asks mains devices (not battery ones, not groups)
#                for their current state.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import time

import pytest

import z2m_link_health
from z2m_constants import LINK_DOWN_GRACE

LINK = z2m_link_health.LINK_ERROR


@pytest.fixture
def house(plugin, make_device):
    """Two devices on the house bridge, one on the garage bridge, one coordinator."""
    plugin.pluginPrefs["mqtt_garage_topic_prefix"] = "garage"
    leak  = make_device(9201, "Leak", "z2mWaterLeakSensor",
                        pluginProps={"friendly_name": "Leak"},
                        states={"availability": "online"})
    plug  = make_device(9202, "Plug", "z2mRelay",
                        pluginProps={"friendly_name": "Plug"},
                        states={"availability": "online"})
    shed  = make_device(9203, "Shed", "z2mContactSensor",
                        pluginProps={"friendly_name": "Shed", "mqtt_prefix": "garage"},
                        states={"availability": "online"})
    coord = make_device(9204, "Coordinator", "z2mCoordinator",
                        pluginProps={"mqtt_prefix": "zigbee2mqtt"},
                        states={"status": "online", "mqttConnected": False,
                                "lastUpdate": ""})
    plugin.friendly_name_map[("zigbee2mqtt", "Leak")] = leak.id
    plugin.friendly_name_map[("zigbee2mqtt", "Plug")] = plug.id
    plugin.friendly_name_map[("garage", "Shed")] = shed.id
    plugin.coordinator_map["zigbee2mqtt"] = coord.id
    return {"leak": leak, "plug": plug, "shed": shed, "coord": coord}


def _connected(plugin, up):
    plugin.mqtt_connected = up
    plugin.mqtt_client = object() if up else None


def _check(plugin, at):
    plugin._last_link_check = 0.0     # bypass the throttle
    plugin._check_link_health(now=at)


# ── broker connection lost ──────────────────────────────────────────────────

def test_a_short_blip_marks_nothing(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE - 1)
    assert all(not d.errorState for d in house.values())


def test_a_lost_broker_marks_every_device_after_the_grace(plugin, house, logs):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    for key in ("leak", "plug", "shed"):
        assert house[key].errorState == LINK
    assert len(logs.at("WARNING")) == 2, "one warning per bridge, not per device"
    _check(plugin, t0 + LINK_DOWN_GRACE + 60)
    assert len(logs.at("WARNING")) == 2, "and not repeated on later checks"


def test_the_coordinator_is_never_given_an_error(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    assert not house["coord"].errorState


def test_an_offline_device_keeps_its_more_specific_error(plugin, house):
    house["leak"].setErrorStateOnServer("offline")
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    assert house["leak"].errorState == "offline"


def test_reconnecting_lifts_the_marks(plugin, house, logs):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    _connected(plugin, True)
    _check(plugin, t0 + LINK_DOWN_GRACE + 10)
    assert all(not d.errorState for d in house.values())
    assert logs.event_has("reachable again")


def test_a_device_last_known_offline_returns_to_offline_not_healthy(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    house["plug"].states["availability"] = "offline"
    _connected(plugin, True)
    _check(plugin, t0 + LINK_DOWN_GRACE + 10)
    assert house["plug"].errorState == "offline"


def test_availability_arriving_first_wins_over_the_restore(plugin, house):
    """The retained availability replay can land before the next check."""
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    plugin._process_availability("Leak", {"state": "offline"})
    assert house["leak"].errorState == "offline"
    _connected(plugin, True)
    _check(plugin, t0 + LINK_DOWN_GRACE + 10)
    assert house["leak"].errorState == "offline"


def test_an_error_set_by_someone_else_is_not_cleared(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    house["plug"].setErrorStateOnServer("something else")
    _connected(plugin, True)
    _check(plugin, t0 + LINK_DOWN_GRACE + 10)
    assert house["plug"].errorState == "something else"


def test_sleep_is_not_counted_as_an_outage(plugin, house):
    """prepare_to_sleep stops MQTT; hours later wake_up restarts the clocks,
    so the second before the reconnect lands does not turn the house red."""
    t_sleep = time.time() - 6 * 3600
    _connected(plugin, False)
    _check(plugin, t_sleep)
    plugin._restart_link_clocks()
    _check(plugin, time.time() + 1)
    assert all(not d.errorState for d in house.values())


# ── zigbee2mqtt itself offline (broker still up) ────────────────────────────

def test_one_bridge_offline_marks_only_its_own_devices(plugin, house):
    _connected(plugin, True)
    plugin._process_bridge_state({"state": "offline"}, "garage")
    _check(plugin, time.time() + LINK_DOWN_GRACE + 1)
    assert house["shed"].errorState == LINK
    assert not house["leak"].errorState
    assert not house["plug"].errorState


def test_bridge_back_online_lifts_its_marks(plugin, house):
    _connected(plugin, True)
    plugin._process_bridge_state({"state": "offline"}, "garage")
    _check(plugin, time.time() + LINK_DOWN_GRACE + 1)
    plugin._process_bridge_state({"state": "online"}, "garage")
    _check(plugin, time.time() + LINK_DOWN_GRACE + 2)
    assert not house["shed"].errorState


# ── the preference ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("off", [False, "false"])
def test_the_preference_turns_marking_off(plugin, house, off):
    plugin.pluginPrefs["markDevicesWhenBridgeDown"] = off
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    assert all(not d.errorState for d in house.values())


def test_turning_the_preference_off_mid_outage_lifts_the_marks(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    plugin.pluginPrefs["markDevicesWhenBridgeDown"] = False
    _check(plugin, t0 + LINK_DOWN_GRACE + 10)
    assert all(not d.errorState for d in house.values())


# ── coordinator mqttConnected ───────────────────────────────────────────────

def test_coordinator_shows_the_broker_link_at_once(plugin, house):
    _connected(plugin, True)
    _check(plugin, 1_000_000.0)
    assert house["coord"].states["mqttConnected"] is True
    _connected(plugin, False)
    _check(plugin, 1_000_001.0)        # well inside the grace
    assert house["coord"].states["mqttConnected"] is False


def test_coordinator_is_written_only_on_a_change(plugin, house):
    _connected(plugin, True)
    _check(plugin, 1_000_000.0)
    writes = len(house["coord"].state_writes)
    _check(plugin, 1_000_010.0)
    assert len(house["coord"].state_writes) == writes


def test_the_coordinator_state_is_registered_on_existing_devices(plugin):
    assert "mqttConnected" in plugin._V218_COORDINATOR_STATES


# ── finding 1: state refresh after a reconnect ──────────────────────────────

def test_refresh_skips_battery_devices_and_groups(plugin, make_device, monkeypatch):
    devs = [
        (9301, "Bulb",   "z2mLight",           {}),                              # no power_source: light => ask
        (9302, "Plug",   "z2mRelay",           {"power_source": "Mains (single phase)"}),
        (9303, "Leak",   "z2mWaterLeakSensor", {"power_source": "Battery"}),
        (9304, "Motion", "z2mOccupancySensor", {}),                              # unknown sensor => skip
        (9305, "Group",  "z2mGroupLight",      {}),
        (9306, "Radar",  "z2mOccupancySensor", {"power_source": "Mains (single phase)"}),
    ]
    for dev_id, name, type_id, props in devs:
        make_device(dev_id, name, type_id, pluginProps={"friendly_name": name, **props})
        plugin.friendly_name_map[("zigbee2mqtt", name)] = dev_id
    asked = []
    monkeypatch.setattr(plugin, "_schedule_state_request",
                        lambda dev_id, fname, *a, **k: asked.append(fname))
    assert plugin._refresh_after_connect(["zigbee2mqtt"]) == 3
    assert sorted(asked) == ["Bulb", "Plug", "Radar"]


def test_refresh_only_covers_the_prefixes_that_connected(plugin, make_device,
                                                         monkeypatch):
    make_device(9311, "Garage Plug", "z2mRelay",
                pluginProps={"friendly_name": "Garage Plug", "mqtt_prefix": "garage"})
    plugin.friendly_name_map[("garage", "Garage Plug")] = 9311
    asked = []
    monkeypatch.setattr(plugin, "_schedule_state_request",
                        lambda dev_id, fname, *a, **k: asked.append(fname))
    plugin._refresh_after_connect(["zigbee2mqtt"])
    assert asked == []


def test_a_stopped_device_is_forgotten(plugin, house):
    t0 = 1_000_000.0
    _connected(plugin, False)
    _check(plugin, t0)
    _check(plugin, t0 + LINK_DOWN_GRACE)
    plugin.deviceStopComm(house["plug"])
    assert house["plug"].id not in plugin._link_marked
