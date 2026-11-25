#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2204_battery_device_called_mains.py
# Description: A battery device that tells zigbee2mqtt it runs on mains is not
#              treated as a mains device (v2.20.4). Live case 25-11-2026: the
#              Third Reality 3RTHS24BZ temperature and humidity sensor runs on
#              two AAA cells, reports "Mains (single phase)", and had its
#              battery state labelled "Mains".
# Author:      CliveS & Claude Fable 5.2
# Date:        25-11-2026
# Version:     1.0

MAINS = "Mains (single phase)"


def _sensor(make_device, dev_id=9801, **extra):
    props = {"friendly_name": "En Suite Sensor", "ieee_address": "0xabc",
             "power_source": MAINS, "has_battery": True,
             "has_temperature": True, "has_humidity": True}
    states = extra.pop("states", None)
    props.update(extra)
    kwargs = {"pluginProps": props}
    if states is not None:
        kwargs["states"] = states
    return make_device(dev_id, "En Suite Sensor", "z2mTemperatureSensor", **kwargs)


def test_a_device_with_a_battery_reading_is_not_mains(plugin_mod):
    is_mains = plugin_mod.Plugin._is_mains_powered
    assert is_mains({"power_source": MAINS, "has_battery": True}) is False
    assert is_mains({"power_source": MAINS, "has_battery": "true"}) is False
    assert is_mains({"power_source": MAINS, "has_battery": False}) is True
    assert is_mains({"power_source": MAINS, "has_battery": "false"}) is True
    assert is_mains({"power_source": MAINS}) is True


def test_it_is_given_a_battery_state(plugin, make_device):
    dev = _sensor(make_device)
    plugin._ensure_device_states(dev)
    assert "battery" in dev.states


def test_a_wrong_mains_label_is_replaced(plugin, make_device):
    dev = _sensor(make_device, 9802, states={"battery": 0, "battery.ui": "Mains"})
    plugin._backfill_native_attributes(dev)
    writes = [w for w in dev.state_writes if w[0] == "battery"]
    assert writes and writes[-1][1] == 0
    assert writes[-1][2] == "Not reported yet"
    assert "batteryLevel" not in dev.states, "a seeded 0 is never a native reading"


def test_a_seeded_zero_with_no_label_is_left_alone(plugin, make_device):
    dev = _sensor(make_device, 9803, states={"battery": 0})
    plugin._backfill_native_attributes(dev)
    assert not [w for w in dev.state_writes if w[0] == "battery"]


def test_a_real_reading_is_mirrored_not_relabelled(plugin, make_device):
    dev = _sensor(make_device, 9804, states={"battery": 87, "battery.ui": "87 %"})
    plugin._backfill_native_attributes(dev)
    assert not [w for w in dev.state_writes
                if w[0] == "battery" and w[2] in ("Mains", "Not reported yet")]


def test_a_true_mains_device_keeps_its_label(plugin, make_device):
    dev = make_device(9805, "Garage Presence", "z2mOccupancySensor",
                      pluginProps={"friendly_name": "Garage Presence",
                                   "power_source": MAINS, "has_battery": False},
                      states={"battery": 0})
    plugin._backfill_native_attributes(dev)
    assert [w for w in dev.state_writes if w[0] == "battery"][-1][2] == "Mains"


def test_the_power_source_backfill_does_not_label_it(plugin, make_device):
    dev = make_device(9806, "En Suite Sensor", "z2mTemperatureSensor",
                      pluginProps={"friendly_name": "En Suite Sensor",
                                   "ieee_address": "0xabd", "has_battery": True},
                      states={"battery": 0})
    plugin.bridge_devices["0xabd"] = {
        "ieee_address": "0xabd", "friendly_name": "En Suite Sensor",
        "power_source": MAINS, "_mqtt_prefix": "zigbee2mqtt",
    }
    plugin._backfill_power_source("zigbee2mqtt")
    assert dev.pluginProps["power_source"] == MAINS
    assert not [w for w in dev.state_writes if w[0] == "battery" and w[2] == "Mains"]
