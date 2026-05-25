#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_device_type_detection.py
# Description: Tests for _detect_device_type — the heart of the Discover & Create
#              Devices menu item. Bad detection means devices get wrong types and
#              users have to delete + recreate, so this gets thorough coverage.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026


def test_detect_light_ct(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.LIGHT_CT) == "z2mLight"


def test_detect_light_rgb_ct(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.LIGHT_RGB_CT) == "z2mLight"


def test_detect_light_via_nested_brightness(plugin_mod):
    """A bare numeric brightness leaf (no type='light' composite) should still
    classify as z2mLight — Hue White Ambiance bulbs and some no-name Tuya
    lights emit this shape."""
    exposes = [
        {"name": "state",      "type": "binary",  "access": 7},
        {"name": "brightness", "type": "numeric", "access": 7},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mLight"


def test_detect_relay_simple(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.RELAY) == "z2mRelay"


def test_detect_relay_with_metering(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.RELAY_WITH_POWER) == "z2mRelay"


def test_detect_relay_writable_state_only(plugin_mod):
    """Plugs exposing only a writable state leaf (no switch composite)."""
    exposes = [
        {"name": "state", "type": "binary", "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "linkquality", "type": "numeric", "access": 1},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mRelay"


def test_detect_contact_sensor(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.CONTACT) == "z2mContactSensor"


def test_detect_occupancy_sensor(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.OCCUPANCY) == "z2mOccupancySensor"


def test_detect_presence_mmwave_is_occupancy_class(plugin_mod, fixtures):
    """mmWave presence sensors expose 'presence' instead of 'occupancy'.
    Both classify as the same Indigo device type."""
    assert plugin_mod._detect_device_type(fixtures.PRESENCE_MMWAVE) == "z2mOccupancySensor"


def test_detect_water_leak_sensor(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.WATER_LEAK) == "z2mWaterLeakSensor"


def test_detect_environmental_sensor(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.TEMP_HUMIDITY) == "z2mTemperatureSensor"


def test_detect_cover_composite(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.COVER) == "z2mCover"


def test_detect_cover_position_only(plugin_mod):
    """Some blinds expose only a numeric position feature — no cover composite."""
    exposes = [
        {"name": "position",    "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 100},
        {"name": "linkquality", "type": "numeric", "access": 1},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mCover"


def test_detect_button(plugin_mod, fixtures):
    assert plugin_mod._detect_device_type(fixtures.BUTTON) == "z2mButton"


def test_detect_repeater_by_lq_only_exposes(plugin_mod, fixtures):
    """A device whose exposes contains only link_quality is a repeater/router."""
    assert plugin_mod._detect_device_type(fixtures.REPEATER_LQ_ONLY) == "z2mRepeater"


def test_detect_repeater_empty_exposes(plugin_mod, fixtures):
    """Some coordinators/routers expose nothing at all."""
    assert plugin_mod._detect_device_type(fixtures.REPEATER_EMPTY) == "z2mSensor"
    # Empty exposes maps to z2mSensor (the catch-all) — repeater detection
    # requires either a model hint or at least the linkquality leaf.


def test_detect_repeater_via_model_name(plugin_mod):
    """Model contains 'repeater' → z2mRepeater regardless of exposes."""
    assert plugin_mod._detect_device_type(
        [{"name": "state", "type": "binary", "access": 7}],
        model="TS0207_Repeater"
    ) == "z2mRepeater"


def test_detect_repeater_smlight_models(plugin_mod):
    for m in ("SLZB-06P7", "SLZB-06", "SLZB-07"):
        assert plugin_mod._detect_device_type(
            [{"name": "state", "type": "binary", "access": 7}],
            model=m,
        ) == "z2mRepeater"


def test_detect_mixed_sensor_falls_back_to_generic(plugin_mod, fixtures):
    """Devices with contact + occupancy together don't fit the specific
    sensor sub-types — they should fall back to the generic z2mSensor."""
    assert plugin_mod._detect_device_type(fixtures.MIXED_SENSOR) == "z2mSensor"


def test_detect_priority_repeater_over_relay(plugin_mod):
    """If model says repeater, that wins even if exposes has writable state."""
    exposes = [
        {"name": "state", "type": "binary", "access": 7,
         "value_on": "ON", "value_off": "OFF"},
    ]
    assert plugin_mod._detect_device_type(exposes, model="TuYa Repeater") == "z2mRepeater"


def test_detect_priority_light_over_relay(plugin_mod):
    """Brightness leaf wins over writable state — bulb has both."""
    exposes = [
        {"name": "state",      "type": "binary",  "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "brightness", "type": "numeric", "access": 7},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mLight"


def test_detect_priority_cover_over_relay(plugin_mod):
    """Position leaf wins over writable state — blind has both."""
    exposes = [
        {"name": "state",    "type": "binary",  "access": 7},
        {"name": "position", "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 100},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mCover"


def test_detect_button_wins_over_relay(plugin_mod):
    """Some TuYa buttons mis-expose a writable state leaf alongside the
    action enum. The action enum should win."""
    exposes = [
        {"name": "state",  "type": "binary", "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "action", "type": "enum",   "access": 1,
         "values": ["single", "double", "long"]},
    ]
    assert plugin_mod._detect_device_type(exposes) == "z2mButton"


def test_detect_none_exposes_is_sensor(plugin_mod):
    """Robust against ``exposes=None`` — empty/None falls through to z2mSensor."""
    assert plugin_mod._detect_device_type(None) == "z2mSensor"
