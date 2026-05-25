#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_pure_helpers.py
# Description: Unit tests for pure helper functions in plugin.py — these have
#              no Indigo dependency and can be exercised standalone.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

import pytest


# ── brightness round-trips ───────────────────────────────────────────────────

@pytest.mark.parametrize("val255,expected", [
    (0,   0),
    (1,   0),     # rounds down to 0
    (127, 49),    # ~50% (int(127/255*100) = 49)
    (128, 50),    # int(128/255*100) = 50
    (252, 98),    # below the 99-clamp threshold
    (253, 100),   # int(253/255*100)=99 → >=99 clamp → 100
    (254, 100),   # the >=99 clamp catches 99 too
    (255, 100),
])
def test_brightness_255_to_100(plugin_mod, val255, expected):
    assert plugin_mod._brightness_255_to_100(val255) == expected


@pytest.mark.parametrize("val100,expected", [
    (0,   1),     # plugin clamps min 1 (z2m treats 0 as off via separate state)
    (1,   2),
    (50,  127),
    (99,  252),
    (100, 254),   # plugin clamps max 254
])
def test_brightness_100_to_255(plugin_mod, val100, expected):
    assert plugin_mod._brightness_100_to_255(val100) == expected


def test_brightness_round_trip_full(plugin_mod):
    """Indigo 100% -> z2m 254 -> Indigo 100% (clamped to 99-or-above floor)."""
    indigo_pct = 100
    mqtt_b     = plugin_mod._brightness_100_to_255(indigo_pct)
    back       = plugin_mod._brightness_255_to_100(mqtt_b)
    assert back == 100   # 254 hits the >=99 -> 100 clamp


# ── colour-temperature conversions ──────────────────────────────────────────

@pytest.mark.parametrize("kelvin,mireds", [
    (1000, 1000),   # 1_000_000 / 1000
    (2700, 370),    # warm white — common
    (4000, 250),
    (6500, 154),
    (10000, 100),
])
def test_kelvin_to_mireds(plugin_mod, kelvin, mireds):
    assert plugin_mod._kelvin_to_mireds(kelvin) == mireds


def test_mireds_kelvin_round_trip(plugin_mod):
    # All common bulb values should survive a single round trip (allowing for rounding)
    for k in (2200, 2700, 3000, 4000, 5000, 6500):
        m = plugin_mod._kelvin_to_mireds(k)
        k2 = plugin_mod._mireds_to_kelvin(m)
        # Round-trip error must be within 1% for the band Indigo cares about
        assert abs(k - k2) <= max(15, k * 0.01), f"kelvin {k} -> mireds {m} -> kelvin {k2}"


def test_mireds_kelvin_zero_guard(plugin_mod):
    """Divide-by-zero must not raise."""
    assert plugin_mod._kelvin_to_mireds(0) == 1_000_000
    assert plugin_mod._mireds_to_kelvin(0) == 1_000_000


# ── HS -> RGB ────────────────────────────────────────────────────────────────

def test_hs_to_rgb_red(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(0, 255)
    assert r == 100 and g == 0 and b == 0


def test_hs_to_rgb_green(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(120, 255)
    assert r == 0 and g == 100 and b == 0


def test_hs_to_rgb_blue(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(240, 255)
    assert r == 0 and g == 0 and b == 100


def test_hs_to_rgb_unsaturated_is_white(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(0, 0)
    assert r == g == b == 100


# ── XY -> RGB ────────────────────────────────────────────────────────────────

def test_xy_to_rgb_returns_three_ints(plugin_mod):
    r, g, b = plugin_mod._xy_to_rgb(0.4, 0.4)
    assert all(isinstance(c, int) for c in (r, g, b))
    assert all(0 <= c <= 100 for c in (r, g, b))


def test_xy_to_rgb_handles_zero_y(plugin_mod):
    # Should not raise on division by y=0 (the fallback branch)
    r, g, b = plugin_mod._xy_to_rgb(0.3, 0.0)
    assert all(0 <= c <= 100 for c in (r, g, b))


# ── _flatten_features / _iter_features ───────────────────────────────────────

def test_flatten_features_leaves_only(plugin_mod):
    exposes = [{
        "type": "light",
        "features": [
            {"name": "state",      "type": "binary"},
            {"name": "brightness", "type": "numeric"},
        ],
    }]
    names = [f.get("name") for f in plugin_mod._flatten_features(exposes)]
    assert names == ["state", "brightness"]


def test_iter_features_includes_composites(plugin_mod):
    exposes = [{
        "type": "light",
        "features": [
            {"name": "state",      "type": "binary"},
            {"name": "brightness", "type": "numeric"},
        ],
    }]
    entries = list(plugin_mod._iter_features(exposes))
    # Top-level composite + 2 leaves = 3
    assert len(entries) == 3
    assert entries[0].get("type") == "light"
    assert {e.get("name") for e in entries[1:]} == {"state", "brightness"}


def test_iter_features_deeply_nested(plugin_mod):
    exposes = [{
        "features": [
            {"features": [
                {"name": "deep"},
            ]},
        ],
    }]
    names = {f.get("name") for f in plugin_mod._iter_features(exposes)
             if f.get("name") is not None}
    assert names == {"deep"}


def test_iter_features_empty_input(plugin_mod):
    assert list(plugin_mod._iter_features([])) == []
