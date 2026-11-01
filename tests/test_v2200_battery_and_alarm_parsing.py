#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2200_battery_and_alarm_parsing.py
# Description: v2.20.0 — review findings 5 and 6.
#              5. A battery sent as text with a decimal ("87.5") was dropped by
#                 int(); every handler now uses the same coercion as the native
#                 batteryLevel mirror (rounded, clamped 0-100, bools rejected).
#              6. An empty water_leak / smoke value read as "all clear" and
#                 could cancel a standing alarm; it is now unknown and skipped.
#                 _payload_bool itself is unchanged ("" is still False for
#                 Configure checkboxes — pinned in test_v1921_fixes.py).
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import pytest

# Every device type whose handler reads `battery` itself (the cover handler
# does not; a cover's battery arrives through the raw-field capture).
BATTERY_TYPES = ["z2mContactSensor", "z2mOccupancySensor", "z2mWaterLeakSensor",
                 "z2mTemperatureSensor", "z2mSensor", "z2mButton", "z2mLock",
                 "z2mThermostat"]


@pytest.fixture
def device(plugin, make_device):
    def _make(type_id, dev_id=9501, **states):
        dev = make_device(dev_id, "Dev", type_id,
                          pluginProps={"friendly_name": "Dev"}, states=dict(states))
        plugin.friendly_name_map[("zigbee2mqtt", "Dev")] = dev_id
        return dev
    return _make


# ── finding 5: battery ──────────────────────────────────────────────────────

@pytest.mark.parametrize("type_id", BATTERY_TYPES)
@pytest.mark.parametrize("raw,expected", [
    (87, 87), (87.4, 87), ("87", 87), ("87.5", 88), ("87.6", 88), (" 42 ", 42),
    (0, 0), (120, 100), (-5, 0),
])
def test_every_handler_reads_battery_the_same_way(plugin, device, type_id,
                                                  raw, expected):
    dev = device(type_id)
    plugin._process_device_state("Dev", {"battery": raw})
    assert dev.states["battery"] == expected


@pytest.mark.parametrize("type_id", BATTERY_TYPES)
@pytest.mark.parametrize("raw", [None, True, False, "", "low", [50], {"v": 1}])
def test_junk_battery_keeps_the_last_reading(plugin, device, type_id, raw):
    dev = device(type_id, battery=55)
    plugin._process_device_state("Dev", {"battery": raw})
    assert dev.states["battery"] == 55


def test_the_custom_and_native_battery_states_agree(plugin, device):
    dev = device("z2mWaterLeakSensor")
    plugin._process_device_state("Dev", {"battery": "87.5"})
    assert dev.states["battery"] == dev.states["batteryLevel"] == 88


def test_payload_battery_raises_for_no_reading(plugin):
    with pytest.raises(ValueError):
        plugin._payload_battery(None)


# ── finding 6: empty alarm values ───────────────────────────────────────────

@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_leak_value_does_not_cancel_a_leak(plugin, device, empty):
    dev = device("z2mWaterLeakSensor", waterLeak=True, onOffState=True)
    plugin._process_device_state("Dev", {"water_leak": empty})
    assert dev.states["waterLeak"] is True
    assert dev.states["onOffState"] is True


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_leak_value_on_the_generic_sensor_changes_nothing(plugin, device,
                                                                   empty):
    dev = device("z2mSensor", waterLeak=True)
    plugin._process_device_state("Dev", {"water_leak": empty})
    assert dev.states["waterLeak"] is True


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_smoke_value_does_not_cancel_an_alarm(plugin, device, empty):
    dev = device("z2mSensor", smoke=True)
    plugin._process_device_state("Dev", {"smoke": empty})
    assert dev.states["smoke"] is True


@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False), ("true", True), ("false", False),
    ("OFF", False), ("1", True), ("0", False), (0, False),
    ("", None), ("  ", None), ("maybe", None), (None, None),
])
def test_alarm_bool(plugin_mod, raw, expected):
    import z2m_helpers
    assert z2m_helpers._alarm_bool(raw) is expected


def test_payload_bool_is_unchanged_for_settings(plugin_mod):
    """Configure checkboxes stored empty still read False."""
    assert plugin_mod._payload_bool("") is False


@pytest.mark.parametrize("token,expected", [("false", False), ("true", True)])
def test_real_tokens_still_work_on_a_leak_sensor(plugin, device, token, expected):
    dev = device("z2mWaterLeakSensor", waterLeak=not expected)
    plugin._process_device_state("Dev", {"water_leak": token})
    assert dev.states["waterLeak"] is expected
