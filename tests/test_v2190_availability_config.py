#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2190_availability_config.py
# Description: v2.19.0 — z2m_availability_config.py: warn when zigbee2mqtt's
#              availability tracking is off, since without it a dead device
#              (a leak sensor with a flat battery) never shows an error.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import time

import pytest

import z2m_availability_config as ac
from z2m_constants import AVAILABILITY_WAIT


# ── reading the settings out of bridge/info ─────────────────────────────────

@pytest.mark.parametrize("config,expected", [
    ({"availability": {"enabled": True, "passive": {"timeout": 1500}}}, (True, 1500)),
    ({"availability": {"enabled": False}}, (False, None)),
    ({"availability": {"enabled": "false"}}, (False, None)),     # string token
    ({"availability": True}, (True, None)),                       # zigbee2mqtt 1.x
    ({"availability": False}, (False, None)),
    ({"availability": {"passive": {"timeout": 60}}}, (True, 60)),  # 1.x object = on
    ({"availability": {"enabled": True, "passive": {"timeout": "junk"}}}, (True, None)),
    ({"availability": {"enabled": True, "passive": {"timeout": 0}}}, (True, None)),
    ({"availability": None}, (None, None)),
    ({"availability": "yes please"}, (None, None)),
    ({"availability": {"enabled": "maybe"}}, (None, None)),
    ({}, (None, None)),
])
def test_read_availability_config(config, expected):
    assert ac.read_availability_config({"config": config}) == expected


@pytest.mark.parametrize("info", [None, "online", [], {}, {"config": "x"}])
def test_read_availability_config_never_guesses(info):
    assert ac.read_availability_config(info) == (None, None)


@pytest.mark.parametrize("minutes,text", [(1500, "25 h"), (90, "1.5 h"),
                                          (45, "45 min"), (None, "")])
def test_format_minutes(minutes, text):
    assert ac.format_minutes(minutes) == text


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def coord(plugin, make_device):
    dev = make_device(9401, "Coordinator", "z2mCoordinator",
                      pluginProps={"mqtt_prefix": "zigbee2mqtt"},
                      states={"status": "", "lastUpdate": "",
                              "availabilityTracking": "", "batteryOfflineAfter": ""})
    plugin.coordinator_map["zigbee2mqtt"] = dev.id
    return dev


@pytest.fixture
def routed(plugin, make_device):
    make_device(9402, "Leak", "z2mWaterLeakSensor",
                pluginProps={"friendly_name": "Leak"})
    plugin.friendly_name_map[("zigbee2mqtt", "Leak")] = 9402


def _info(availability):
    return {"version": "2.6.0", "config": {"availability": availability}}


# ── settings say off / on ───────────────────────────────────────────────────

def test_settings_off_warns_once_and_shows_on_the_coordinator(plugin, coord, logs):
    plugin._process_bridge_info(_info({"enabled": False}), "zigbee2mqtt")
    plugin._process_bridge_info(_info({"enabled": False}), "zigbee2mqtt")  # retained republish
    warnings = [m for m in logs.at("WARNING") if "availability turned off" in m]
    assert len(warnings) == 1
    assert "configuration.yaml" in warnings[0]
    assert coord.states["availabilityTracking"] == "disabled"


def test_settings_on_shows_the_battery_timeout_without_a_warning(plugin, coord, logs):
    plugin._process_bridge_info(
        _info({"enabled": True, "passive": {"timeout": 1500}}), "zigbee2mqtt")
    assert not logs.at("WARNING")
    assert coord.states["availabilityTracking"] == "enabled"
    assert coord.states["batteryOfflineAfter"] == "25 h"
    assert logs.activity_has("after 25 h")


def test_off_globally_but_reports_arriving_reads_some_devices(plugin, coord):
    """zigbee2mqtt allows availability per device even when off globally."""
    plugin._process_bridge_info(_info({"enabled": False}), "zigbee2mqtt")
    plugin._process_message("zigbee2mqtt/Leak/availability", {"state": "online"})
    assert coord.states["availabilityTracking"] == "some devices"


# ── settings silent: judge by the evidence ──────────────────────────────────

def _connect(plugin, at):
    plugin.mqtt_connected = True
    plugin._bridge_state_cache["zigbee2mqtt"] = "online"
    plugin._start_availability_wait(["zigbee2mqtt"])
    plugin._avail_wait_from["zigbee2mqtt"] = at


def test_no_reports_after_the_wait_warns(plugin, coord, routed, logs):
    t0 = 1_000_000.0
    _connect(plugin, t0)
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT - 1)
    assert not logs.at("WARNING")
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT)
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT + 60)
    warnings = [m for m in logs.at("WARNING") if "probably turned off" in m]
    assert len(warnings) == 1
    assert coord.states["availabilityTracking"] == "probably off"


def test_any_report_means_it_is_on(plugin, coord, routed, logs):
    t0 = 1_000_000.0
    _connect(plugin, t0)
    plugin._process_message("zigbee2mqtt/Someone Else/availability",
                            {"state": "online"})
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT + 1)
    assert not logs.at("WARNING")
    assert coord.states["availabilityTracking"] == "enabled"


@pytest.mark.parametrize("why", ["broker down", "bridge offline", "no devices"])
def test_no_warning_when_nothing_could_have_arrived(plugin, make_device, logs, why):
    t0 = 1_000_000.0
    _connect(plugin, t0)
    if why == "broker down":
        plugin.mqtt_connected = False
    if why == "bridge offline":
        plugin._bridge_state_cache["zigbee2mqtt"] = "offline"
    if why != "no devices":
        make_device(9403, "Leak", "z2mWaterLeakSensor",
                    pluginProps={"friendly_name": "Leak"})
        plugin.friendly_name_map[("zigbee2mqtt", "Leak")] = 9403
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT + 1)
    assert not logs.at("WARNING")


def test_a_late_report_withdraws_the_warning(plugin, coord, routed, logs):
    t0 = 1_000_000.0
    _connect(plugin, t0)
    plugin._check_availability_reports(now=t0 + AVAILABILITY_WAIT)
    plugin._process_message("zigbee2mqtt/Leak/availability", {"state": "online"})
    assert logs.event_has("after all")
    assert coord.states["availabilityTracking"] == "enabled"


def test_the_connect_handler_starts_the_wait(plugin):
    plugin._process_message("__connected__", {"subscribed": ["zigbee2mqtt/#"]})
    assert abs(plugin._avail_wait_from["zigbee2mqtt"] - time.time()) < 5


# ── Test MQTT Connection ────────────────────────────────────────────────────

def test_connection_test_lists_availability_off(plugin):
    plugin._process_bridge_info(_info({"enabled": False}), "zigbee2mqtt")
    assert "disabled" in plugin._availability_problem("zigbee2mqtt")


def test_connection_test_is_quiet_when_it_is_on(plugin):
    plugin._process_bridge_info(_info({"enabled": True}), "zigbee2mqtt")
    assert plugin._availability_problem("zigbee2mqtt") == ""


def test_the_coordinator_states_are_registered_on_existing_devices(plugin):
    assert set(plugin._V219_COORDINATOR_STATES) == {"availabilityTracking",
                                                    "batteryOfflineAfter"}
