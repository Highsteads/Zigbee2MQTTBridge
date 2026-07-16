#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_cover_button_repeater.py
# Description: Tests for the remaining state-processing handlers — covers,
#              buttons, and repeaters. Also tests the auto-reclassify path
#              (relay -> button) and proves the v1.9.9 _ensure_device_folder
#              bug fix.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

import pytest
import indigo  # stub


# ── _process_cover_state ─────────────────────────────────────────────────────

def test_cover_open_state(plugin, make_device):
    dev = make_device(1, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"state": "OPEN"})
    assert dev.states["onOffState"] is True
    assert dev.states["coverState"] == "open"


def test_cover_closed_state(plugin, make_device):
    dev = make_device(2, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"state": "CLOSE"})
    assert dev.states["onOffState"] is False


def test_cover_position_drives_brightness(plugin, make_device):
    dev = make_device(3, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"position": 75})
    assert dev.states["brightnessLevel"] == 75
    assert dev.states["onOffState"] is True   # any position > 0 = open


def test_cover_position_zero_is_closed(plugin, make_device):
    dev = make_device(4, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"position": 0})
    assert dev.states["brightnessLevel"] == 0
    assert dev.states["onOffState"] is False


def test_cover_position_clamped(plugin, make_device):
    """Out-of-range positions must clamp to 0-100, not crash."""
    dev = make_device(5, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"position": 150})
    assert dev.states["brightnessLevel"] == 100
    plugin._process_cover_state(dev, {"position": -5})
    assert dev.states["brightnessLevel"] == 0


def test_cover_state_stop_leaves_onoffstate(plugin, make_device):
    """STOP doesn't change onOffState — partial-open is ambiguous."""
    dev = make_device(6, "Blind", "z2mCover", states={"onOffState": True})
    dev.onState = True
    plugin._process_cover_state(dev, {"state": "STOP"})
    # No onOffState write — original True preserved
    onoff_writes = [w for w in dev.state_writes if w[0] == "onOffState"]
    assert onoff_writes == []


def test_cover_tilt(plugin, make_device):
    dev = make_device(7, "Blind", "z2mCover")
    plugin._process_cover_state(dev, {"tilt": 45})
    assert dev.states["tiltAngle"] == 45


# ── _process_button_state ────────────────────────────────────────────────────

def test_button_single_press_increments_count(plugin, make_device):
    dev = make_device(10, "Remote", "z2mButton",
                      states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "1_single"})
    # lastAction stores the NORMALISED action token (button index stripped — it
    # lives in lastButton) so it matches a List enum Option / sub-state.
    assert dev.states["lastAction"] == "single"
    assert dev.states["lastButton"] == 1
    assert dev.states["pressCount"] == 1


def test_button_action_numeric_only(plugin, make_device):
    dev = make_device(11, "Remote", "z2mButton",
                      states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "2"})
    assert dev.states["lastButton"] == 2


def test_button_action_non_numeric_button_zero(plugin, make_device):
    """Actions without a numeric prefix (e.g. 'on', 'hold') get lastButton=0."""
    dev = make_device(12, "Remote", "z2mButton",
                      states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "hold"})
    assert dev.states["lastButton"]  == 0
    assert dev.states["lastAction"] == "hold"


@pytest.mark.parametrize("raw, expected", [
    ("1_single",            "single"),    # button-index prefix stripped
    ("single",              "single"),    # already clean
    ("2_double",            "double"),
    ("hold",                "hold"),
    ("release",             "release"),
    ("brightness_move_up",  "brightnessMoveUp"),  # compound -> camelCase
    ("3_brightness_step_up", "brightnessStepUp"),
    ("2",                   "other"),      # bare button number -> declared "other"
    ("",                    "other"),      # empty -> declared "other"
    ("recall_1",            "other"),      # exotic/unmapped token -> declared "other"
    ("arrow_left_click",    "arrowLeftClick"),  # multi-function remote now surfaces
])
def test_normalise_action(plugin, plugin_mod, raw, expected):
    """_normalise_action must yield a legal enum Option value: a declared token
    when recognised, else "other" (never a value the enum can't display)."""
    token = plugin._normalise_action(raw)
    assert token == expected
    # Whatever it returns must be a real declared Option so a sub-state can fire.
    assert token in plugin_mod._BUTTON_ACTION_VALUES


def test_button_compound_action_written_normalised(plugin, make_device):
    dev = make_device(17, "Dimmer", "z2mButton", states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "1_brightness_move_up"})
    assert dev.states["lastAction"] == "brightnessMoveUp"
    assert dev.states["lastButton"] == 1


def test_button_press_count_wraps_at_9999(plugin, make_device):
    dev = make_device(13, "Remote", "z2mButton",
                      states={"pressCount": 9999})
    plugin._process_button_state(dev, {"action": "1_single"})
    # 9999 % 9999 = 0, +1 = 1
    assert dev.states["pressCount"] == 1


def test_button_press_count_string_value_coerced(plugin, make_device):
    """Indigo may store the state as a string — int() must coerce."""
    dev = make_device(14, "Remote", "z2mButton",
                      states={"pressCount": "5"})
    plugin._process_button_state(dev, {"action": "1_single"})
    assert dev.states["pressCount"] == 6


def test_button_empty_action_ignored(plugin, make_device):
    """Empty/None action must not produce a press event."""
    dev = make_device(15, "Remote", "z2mButton",
                      states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": ""})
    plugin._process_button_state(dev, {"action": None})
    assert "lastAction" not in dev.states


def test_button_battery_in_action_payload(plugin, make_device):
    dev = make_device(16, "Remote", "z2mButton",
                      states={"pressCount": 0})
    plugin._process_button_state(dev, {"action": "1_single", "battery": 73})
    assert dev.states["battery"] == 73


# ── _process_repeater_state ──────────────────────────────────────────────────

def test_repeater_linkquality_only(plugin, make_device):
    """Repeaters update only linkQuality from payload — availability drives
    onOffState elsewhere."""
    dev = make_device(20, "Router", "z2mRepeater")
    plugin._process_repeater_state(dev, {"linkquality": 200})
    assert dev.states["linkQuality"] == 200
    # No onOffState write from payload
    onoff_writes = [w for w in dev.state_writes if w[0] == "onOffState"]
    assert onoff_writes == []


def test_repeater_bogus_linkquality_silent(plugin, make_device):
    dev = make_device(21, "Router", "z2mRepeater")
    plugin._process_repeater_state(dev, {"linkquality": "junk"})
    assert "linkQuality" not in dev.states


# ── _process_availability ────────────────────────────────────────────────────

def test_availability_online_offline(plugin, make_device):
    dev = make_device(30, "Door", "z2mContactSensor",
                      pluginProps={"friendly_name": "Door"})
    plugin.friendly_name_map[("zigbee2mqtt", "Door")] = 30

    plugin._process_availability("Door", {"state": "online"})
    assert dev.states["availability"] == "online"

    plugin._process_availability("Door", {"state": "offline"})
    assert dev.states["availability"] == "offline"


def test_availability_bare_string_payload(plugin, make_device):
    """Some Z2M versions send the bare string 'online' instead of a JSON dict."""
    dev = make_device(31, "Door", "z2mContactSensor",
                      pluginProps={"friendly_name": "Door"})
    plugin.friendly_name_map[("zigbee2mqtt", "Door")] = 31

    plugin._process_availability("Door", "online")
    assert dev.states["availability"] == "online"


def test_availability_repeater_mirrors_onoffstate(plugin, make_device):
    """Repeaters get onOffState = (state == 'online')."""
    dev = make_device(32, "Router", "z2mRepeater",
                      pluginProps={"friendly_name": "Router"})
    plugin.friendly_name_map[("zigbee2mqtt", "Router")] = 32

    plugin._process_availability("Router", {"state": "online"})
    assert dev.states["onOffState"] is True

    plugin._process_availability("Router", {"state": "offline"})
    assert dev.states["onOffState"] is False


def test_availability_unknown_device_silent(plugin):
    """Receiving availability for an unknown friendly_name must not raise."""
    plugin._process_availability("Mystery", {"state": "online"})


# ── _process_bridge_devices ──────────────────────────────────────────────────

def test_bridge_devices_caches_non_coordinator(plugin):
    """bridge/devices payload caches every non-coordinator, non-disabled device."""
    payload = [
        {"ieee_address": "0x111", "friendly_name": "Door",  "type": "Router"},
        {"ieee_address": "0x222", "friendly_name": "Lamp",  "type": "EndDevice"},
        {"ieee_address": "0x333", "friendly_name": "Coord", "type": "Coordinator"},
        {"ieee_address": "0x444", "friendly_name": "Off",   "disabled": True},
    ]
    plugin._process_bridge_devices(payload, prefix="zigbee2mqtt")
    assert "0x111" in plugin.bridge_devices
    assert "0x222" in plugin.bridge_devices
    assert "0x333" not in plugin.bridge_devices   # coordinator excluded
    assert "0x444" not in plugin.bridge_devices   # disabled excluded


def test_bridge_devices_preserves_other_prefix(plugin):
    """A bridge/devices update for one prefix must not clobber the cache
    for the other prefix."""
    # Seed with garage prefix entries
    plugin._process_bridge_devices([
        {"ieee_address": "0xaaa", "friendly_name": "Garage Door"},
    ], prefix="zigbee2mqtt_garage")

    # Then update primary prefix
    plugin._process_bridge_devices([
        {"ieee_address": "0xbbb", "friendly_name": "House Door"},
    ], prefix="zigbee2mqtt")

    assert "0xaaa" in plugin.bridge_devices
    assert "0xbbb" in plugin.bridge_devices
    assert plugin.bridge_devices["0xaaa"]["_mqtt_prefix"] == "zigbee2mqtt_garage"
    assert plugin.bridge_devices["0xbbb"]["_mqtt_prefix"] == "zigbee2mqtt"


def test_bridge_devices_non_list_payload_silent(plugin):
    """Malformed payload (e.g. dict) must NOT crash — silently skip."""
    plugin._process_bridge_devices({"not": "a list"}, prefix="zigbee2mqtt")
    plugin._process_bridge_devices(None, prefix="zigbee2mqtt")
    plugin._process_bridge_devices("string", prefix="zigbee2mqtt")
    # No exception is the assertion


# ── Auto-reclassify path (v1.9.9 bug fix) ────────────────────────────────────

def test_reclassify_calls_ensure_folder_with_name(plugin, make_device, monkeypatch):
    """v1.9.9 regression test: _reclassify_as_button used to call
    self._ensure_device_folder() with no argument, crashing with
    TypeError every time a device with folderId=0 was reclassified.
    Confirms the call now passes DEVICE_FOLDER_NAME."""
    # Track what arguments _ensure_device_folder is called with
    calls = []
    monkeypatch.setattr(plugin, "_ensure_device_folder",
                        lambda *args: calls.append(args) or 9999)

    dev = make_device(99, "MisidentifiedButton", "z2mRelay",
                      pluginProps={"friendly_name": "MisidentifiedButton",
                                   "ieee_address": "0xfff"})
    # Avoid the real indigo.device.delete / create calls — MONKEYPATCHED (not a
    # bare assignment, which permanently replaced indigo.device on the shared
    # stub module and leaked into every later test — fixed v1.9.22).
    delete_calls = []
    create_calls = []
    fake_delete = lambda d: delete_calls.append(d.id)
    fake_create = lambda **kw: (create_calls.append(kw) or
                                _StubNewDev(create_calls[-1]))
    monkeypatch.setattr(
        indigo, "device",
        type("X", (), {"delete": staticmethod(fake_delete),
                       "create": staticmethod(fake_create)})(),
        raising=False)
    # set folderId attribute via the stub
    dev.folderId = 0   # root-level — this is the bug-triggering case

    plugin._reclassify_as_button(dev, {"action": "1_single"})

    # The fix: _ensure_device_folder MUST have been called, with a name argument
    # (a hard assertion — `if calls:` used to pass vacuously when the call never
    # happened at all).
    assert calls, "_ensure_device_folder was never called for a folderId=0 device"
    assert calls[-1] != (), "_ensure_device_folder called with no arg (v1.9.8 bug)"
    assert calls[-1][0] is not None


# ── _should_reclassify_as_button gate (v1.9.15) ──────────────────────────────
# A non-button device that publishes an 'action' must only be deleted + recreated
# as a button if it has NO primary output capability — otherwise a real
# dimmer/cover/switch-with-scenes would be destroyed and its id orphaned.

def test_gate_protects_switch_with_writable_state(plugin, make_device):
    dev = make_device(601, "Switch+Scenes", "z2mRelay",
                      pluginProps={"friendly_name": "Switch+Scenes", "ieee_address": "0xd1"})
    plugin.bridge_devices = {"0xd1": {
        "ieee_address": "0xd1", "friendly_name": "Switch+Scenes",
        "definition": {"exposes": [
            {"name": "state", "type": "binary", "access": 7},   # writable on/off
            {"name": "action", "type": "enum"},
        ]},
    }}
    assert plugin._should_reclassify_as_button(dev) is False


def test_gate_allows_action_only_device(plugin, make_device):
    dev = make_device(602, "PureButton", "z2mSensor",
                      pluginProps={"friendly_name": "PureButton", "ieee_address": "0xb2"})
    plugin.bridge_devices = {"0xb2": {
        "ieee_address": "0xb2", "friendly_name": "PureButton",
        "definition": {"exposes": [
            {"name": "action", "type": "enum"},
            {"name": "battery", "type": "numeric"},
        ]},
    }}
    assert plugin._should_reclassify_as_button(dev) is True


def test_gate_protects_light_and_cover_types_outright(plugin, make_device):
    light = make_device(603, "ALight", "z2mLight",
                        pluginProps={"friendly_name": "ALight", "ieee_address": "0xl3"})
    cover = make_device(604, "ACover", "z2mCover",
                        pluginProps={"friendly_name": "ACover", "ieee_address": "0xc4"})
    plugin.bridge_devices = {}   # even with no cached exposes
    assert plugin._should_reclassify_as_button(light) is False
    assert plugin._should_reclassify_as_button(cover) is False


# ── Regression (v1.9.18): presence/occupancy sensors must NOT reclassify ──────
# An Aqara FP1 (RTCZCGQ11LM) and other mmWave/PIR presence sensors emit region /
# presence events as an `action` enum. They are created as z2mOccupancySensor and
# must NEVER be reclassified as a button — that would delete + recreate the device,
# changing its id and orphaning every trigger/link/control-page reference, and lose
# all presence semantics. The detection-time gate (v1.9.17) had not been mirrored
# into the runtime _should_reclassify_as_button guard; this locks both in step.

def test_gate_protects_presence_sensor_with_action(plugin, make_device):
    dev = make_device(605, "FP1 Presence", "z2mOccupancySensor",
                      pluginProps={"friendly_name": "FP1 Presence", "ieee_address": "0xfp1"})
    plugin.bridge_devices = {"0xfp1": {
        "ieee_address": "0xfp1", "friendly_name": "FP1 Presence",
        "definition": {"exposes": [
            {"name": "presence",        "type": "binary",  "access": 1},
            {"name": "action",          "type": "enum",    "access": 1,
             "values": ["region_1_enter", "enter", "leave"]},
            {"name": "illuminance_lux", "type": "numeric", "access": 1},
            {"name": "battery",         "type": "numeric", "access": 1},
        ]},
    }}
    assert plugin._should_reclassify_as_button(dev) is False


def test_gate_protects_occupancy_sensor_with_action(plugin, make_device):
    dev = make_device(606, "Occ+Action", "z2mOccupancySensor",
                      pluginProps={"friendly_name": "Occ+Action", "ieee_address": "0xocc"})
    plugin.bridge_devices = {"0xocc": {
        "ieee_address": "0xocc", "friendly_name": "Occ+Action",
        "definition": {"exposes": [
            {"name": "occupancy", "type": "binary", "access": 1},
            {"name": "action",    "type": "enum",   "access": 1, "values": ["enter"]},
        ]},
    }}
    assert plugin._should_reclassify_as_button(dev) is False


class _StubNewDev:
    def __init__(self, kw):
        self.id          = 1000
        self.name        = kw["name"]
        self.deviceTypeId = kw["deviceTypeId"]
        self.pluginProps = kw["props"]
        self.ownerProps  = kw["props"]
        self.states      = {}
        self.state_writes = []

    def updateStateOnServer(self, key, value, uiValue=None, **_):
        self.states[key] = value
        self.state_writes.append((key, value, uiValue))
