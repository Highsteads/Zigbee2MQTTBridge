#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    zoo_manifest.py
# Description: The "device zoo" — a single declarative contract table mapping a
#              zigbee2mqtt `exposes` payload to the FULL translation the plugin
#              must produce: the Indigo device TYPE *and* the capability props
#              (has_*, Supports*). One row per device class. Driven by
#              test_zoo.py, which parametrises over CASES and also enforces
#              cross-cutting invariants no single per-case test can.
#
#              Why this exists: nearly every CliveS bridge plugin is a
#              translator (external device shape -> Indigo device). The bugs
#              live in that translation step and they don't need hardware to
#              reproduce — only the input shape. The zoo turns "a payload got
#              mis-classified" from a hardware/beta-tester discovery into a
#              millisecond unit failure, and a fixed bug becomes a new row here
#              (permanent regression guard).
#
#              SEEDING: the payloads below are faithful representative z2m
#              `exposes` shapes (the same ones the existing detection tests use,
#              extended with the expected props). The next enrichment step is to
#              replace/augment these with REAL captures from the live broker's
#              `zigbee2mqtt/bridge/devices` topic for CliveS's actual estate
#              (Aqara FP1, Moes presence, Aqara contacts, etc.) — higher fidelity
#              than docs-modelled shapes. Mark those cases real=True.
# Author:      CliveS & Claude Opus 4.8
# Date:        13-06-2026
# Version:     1.0

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ZooCase:
    """One zoo animal: an input payload and the full translation it must yield.

    expect_props is a SUBSET assertion — every key/value here must be present in
    the props the plugin builds, but the plugin may add more. This keeps a case
    focused on the capabilities that matter for that device class without having
    to restate every prop the builder emits.
    """
    name:         str                 # stable id, shown in the parametrise label
    exposes:      object              # the z2m `exposes` array (or None)
    expect_type:  str                 # the deviceTypeId the classifier must pick
    expect_props: dict = field(default_factory=dict)   # subset that must be present
    model:        str = ""            # device model string (drives repeater detection)
    real:         bool = False        # True once seeded from a real broker capture
    note:         str = ""            # why this animal is in the zoo


# ── Light family ─────────────────────────────────────────────────────────────

_LIGHT_CT = [{
    "type": "light",
    "features": [
        {"name": "state",      "type": "binary",  "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "brightness", "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 254},
        {"name": "color_temp", "type": "numeric", "access": 7,
         "value_min": 153, "value_max": 500},
    ],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

_LIGHT_RGB_CT = [{
    "type": "light",
    "features": [
        {"name": "state",      "type": "binary",  "access": 7},
        {"name": "brightness", "type": "numeric", "access": 7},
        {"name": "color_temp", "type": "numeric", "access": 7},
        {"name": "color_xy",   "type": "composite", "access": 7,
         "features": [{"name": "x", "type": "numeric"},
                      {"name": "y", "type": "numeric"}]},
    ],
}]

# ── Relay family ─────────────────────────────────────────────────────────────

_RELAY = [{
    "type": "switch",
    "features": [{"name": "state", "type": "binary", "access": 7,
                  "value_on": "ON", "value_off": "OFF"}],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

_RELAY_POWER = [{
    "type": "switch",
    "features": [{"name": "state", "type": "binary", "access": 7}],
}, {"name": "power",  "type": "numeric", "access": 1},
   {"name": "energy", "type": "numeric", "access": 1},
   {"name": "linkquality", "type": "numeric", "access": 1}]

# ── Sensor family ────────────────────────────────────────────────────────────

_CONTACT = [
    {"name": "contact",     "type": "binary",  "access": 1,
     "value_on": False, "value_off": True},
    {"name": "battery",     "type": "numeric", "access": 1, "unit": "%"},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

_OCCUPANCY_PIR = [
    {"name": "occupancy",       "type": "binary",  "access": 1},
    {"name": "illuminance_lux", "type": "numeric", "access": 1},
    {"name": "battery",         "type": "numeric", "access": 1},
    {"name": "linkquality",     "type": "numeric", "access": 1},
]

_PRESENCE_MMWAVE = [
    {"name": "presence",    "type": "binary",  "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

_WATER_LEAK = [
    {"name": "water_leak",  "type": "binary",  "access": 1},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

_TEMP_HUMIDITY = [
    {"name": "temperature", "type": "numeric", "access": 1, "unit": "°C"},
    {"name": "humidity",    "type": "numeric", "access": 1, "unit": "%"},
    {"name": "pressure",    "type": "numeric", "access": 1, "unit": "hPa"},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

# Mixed contact+occupancy: fits no specific sub-type, must fall back to generic.
_MIXED_SENSOR = [
    {"name": "contact",     "type": "binary",  "access": 1},
    {"name": "occupancy",   "type": "binary",  "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

# ── Cover / button / repeater ────────────────────────────────────────────────

_COVER = [{
    "type": "cover",
    "features": [
        {"name": "state",    "type": "enum",    "access": 7,
         "values": ["OPEN", "CLOSE", "STOP"]},
        {"name": "position", "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 100},
    ],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

_BUTTON = [
    {"name": "action",      "type": "enum",    "access": 1,
     "values": ["single", "double", "long", "hold", "release"]},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

_REPEATER_LQ_ONLY = [{"name": "linkquality", "type": "numeric", "access": 1}]


# ── The contract table ───────────────────────────────────────────────────────
# Add a row to cover a new device class — or to lock in a bug you just fixed.

CASES: list[ZooCase] = [
    ZooCase("light_ct", _LIGHT_CT, "z2mLight",
            {"has_brightness": True, "has_color_temp": True, "has_color": False,
             "SupportsWhiteTemperature": True, "SupportsColor": False},
            note="tunable-white bulb: CT but no colour"),
    ZooCase("light_rgb_ct", _LIGHT_RGB_CT, "z2mLight",
            {"has_color": True, "SupportsColor": True, "SupportsRGB": True,
             "SupportsWhiteTemperature": True},
            note="full-colour bulb — the 'colour lesson': Supports* must be set"),
    ZooCase("relay_plain", _RELAY, "z2mRelay",
            {"has_power": False, "has_energy": False},
            note="bare on/off plug"),
    ZooCase("relay_metering", _RELAY_POWER, "z2mRelay",
            {"has_power": True, "has_energy": True},
            note="metering plug — power/energy must be picked up"),
    ZooCase("contact", _CONTACT, "z2mContactSensor",
            {"has_battery": True},
            note="door/window contact"),
    ZooCase("occupancy_pir", _OCCUPANCY_PIR, "z2mOccupancySensor",
            {"has_pir": True, "has_illuminance": True, "has_battery": True},
            note="PIR occupancy + lux"),
    ZooCase("presence_mmwave", _PRESENCE_MMWAVE, "z2mOccupancySensor",
            {"has_presence": True},
            note="mmWave presence — 'presence' not 'occupancy', same class"),
    ZooCase("water_leak", _WATER_LEAK, "z2mWaterLeakSensor",
            {"has_battery": True},
            note="leak sensor"),
    ZooCase("temp_humidity", _TEMP_HUMIDITY, "z2mTemperatureSensor",
            {"has_temperature": True, "has_humidity": True, "has_pressure": True},
            note="environmental sensor"),
    ZooCase("mixed_sensor", _MIXED_SENSOR, "z2mSensor",
            {"has_contact": True, "has_occupancy": True},
            note="contact+occupancy together -> generic catch-all"),
    ZooCase("cover", _COVER, "z2mCover",
            {"has_tilt": False},
            note="blind/curtain with position"),
    ZooCase("button", _BUTTON, "z2mButton",
            {"has_battery": True},
            note="scene controller — action enum wins over any stray state leaf"),
    ZooCase("repeater_lq_only", _REPEATER_LQ_ONLY, "z2mRepeater", {},
            note="router/repeater: only linkquality exposed"),
    ZooCase("repeater_by_model", _RELAY, "z2mRepeater", {},
            model="SLZB-06P7",
            note="known repeater model wins even with a writable state leaf"),
    ZooCase("empty_exposes", [], "z2mSensor", {},
            note="empty list (not None) falls to generic — repeater needs a lq "
                 "leaf or model hint, a bare [] does not"),
    ZooCase("none_exposes", None, "z2mSensor", {},
            note="defensive: exposes=None must not crash, falls to generic"),
]


# ── Real captures from CliveS's live broker (zigbee2mqtt/bridge/devices) ──────
# Higher-fidelity than the modelled shapes above: these are the verbatim
# `exposes` arrays of real devices in the estate, captured 13-Jun-2026. Stored
# as JSON under tests/zoo_real/ so they read as data, not code. Re-capture with:
#   mosquitto_sub -h <broker> -u <user> -P <pass> -t 'zigbee2mqtt/bridge/devices' -C 1
# then split per device into tests/zoo_real/<name>.json ({model, vendor, exposes}).

import json as _json
import os as _os

_REAL_DIR = _os.path.join(_os.path.dirname(__file__), "zoo_real")


def _load_real(stem: str):
    with open(_os.path.join(_REAL_DIR, f"{stem}.json"), encoding="utf-8") as fh:
        d = _json.load(fh)
    return d.get("model", ""), d.get("exposes")


def _real(stem, expect_type, expect_props=None, note=""):
    model, exposes = _load_real(stem)
    return ZooCase(f"real_{stem}", exposes, expect_type, expect_props or {},
                   model=model, real=True, note=note)


CASES += [
    # The headline find: the Aqara FP1 exposes BOTH `presence` and an `action`
    # enum (region events). It MUST classify as an occupancy sensor — the action
    # is presence-event metadata, not a scene controller. (Pre-fix the action
    # rule won and it became a z2mButton; the live device is the catch-all
    # z2mSensor because its exposes gained `action` after creation.)
    _real("fp1_presence", "z2mOccupancySensor", {"has_presence": True},
          note="Aqara FP1 RTCZCGQ11LM — presence + action enum; presence wins"),
    _real("occupancy_pir", "z2mOccupancySensor", {"has_presence": True, "has_illuminance": True},
          note="Aqara PS-S04D mmWave presence + lux (uses 'presence', not 'occupancy')"),
    _real("contact_door", "z2mContactSensor", {},
          note="Tuya SNTZ007 contact"),
    _real("temp_humidity", "z2mTemperatureSensor", {"has_temperature": True, "has_humidity": True},
          note="Sonoff SNZB-02D"),
    _real("water_leak", "z2mWaterLeakSensor", {},
          note="Aqara SJCGQ11LM leak"),
    _real("repeater", "z2mRepeater", {},
          note="Tuya TS0207 repeater"),
    _real("button_push", "z2mButton", {},
          note="Push_LO push button — no presence/occupancy, stays a button"),
    _real("light_bulb", "z2mLight", {"has_brightness": True},
          note="Hue 9290012573A bulb"),
]
