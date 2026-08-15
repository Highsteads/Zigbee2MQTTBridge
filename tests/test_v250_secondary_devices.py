#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v250_secondary_devices.py
# Description: Splitting a reading out of a multi-capability device into its own
#              Indigo device, grouped with its parent.
#
#              The point of the design is that it is ADDITIVE: the parent keeps
#              its id and everything pointing at it. The tests that matter most
#              are therefore the ones proving nothing existing is disturbed, and
#              that switching a reading back off never deletes a device the user
#              may have referenced.
# Author:      CliveS & Claude Opus 5
# Date:        15-08-2026
# Version:     1.0

import indigo  # stub

EXPOSES = [
    {"property": "presence", "type": "binary", "access": 1},
    {"property": "temperature", "type": "numeric", "access": 1},
    {"property": "humidity", "type": "numeric", "access": 1},
    {"property": "illuminance", "type": "numeric", "access": 1},
    # settable-only, never reported — must not be offered
    {"property": "pressure", "type": "numeric", "access": 2},
]


def _parent(plugin, make_device, dev_id=850, props=None):
    base = {"friendly_name": "Bathroom Basin", "ieee_address": "0xsec1",
            "mqtt_prefix": "zigbee2mqtt"}
    base.update(props or {})
    dev = make_device(dev_id, "Bathroom Basin Presence Sensor",
                      "z2mOccupancySensor", pluginProps=base)
    plugin.bridge_devices["0xsec1"] = {
        "ieee_address": "0xsec1", "friendly_name": "Bathroom Basin",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"model": "PS-S04D", "exposes": EXPOSES},
    }
    return dev


# ── what gets offered ─────────────────────────────────────────────────────────

def test_only_reported_readings_are_offered(plugin, make_device):
    """Offered from the device's exposes, not from whether a state holds a
    value — several sensors here show temperature 0.0 having never measured
    one, and offering those would invite splitting out a reading that never
    arrives."""
    dev = _parent(plugin, make_device)
    assert plugin._offered_secondaries(dev) == ["temperature", "humidity",
                                                "illuminance"]


def test_a_settable_only_reading_is_not_offered(plugin, make_device):
    dev = _parent(plugin, make_device)
    assert "pressure" not in plugin._offered_secondaries(dev)


def test_a_secondary_offers_nothing_itself(plugin, make_device):
    """No recursion: a secondary must never spawn its own secondaries."""
    dev = make_device(851, "Something [Temperature]", "z2mTemperatureSecondary",
                      pluginProps={"ieee_address": "0xsec1"})
    plugin.bridge_devices["0xsec1"] = {
        "ieee_address": "0xsec1", "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": EXPOSES},
    }
    assert plugin._offered_secondaries(dev) == []


def test_an_unknown_device_offers_nothing(plugin, make_device):
    dev = make_device(852, "Mystery", "z2mSensor", pluginProps={"ieee_address": "0xzzz"})
    assert plugin._offered_secondaries(dev) == []


# ── creating ──────────────────────────────────────────────────────────────────

def test_ticking_a_box_creates_and_groups_a_device(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    new_id = plugin._secondary_dev_id(dev, "temperature")
    assert new_id, "the parent records which device it made"
    created = indigo.devices[new_id]
    assert created.deviceTypeId == "z2mTemperatureSecondary"
    assert created.name == "Bathroom Basin Presence Sensor [Temperature]"
    assert new_id in indigo.device.getGroupList(dev.id)


def test_the_parent_is_untouched(plugin, make_device):
    """The whole reason this is safe where delete-and-recreate was not."""
    dev = _parent(plugin, make_device)
    before_id, before_type = dev.id, dev.deviceTypeId
    before_states = dict(dev.states)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    assert dev.id == before_id
    assert dev.deviceTypeId == before_type
    assert dev.states == before_states


def test_the_secondary_gets_the_native_sensor_property(plugin, make_device):
    """A native sensor only HAS sensorValue while SupportsSensorValue is True.
    Without it every write is silently dropped and the device shows nothing."""
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    created = indigo.devices[plugin._secondary_dev_id(dev, "temperature")]
    assert created.pluginProps["SupportsSensorValue"] is True
    assert created.pluginProps["SupportsOnState"] is False


def test_a_name_clash_is_resolved(plugin, make_device):
    make_device(853, "Bathroom Basin Presence Sensor [Temperature]", "z2mSensor")
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    created = indigo.devices[plugin._secondary_dev_id(dev, "temperature")]
    assert created.name.endswith(" 2")


def test_unticked_readings_create_nothing(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "false"})
    assert plugin._secondary_dev_id(dev, "temperature") is None


def test_saving_twice_does_not_create_twice(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    first = plugin._secondary_dev_id(dev, "temperature")
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    assert plugin._secondary_dev_id(dev, "temperature") == first


# ── retiring ──────────────────────────────────────────────────────────────────

def test_unticking_never_deletes_the_device(plugin, make_device):
    """The user may have pointed a trigger or control page at it. Deleting
    would break those silently; renaming makes it obvious."""
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    secondary_id = plugin._secondary_dev_id(dev, "temperature")
    plugin._sync_secondaries(dev, {"z2msec_temperature": "false"})
    assert secondary_id in indigo.devices, "still there"
    assert "[UNUSED" in indigo.devices[secondary_id].name
    assert plugin._secondary_dev_id(dev, "temperature") is None


def test_unticking_ungroups_it(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    secondary_id = plugin._secondary_dev_id(dev, "temperature")
    plugin._sync_secondaries(dev, {"z2msec_temperature": "false"})
    assert secondary_id not in indigo.device.getGroupList(dev.id)


# ── feeding them ──────────────────────────────────────────────────────────────

def test_readings_reach_the_secondary(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true",
                                   "z2msec_humidity": "true"})
    plugin._route_to_secondaries(dev, {"temperature": 24.03, "humidity": 58.4,
                                       "presence": True})
    temp = indigo.devices[plugin._secondary_dev_id(dev, "temperature")]
    hum = indigo.devices[plugin._secondary_dev_id(dev, "humidity")]
    assert temp.states["temperature"] == 24.0
    assert temp.states["sensorValue"] == 24.0
    assert hum.states["humidity"] == 58.4


def test_the_sensor_value_carries_units(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    plugin._route_to_secondaries(dev, {"temperature": 24.0})
    temp = indigo.devices[plugin._secondary_dev_id(dev, "temperature")]
    ui = [w for w in temp.state_writes if w[0] == "sensorValue"][-1][2]
    assert ui == "24.0 °C"


def test_a_null_reading_is_not_written_as_zero(plugin, make_device):
    """zigbee2mqtt publishes nulls after a restart. Absent is not a reading."""
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    plugin._route_to_secondaries(dev, {"temperature": None})
    temp = indigo.devices[plugin._secondary_dev_id(dev, "temperature")]
    assert "sensorValue" not in temp.states


def test_routing_without_a_secondary_does_nothing(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._route_to_secondaries(dev, {"temperature": 24.0})   # none created


def test_a_deleted_secondary_is_forgotten_not_warned_about_for_ever(
        plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_temperature": "true"})
    secondary_id = plugin._secondary_dev_id(dev, "temperature")
    del indigo.devices._by_id[secondary_id]          # user deleted it by hand
    plugin._route_to_secondaries(dev, {"temperature": 24.0})
    assert plugin._secondary_dev_id(dev, "temperature") is None


def test_illuminance_is_rounded_to_a_whole_number(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin._sync_secondaries(dev, {"z2msec_illuminance": "true"})
    plugin._route_to_secondaries(dev, {"illuminance": 137.6})
    lux = indigo.devices[plugin._secondary_dev_id(dev, "illuminance")]
    assert lux.states["illuminance"] == 138


# ── the dialog ────────────────────────────────────────────────────────────────

def test_checkboxes_appear_for_offered_readings(plugin, make_device):
    dev = _parent(plugin, make_device)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert 'id="z2msec_temperature"' in xml
    assert 'id="z2msec_humidity"' in xml
    assert 'id="z2msec_pressure"' not in xml, "not reported by this device"
    import xml.dom.minidom as minidom
    minidom.parseString(xml)


def test_both_generated_sections_survive_together(plugin, make_device):
    """Two mixins append to the same dialog. Whichever runs first must not
    swallow the other — they chain through super()."""
    dev = _parent(plugin, make_device)
    plugin.bridge_devices["0xsec1"]["definition"]["exposes"] = EXPOSES + [
        {"property": "motion_sensitivity", "type": "enum", "access": 7,
         "values": ["low", "high"]},
    ]
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "z2mset_motion_sensitivity" in xml, "settings section"
    assert "z2msec_temperature" in xml, "secondary-device section"
    import xml.dom.minidom as minidom
    minidom.parseString(xml)


def test_closing_the_dialog_runs_both_hooks(plugin, make_device, monkeypatch):
    dev = _parent(plugin, make_device)
    called = []
    monkeypatch.setattr(plugin, "_sync_secondaries",
                        lambda d, v: called.append("secondary"))
    monkeypatch.setattr(plugin, "_managed_settings_for",
                        lambda d: called.append("settings") or [])
    plugin.closedDeviceConfigUi({}, False, "z2mOccupancySensor", dev.id)
    assert "secondary" in called and "settings" in called


def test_cancelling_creates_nothing(plugin, make_device):
    dev = _parent(plugin, make_device)
    plugin.closedDeviceConfigUi({"z2msec_temperature": "true"}, True,
                                "z2mOccupancySensor", dev.id)
    assert plugin._secondary_dev_id(dev, "temperature") is None
