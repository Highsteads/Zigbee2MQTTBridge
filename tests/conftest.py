#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    conftest.py
# Description: Shared pytest fixtures. Installs the indigo module stub BEFORE
#              plugin.py is imported anywhere in the test session, then
#              imports the plugin module and exposes it as a fixture.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# ── Install indigo stub BEFORE any test imports plugin.py ────────────────────

THIS = Path(__file__).resolve()
TESTS_DIR  = THIS.parent
REPO_ROOT  = TESTS_DIR.parent
SERVER_DIR = REPO_ROOT / "Zigbee2MQTTBridge.indigoPlugin" / "Contents" / "Server Plugin"

# Stub goes on sys.path so `from indigo_stub import install` works
sys.path.insert(0, str(TESTS_DIR))
# Plugin source dir so `import plugin` resolves
sys.path.insert(0, str(SERVER_DIR))

from indigo_stub import install as install_indigo_stub  # noqa: E402

install_indigo_stub()

# Indigo's plugin lives in a path Python won't import as a normal module name
# unless we tweak this — and plugin.py expects ``os.getcwd()`` to be the
# Server Plugin dir at import time (for ``from plugin_utils import …``).
os.chdir(str(SERVER_DIR))

import plugin as plugin_module  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def plugin_mod():
    """The imported plugin module — for tests of module-level helpers."""
    return plugin_module


@pytest.fixture
def plugin():
    """A fresh Plugin instance with default prefs. State is per-test."""
    # Re-import indigo stub freshness for each test if needed
    importlib.reload(plugin_module) if False else None
    p = plugin_module.Plugin(
        pluginId          = "com.clives.indigoplugin.z2mbridge",
        pluginDisplayName = "Zigbee2MQTT Bridge",
        pluginVersion     = "1.9.8",
        pluginPrefs       = {"mqtt_topic_prefix": "zigbee2mqtt"},
    )
    yield p


@pytest.fixture
def make_device():
    """Factory: build a FakeDevice and register it in the indigo.devices stub."""
    import indigo  # the stub
    from indigo_stub import FakeDevice

    created = []

    def _make(id, name, deviceTypeId, **kwargs):
        dev = FakeDevice(id=id, name=name, deviceTypeId=deviceTypeId, **kwargs)
        indigo.devices.add(dev)
        created.append(dev)
        return dev

    yield _make

    # cleanup
    for dev in created:
        indigo.devices._by_id.pop(dev.id, None)


# ── Fixture exposes (real-world payload samples) ─────────────────────────────

# Minimal canonical zigbee2mqtt `exposes` arrays representing the device
# classes the plugin can recognise. Modelled on real payloads from z2m docs.

EXPOSES_LIGHT_CT = [{
    "type": "light",
    "features": [
        {"name": "state",       "type": "binary",  "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "brightness",  "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 254},
        {"name": "color_temp",  "type": "numeric", "access": 7,
         "value_min": 153, "value_max": 500},
    ],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

EXPOSES_LIGHT_RGB_CT = [{
    "type": "light",
    "features": [
        {"name": "state",       "type": "binary",  "access": 7,
         "value_on": "ON", "value_off": "OFF"},
        {"name": "brightness",  "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 254},
        {"name": "color_temp",  "type": "numeric", "access": 7,
         "value_min": 153, "value_max": 500},
        {"name": "color_xy",    "type": "composite", "access": 7,
         "features": [
            {"name": "x", "type": "numeric"},
            {"name": "y", "type": "numeric"},
         ]},
    ],
}]

EXPOSES_RELAY = [{
    "type": "switch",
    "features": [
        {"name": "state", "type": "binary", "access": 7,
         "value_on": "ON", "value_off": "OFF"},
    ],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

EXPOSES_RELAY_WITH_POWER = [{
    "type": "switch",
    "features": [
        {"name": "state", "type": "binary", "access": 7,
         "value_on": "ON", "value_off": "OFF"},
    ],
}, {"name": "power",  "type": "numeric", "access": 1},
   {"name": "energy", "type": "numeric", "access": 1},
   {"name": "linkquality", "type": "numeric", "access": 1}]

EXPOSES_CONTACT = [
    {"name": "contact",     "type": "binary", "access": 1,
     "value_on": False, "value_off": True},
    {"name": "battery",     "type": "numeric", "access": 1, "unit": "%"},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_OCCUPANCY = [
    {"name": "occupancy",   "type": "binary", "access": 1,
     "value_on": True,  "value_off": False},
    {"name": "illuminance_lux", "type": "numeric", "access": 1},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_PRESENCE_MMWAVE = [
    {"name": "presence",    "type": "binary", "access": 1,
     "value_on": True, "value_off": False},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_WATER_LEAK = [
    {"name": "water_leak",  "type": "binary", "access": 1,
     "value_on": True, "value_off": False},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_TEMP_HUMIDITY = [
    {"name": "temperature", "type": "numeric", "access": 1, "unit": "°C"},
    {"name": "humidity",    "type": "numeric", "access": 1, "unit": "%"},
    {"name": "pressure",    "type": "numeric", "access": 1, "unit": "hPa"},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_COVER = [{
    "type": "cover",
    "features": [
        {"name": "state",    "type": "enum", "access": 7,
         "values": ["OPEN", "CLOSE", "STOP"]},
        {"name": "position", "type": "numeric", "access": 7,
         "value_min": 0, "value_max": 100},
    ],
}, {"name": "linkquality", "type": "numeric", "access": 1}]

EXPOSES_BUTTON = [
    {"name": "action", "type": "enum", "access": 1,
     "values": ["single", "double", "long", "hold", "release"]},
    {"name": "battery",     "type": "numeric", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_REPEATER_LQ_ONLY = [
    {"name": "linkquality", "type": "numeric", "access": 1},
]

EXPOSES_REPEATER_EMPTY: list = []

EXPOSES_MIXED_SENSOR = [
    {"name": "contact",     "type": "binary", "access": 1},
    {"name": "occupancy",   "type": "binary", "access": 1},
    {"name": "linkquality", "type": "numeric", "access": 1},
]


@pytest.fixture
def fixtures():
    """Bundle of named exposes payloads, accessed as ``fixtures.LIGHT_CT`` etc."""
    class _Fixtures: ...
    f = _Fixtures()
    f.LIGHT_CT             = EXPOSES_LIGHT_CT
    f.LIGHT_RGB_CT         = EXPOSES_LIGHT_RGB_CT
    f.RELAY                = EXPOSES_RELAY
    f.RELAY_WITH_POWER     = EXPOSES_RELAY_WITH_POWER
    f.CONTACT              = EXPOSES_CONTACT
    f.OCCUPANCY            = EXPOSES_OCCUPANCY
    f.PRESENCE_MMWAVE      = EXPOSES_PRESENCE_MMWAVE
    f.WATER_LEAK           = EXPOSES_WATER_LEAK
    f.TEMP_HUMIDITY        = EXPOSES_TEMP_HUMIDITY
    f.COVER                = EXPOSES_COVER
    f.BUTTON               = EXPOSES_BUTTON
    f.REPEATER_LQ_ONLY     = EXPOSES_REPEATER_LQ_ONLY
    f.REPEATER_EMPTY       = EXPOSES_REPEATER_EMPTY
    f.MIXED_SENSOR         = EXPOSES_MIXED_SENSOR
    return f


# ── Action helper ────────────────────────────────────────────────────────────

class FakeAction:
    """Stand-in for the action object Indigo passes to actionControl* methods."""

    def __init__(self, deviceAction=None, sensorAction=None,
                 actionValue=None, props=None):
        self.deviceAction = deviceAction
        self.sensorAction = sensorAction
        self.actionValue  = actionValue
        self.props        = props or {}


@pytest.fixture
def make_action():
    return FakeAction
