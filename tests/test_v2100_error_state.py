#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2100_error_state.py
# Description: v2.10.0 — an "offline" error set from zigbee2mqtt's availability
#              verdict survives every routine state write, and only "online"
#              clears it.  Indigo's state writes clear a device's error state by
#              default; tests/indigo_stub.py now does the same, so these fail
#              against any write that forgets clearErrorState=False.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0

import ast
import os

BUNDLE = os.path.join(os.path.dirname(__file__), "..",
                      "Zigbee2MQTTBridge.indigoPlugin", "Contents", "Server Plugin")


def _offline_device(plugin, make_device, dev_id, name, type_id="z2mSensor"):
    dev = make_device(dev_id, name, type_id, pluginProps={"friendly_name": name})
    plugin.friendly_name_map[("zigbee2mqtt", name)] = dev.id
    plugin._process_availability(name, {"state": "offline"})
    assert dev.errorState == "offline"
    return dev


def test_stub_clears_the_error_on_a_plain_write_like_indigo(make_device):
    """The guard for everything below: without this the stub cannot fail."""
    dev = make_device(760, "Stub Check", "z2mSensor")
    dev.setErrorStateOnServer("offline")
    dev.updateStateOnServer("linkQuality", 10)
    assert dev.errorState == ""


def test_bridge_health_counters_keep_the_offline_error(plugin, make_device):
    """bridge/health rewrites every device's counters every ten minutes, dead
    or alive — that write used to wipe the error within ten minutes."""
    dev = _offline_device(plugin, make_device, 761, "Shed Sensor")
    plugin.ieee_map["0xdead"] = dev.id
    plugin._process_device_health(
        {"0xdead": {"messages_per_sec": 0.0, "leave_count": 0,
                    "network_address_changes": 0}}, "zigbee2mqtt")
    assert dev.states.get("leaveCount") == 0, "the counters were still written"
    assert dev.errorState == "offline"


def test_a_republished_state_payload_keeps_the_offline_error(plugin, make_device):
    """zigbee2mqtt republishes its cached state (on startup, or a retained
    topic) — that is not the device talking and must not end the fault."""
    dev = _offline_device(plugin, make_device, 762, "Porch Plug", "z2mRelay")
    plugin._process_device_state("Porch Plug", {"state": "ON", "linkquality": 40})
    assert dev.errorState == "offline"


def test_a_replayed_offline_keeps_the_error(plugin, make_device):
    """A retained "offline" replayed on reconnect writes `availability` again;
    that write must not clear the error it is about to re-assert."""
    dev = _offline_device(plugin, make_device, 763, "Garden Sensor")
    plugin._process_availability("Garden Sensor", {"state": "offline"})
    assert dev.errorState == "offline"
    assert dev.error_writes == ["offline"]


def test_only_online_ends_the_fault(plugin, make_device):
    dev = _offline_device(plugin, make_device, 764, "Loft Sensor")
    plugin.ieee_map["0xbeef"] = dev.id
    plugin._process_device_health({"0xbeef": {"leave_count": 1}}, "zigbee2mqtt")
    plugin._process_device_state("Loft Sensor", {"temperature": 12.5})
    assert dev.errorState == "offline"
    plugin._process_availability("Loft Sensor", {"state": "online"})
    assert dev.errorState == ""


def test_every_device_write_in_the_bundle_keeps_the_error():
    """A new updateStateOnServer call that forgets clearErrorState=False would
    quietly reopen the fault.  The coordinator's deviceCount is the one
    exception: the plugin never sets an error on a coordinator."""
    offenders = []
    for fname in sorted(os.listdir(BUNDLE)):
        if not fname.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(BUNDLE, fname), encoding="utf-8").read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "updateStateOnServer"):
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and first.value == "deviceCount":
                continue
            kept = any(k.arg == "clearErrorState" and isinstance(k.value, ast.Constant)
                       and k.value.value is False for k in node.keywords)
            if not kept:
                offenders.append(f"{fname}:{node.lineno}")
    assert not offenders, f"writes that would clear the offline error: {offenders}"
