#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_capabilities.py
# Description: Tests for the per-type _detect_*_capabilities helpers and the
#              _build_capabilities_display string formatter.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026


# ── _detect_light_capabilities ───────────────────────────────────────────────

def test_light_caps_ct_only(plugin_mod, fixtures):
    caps = plugin_mod._detect_light_capabilities(fixtures.LIGHT_CT)
    assert caps["has_brightness"] is True
    assert caps["has_color_temp"] is True
    assert caps["has_color"]      is False


def test_light_caps_rgb_ct(plugin_mod, fixtures):
    caps = plugin_mod._detect_light_capabilities(fixtures.LIGHT_RGB_CT)
    assert caps["has_brightness"] is True
    assert caps["has_color_temp"] is True
    assert caps["has_color"]      is True


def test_light_caps_recognises_color_hs_and_color(plugin_mod):
    """The detector accepts any of color_xy / color_hs / color as colour evidence."""
    for cname in ("color_xy", "color_hs", "color"):
        exposes = [{"type": "light", "features": [
            {"name": "state",       "type": "binary"},
            {"name": "brightness",  "type": "numeric"},
            {"name": cname,         "type": "composite"},
        ]}]
        caps = plugin_mod._detect_light_capabilities(exposes)
        assert caps["has_color"] is True, f"failed for {cname}"


# ── _detect_contact_sensor_capabilities ──────────────────────────────────────

def test_contact_caps_with_battery(plugin_mod, fixtures):
    caps = plugin_mod._detect_contact_sensor_capabilities(fixtures.CONTACT)
    assert caps["has_battery"] is True


def test_contact_caps_without_battery(plugin_mod):
    exposes = [{"name": "contact", "type": "binary"}]
    caps = plugin_mod._detect_contact_sensor_capabilities(exposes)
    assert caps["has_battery"] is False


# ── _detect_occupancy_sensor_capabilities ────────────────────────────────────

def test_occupancy_caps_full(plugin_mod, fixtures):
    caps = plugin_mod._detect_occupancy_sensor_capabilities(fixtures.OCCUPANCY)
    assert caps["has_pir"]         is True
    assert caps["has_illuminance"] is True
    assert caps["has_battery"]     is True
    assert caps["has_presence"]    is False  # this fixture uses 'occupancy' not 'presence'


def test_occupancy_caps_presence_only_mmwave(plugin_mod, fixtures):
    caps = plugin_mod._detect_occupancy_sensor_capabilities(fixtures.PRESENCE_MMWAVE)
    assert caps["has_pir"]      is False
    assert caps["has_presence"] is True


# ── _detect_water_leak_sensor_capabilities ───────────────────────────────────

def test_water_leak_caps(plugin_mod, fixtures):
    caps = plugin_mod._detect_water_leak_sensor_capabilities(fixtures.WATER_LEAK)
    assert caps["has_battery"]     is True
    assert caps["has_temperature"] is False


# ── _detect_temperature_sensor_capabilities ──────────────────────────────────

def test_temp_caps(plugin_mod, fixtures):
    caps = plugin_mod._detect_temperature_sensor_capabilities(fixtures.TEMP_HUMIDITY)
    assert caps["has_temperature"] is True
    assert caps["has_humidity"]    is True
    assert caps["has_pressure"]    is True
    assert caps["has_battery"]     is True
    assert caps["has_illuminance"] is False


# ── _detect_sensor_capabilities (catch-all) ──────────────────────────────────

def test_sensor_caps_mixed(plugin_mod, fixtures):
    caps = plugin_mod._detect_sensor_capabilities(fixtures.MIXED_SENSOR)
    assert caps["has_contact"]   is True
    assert caps["has_occupancy"] is True


def test_sensor_caps_motion_alias(plugin_mod):
    """The catch-all detector treats 'motion' as occupancy evidence too."""
    exposes = [{"name": "motion", "type": "binary"}]
    caps = plugin_mod._detect_sensor_capabilities(exposes)
    assert caps["has_occupancy"] is True


# ── _detect_relay_capabilities ───────────────────────────────────────────────

def test_relay_caps_basic(plugin_mod, fixtures):
    caps = plugin_mod._detect_relay_capabilities(fixtures.RELAY)
    assert caps["has_power"]  is False
    assert caps["has_energy"] is False


def test_relay_caps_with_metering(plugin_mod, fixtures):
    caps = plugin_mod._detect_relay_capabilities(fixtures.RELAY_WITH_POWER)
    assert caps["has_power"]  is True
    assert caps["has_energy"] is True


# ── _build_capabilities_display ──────────────────────────────────────────────

def test_caps_display_light_rgb_ct(plugin_mod):
    s = plugin_mod._build_capabilities_display("z2mLight", {
        "has_brightness": True, "has_color_temp": True, "has_color": True,
    })
    assert "on/off"      in s
    assert "brightness"  in s
    assert "color temp"  in s
    assert "full color"  in s


def test_caps_display_relay_metered(plugin_mod):
    s = plugin_mod._build_capabilities_display("z2mRelay", {
        "has_power": True, "has_energy": True,
    })
    assert "on/off"      in s
    assert "power (W)"   in s
    assert "energy (kWh)" in s


def test_caps_display_contact_no_battery(plugin_mod):
    s = plugin_mod._build_capabilities_display("z2mContactSensor", {
        "has_battery": False,
    })
    assert "contact" in s
    assert "battery" not in s


def test_caps_display_occupancy_full(plugin_mod):
    s = plugin_mod._build_capabilities_display("z2mOccupancySensor", {
        "has_illuminance": True, "has_temperature": True,
        "has_humidity":    True, "has_battery":     True,
    })
    for token in ("occupancy", "illuminance", "temperature", "humidity", "battery"):
        assert token in s, f"missing {token!r} in {s!r}"


def test_caps_display_empty_envsensor_fallback(plugin_mod):
    """A z2mTemperatureSensor with no capability flags returns a sensible
    fallback string rather than an empty value."""
    s = plugin_mod._build_capabilities_display("z2mTemperatureSensor", {})
    assert s   # non-empty
    assert "environmental" in s.lower() or "sensor" in s.lower()


def test_caps_display_unknown_type_falls_back_to_type_id(plugin_mod):
    s = plugin_mod._build_capabilities_display("z2mUnknown", {})
    assert s == "z2mUnknown"


# ── Plugin._compute_light_native_flags ───────────────────────────────────────

def test_native_flags_rgb_ct(plugin_mod):
    flags = plugin_mod.Plugin._compute_light_native_flags(has_color=True, has_color_temp=True)
    assert flags == {
        "SupportsColor": True, "SupportsRGB": True,
        "SupportsWhite": True, "SupportsWhiteTemperature": True,
    }


def test_native_flags_ct_only_sets_supports_color(plugin_mod):
    """CT-only Hue White Ambiance bulbs MUST have SupportsColor=True or Indigo
    silently drops SupportsWhiteTemperature. This is the v1.9.3 regression fix."""
    flags = plugin_mod.Plugin._compute_light_native_flags(has_color=False, has_color_temp=True)
    assert flags["SupportsColor"]            is True
    assert flags["SupportsRGB"]              is False
    assert flags["SupportsWhite"]            is True
    assert flags["SupportsWhiteTemperature"] is True


def test_native_flags_color_only(plugin_mod):
    flags = plugin_mod.Plugin._compute_light_native_flags(has_color=True, has_color_temp=False)
    assert flags["SupportsColor"]            is True
    assert flags["SupportsRGB"]              is True
    assert flags["SupportsWhite"]            is False
    assert flags["SupportsWhiteTemperature"] is False


def test_native_flags_dimmer_only(plugin_mod):
    flags = plugin_mod.Plugin._compute_light_native_flags(has_color=False, has_color_temp=False)
    assert all(v is False for v in flags.values())
