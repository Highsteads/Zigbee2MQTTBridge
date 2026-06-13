#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_zoo.py
# Description: Drives the device zoo (zoo_manifest.CASES). Two kinds of check:
#              (1) per-animal contract — each payload yields the right device
#                  TYPE and the right capability props (the full translation);
#              (2) cross-cutting INVARIANTS asserted across every animal at once
#                  — the rules the translator must never break, which no single
#                  per-case test can express. These are where the zoo earns its
#                  keep: they catch a whole class of mis-classification, not one
#                  example of it.
# Author:      CliveS & Claude Opus 4.8
# Date:        13-06-2026

from __future__ import annotations

import pytest

from zoo_manifest import CASES


# The full set of deviceTypeIds the classifier is allowed to emit. A row whose
# expect_type drifts outside this set (a typo, or a type not declared in
# Devices.xml) is a bug in the manifest or the plugin — fail loudly.
# (Future invariant: derive this from Devices.xml so an orphan type is caught.)
KNOWN_TYPES = {
    "z2mLight", "z2mRelay", "z2mContactSensor", "z2mOccupancySensor",
    "z2mWaterLeakSensor", "z2mTemperatureSensor", "z2mSensor", "z2mCover",
    "z2mButton", "z2mRepeater",
}

_IDS = [c.name for c in CASES]


def _build_props(plugin, plugin_mod, case):
    """Run the REAL translation: payload -> type -> full pluginProps dict."""
    type_id = plugin_mod._detect_device_type(case.exposes, model=case.model)
    props = plugin._build_plugin_props(
        type_id,
        {"friendly_name": case.name, "ieee_address": "0x0"},
        {"vendor": "Zoo", "model": case.model},
        case.exposes,
    )
    return type_id, props


def _top_level_feature_names(plugin_mod, exposes):
    if not exposes:
        return set()
    return {f.get("name") for f in plugin_mod._iter_features(exposes)}


# ── (1) Per-animal contract ──────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_zoo_classification(plugin_mod, case):
    """Each payload classifies to its declared device type."""
    got = plugin_mod._detect_device_type(case.exposes, model=case.model)
    assert got == case.expect_type, (
        f"{case.name}: expected {case.expect_type}, got {got} ({case.note})"
    )


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.expect_props], ids=[c.name for c in CASES if c.expect_props]
)
def test_zoo_capabilities(plugin, plugin_mod, case):
    """Each payload yields the expected capability props (subset match)."""
    _type_id, props = _build_props(plugin, plugin_mod, case)
    for key, want in case.expect_props.items():
        assert key in props, f"{case.name}: prop {key!r} missing ({case.note})"
        assert props[key] == want, (
            f"{case.name}: prop {key!r} = {props[key]!r}, expected {want!r} ({case.note})"
        )


# ── (2) Cross-cutting invariants — the zoo's real value ──────────────────────

def test_invariant_all_types_known():
    """No manifest row may declare a device type the plugin can't emit."""
    bad = [(c.name, c.expect_type) for c in CASES if c.expect_type not in KNOWN_TYPES]
    assert not bad, f"unknown expect_type(s): {bad}"


@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_invariant_classification_deterministic(plugin_mod, case):
    """Same payload classified twice must give the same answer. Guards the
    live-reference / shared-mutable-state class of bug (a classifier that
    accumulates or mutates per call)."""
    a = plugin_mod._detect_device_type(case.exposes, model=case.model)
    b = plugin_mod._detect_device_type(case.exposes, model=case.model)
    assert a == b, f"{case.name}: non-deterministic ({a} then {b})"


@pytest.mark.parametrize("case", CASES, ids=_IDS)
def test_invariant_contact_never_becomes_motion(plugin_mod, case):
    """A payload that has `contact` and none of occupancy/presence/water_leak
    must never classify as a motion/occupancy device. (The mirror of the DAM
    'contact never becomes motion' rule — the single most common translator
    mis-file.)"""
    names = _top_level_feature_names(plugin_mod, case.exposes)
    pure_contact = "contact" in names and not (
        names & {"occupancy", "presence", "water_leak"}
    )
    if pure_contact:
        got = plugin_mod._detect_device_type(case.exposes, model=case.model)
        assert got != "z2mOccupancySensor", f"{case.name}: pure contact classified as motion"
        assert got == "z2mContactSensor", f"{case.name}: pure contact not a contact sensor ({got})"


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.exposes], ids=[c.name for c in CASES if c.exposes]
)
def test_invariant_battery_capability_never_dropped(plugin, plugin_mod, case):
    """If a payload exposes `battery`, the built props must record has_battery.
    A capability silently dropped at creation = a state Indigo never makes =
    updates lost forever (the bug-shape behind the indigo-matter SupportsSensorValue
    miss). Only enforced for device types whose capability detector tracks battery."""
    names = _top_level_feature_names(plugin_mod, case.exposes)
    if "battery" not in names:
        return
    type_id, props = _build_props(plugin, plugin_mod, case)
    # Types whose capability detector reports has_battery (relay/light/cover don't).
    battery_aware = {
        "z2mContactSensor", "z2mOccupancySensor", "z2mWaterLeakSensor",
        "z2mTemperatureSensor", "z2mSensor", "z2mButton",
    }
    if type_id in battery_aware:
        assert props.get("has_battery") is True, (
            f"{case.name}: exposes battery but has_battery not set on {type_id}"
        )


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.exposes], ids=[c.name for c in CASES if c.exposes]
)
def test_invariant_colour_lesson(plugin, plugin_mod, case):
    """The 'colour lesson': a light exposing a colour feature must get the
    Supports* colour props set (these gate Indigo states for API-created
    devices; missing them = no colour control, silently)."""
    names = _top_level_feature_names(plugin_mod, case.exposes)
    has_colour_feature = bool(names & {"color_xy", "color_hs", "color"})
    if not has_colour_feature:
        return
    type_id, props = _build_props(plugin, plugin_mod, case)
    assert type_id == "z2mLight", f"{case.name}: colour feature but not a light ({type_id})"
    assert props.get("SupportsColor") is True, f"{case.name}: SupportsColor not set"
    assert props.get("SupportsRGB") is True, f"{case.name}: SupportsRGB not set"
