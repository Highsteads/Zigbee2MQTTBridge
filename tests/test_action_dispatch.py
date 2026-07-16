#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_action_dispatch.py
# Description: Tests for actionControlDevice / actionControlDimmer /
#              actionControlSensor / actionControlUniversalDevices. We don't
#              connect to a real MQTT broker — _publish is patched to capture
#              outgoing topic + payload pairs.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

import indigo  # stub


def _patch_publish(plugin):
    """Replace _publish with a recorder that captures calls. Returns the list
    of (topic, payload_dict) pairs so the test can assert on them."""
    sent: list[tuple[str, dict]] = []

    def fake_publish(topic, payload):
        sent.append((topic, payload))

    plugin._publish = fake_publish
    return sent


# ── actionControlDevice (relay path) ─────────────────────────────────────────

def test_relay_turn_on(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(101, "Lounge Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Lounge Plug"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    assert sent == [("zigbee2mqtt/Lounge Plug/set", {"state": "ON"})]


def test_relay_turn_off(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(102, "Lounge Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Lounge Plug"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOff), dev)
    assert sent == [("zigbee2mqtt/Lounge Plug/set", {"state": "OFF"})]


def test_relay_toggle_when_on_sends_off(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(103, "Lounge Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Lounge Plug"},
                      onState=True)

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.Toggle), dev)
    assert sent == [("zigbee2mqtt/Lounge Plug/set", {"state": "OFF"})]


def test_relay_toggle_when_off_sends_on(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(104, "Lounge Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Lounge Plug"},
                      onState=False)

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.Toggle), dev)
    assert sent == [("zigbee2mqtt/Lounge Plug/set", {"state": "ON"})]


def test_relay_status_request(plugin, make_device, make_action):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = _patch_publish(plugin)
    dev = make_device(105, "Lounge Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Lounge Plug"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.RequestStatus), dev)
    assert sent[0][0].endswith("/Lounge Plug/get")


def test_relay_uses_per_device_prefix(plugin, make_device, make_action):
    """Devices stored with mqtt_prefix should publish to that prefix."""
    sent = _patch_publish(plugin)
    dev = make_device(106, "Garage Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Garage Plug",
                                   "mqtt_prefix": "zigbee2mqtt_garage"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    assert sent == [("zigbee2mqtt_garage/Garage Plug/set", {"state": "ON"})]


# ── actionControlDimmer (light path) ─────────────────────────────────────────

def test_light_turn_on(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(201, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDimmerRelayAction.TurnOn), dev)
    assert sent == [("zigbee2mqtt/Lounge Lamp/set", {"state": "ON"})]


def test_light_set_brightness_50pct(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(202, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"})

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetBrightness, actionValue=50), dev)
    topic, payload = sent[0]
    assert topic == "zigbee2mqtt/Lounge Lamp/set"
    assert payload["state"] == "ON"
    assert payload["brightness"] == 127   # _brightness_100_to_255(50)


def test_light_set_brightness_zero_sends_off(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(203, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"})

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetBrightness, actionValue=0), dev)
    _, payload = sent[0]
    assert payload["state"] == "OFF"


def test_light_brighten_by(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(204, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"},
                      brightness=40)

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.BrightenBy, actionValue=20), dev)
    _, payload = sent[0]
    # 40 + 20 = 60% -> 153 (int(60 * 2.55))
    assert payload["brightness"] == 153


def test_light_dim_by_clamped_to_zero(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(205, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"},
                      brightness=5)

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.DimBy, actionValue=20), dev)
    _, payload = sent[0]
    # 5 - 20 = -15 -> clamped to 0 -> OFF + brightness=1 (min clamp)
    assert payload["state"] == "OFF"


def test_light_set_color_temp_kelvin(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(206, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"})

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetColorLevels,
        actionValue={"whiteTemperature": 2700}), dev)
    _, payload = sent[0]
    assert "color_temp" in payload
    # 2700K -> ~370 mireds
    assert 360 <= payload["color_temp"] <= 380
    assert payload["state"] == "ON"


def test_light_set_color_rgb(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(207, "Lounge Lamp", "z2mLight",
                      pluginProps={"friendly_name": "Lounge Lamp"})

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetColorLevels,
        actionValue={"redLevel": 100, "greenLevel": 0, "blueLevel": 0}), dev)
    _, payload = sent[0]
    assert payload["color"] == {"r": 255, "g": 0, "b": 0}
    assert payload["state"] == "ON"


# ── actionControlDimmer (cover path) ─────────────────────────────────────────

def test_cover_open(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(301, "Lounge Blind", "z2mCover",
                      pluginProps={"friendly_name": "Lounge Blind"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDimmerRelayAction.TurnOn), dev)
    assert sent == [("zigbee2mqtt/Lounge Blind/set", {"state": "OPEN"})]


def test_cover_close(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(302, "Lounge Blind", "z2mCover",
                      pluginProps={"friendly_name": "Lounge Blind"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDimmerRelayAction.TurnOff), dev)
    assert sent == [("zigbee2mqtt/Lounge Blind/set", {"state": "CLOSE"})]


def test_cover_set_position(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(303, "Lounge Blind", "z2mCover",
                      pluginProps={"friendly_name": "Lounge Blind"})

    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetBrightness, actionValue=42), dev)
    assert sent == [("zigbee2mqtt/Lounge Blind/set", {"position": 42})]


def test_cover_set_color_no_op(plugin, make_device, make_action):
    """SetColorLevels on a cover must not crash — it logs a warning and returns."""
    sent = _patch_publish(plugin)
    dev = make_device(304, "Lounge Blind", "z2mCover",
                      pluginProps={"friendly_name": "Lounge Blind"})

    # No exception
    plugin.actionControlDevice(make_action(
        deviceAction=indigo.kDimmerRelayAction.SetColorLevels,
        actionValue={"redLevel": 100}), dev)
    assert sent == []   # nothing published


# ── actionControlSensor (the v1.9.8 fix) ─────────────────────────────────────

def test_sensor_status_request_uses_sensorAction(plugin, make_device, make_action):
    """Confirms the v1.9.8 fix — SensorAction uses .sensorAction, not .deviceAction.
    Calling with sensorAction=RequestStatus must publish a /get to the right topic."""
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = _patch_publish(plugin)
    dev = make_device(401, "Bathroom Door", "z2mContactSensor",
                      pluginProps={"friendly_name": "Bathroom Door"})

    plugin.actionControlSensor(
        make_action(sensorAction=indigo.kSensorAction.RequestStatus), dev)

    assert len(sent) == 1
    assert sent[0][0] == "zigbee2mqtt/Bathroom Door/get"


def test_sensor_unhandled_action_does_not_crash(plugin, make_device, make_action):
    sent = _patch_publish(plugin)
    dev = make_device(402, "Bathroom Door", "z2mContactSensor",
                      pluginProps={"friendly_name": "Bathroom Door"})

    # Some unknown sensor action — should log WARNING, not raise
    plugin.actionControlSensor(make_action(sensorAction="SomeUnknownAction"), dev)
    assert sent == []


# ── actionControlUniversal ───────────────────────────────────────────────────

def test_universal_request_status(plugin, make_device, make_action):
    plugin.mqtt_connected = True   # /get is a quiet no-op offline since v2.0.0
    sent = _patch_publish(plugin)
    dev = make_device(501, "Some Device", "z2mRelay",
                      pluginProps={"friendly_name": "Some Device"})

    # v1.9.15: Indigo's callback is actionControlUniversal (not ...Devices).
    plugin.actionControlUniversal(
        make_action(deviceAction=indigo.kUniversalAction.RequestStatus), dev)
    assert len(sent) == 1
    assert sent[0][0].endswith("/Some Device/get")
