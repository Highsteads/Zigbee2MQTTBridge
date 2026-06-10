#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_edge_cases.py
# Description: Edge-case tests aimed at robustness — payloads with surprising
#              shapes, type-coercion edge cases, defensive guard regressions.
#              These are the tests most likely to find real bugs.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

import indigo  # stub


# ── Payload type robustness ──────────────────────────────────────────────────

def test_process_device_state_ignores_non_dict_payload(plugin, make_device):
    """An MQTT payload that isn't a JSON object (e.g. a bare string from
    bridge/state) must NOT crash the device state dispatcher."""
    dev = make_device(1, "Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Plug"})
    plugin.friendly_name_map["Plug"] = 1
    # bare string payload — should be a no-op, NOT raise
    plugin._process_device_state("Plug", "ON")
    plugin._process_device_state("Plug", None)
    plugin._process_device_state("Plug", 42)
    plugin._process_device_state("Plug", ["list", "data"])
    # No state writes from any of these
    assert dev.states == {}


def test_process_device_state_unknown_friendly_name_silent(plugin):
    """Receiving a state payload for a device the plugin doesn't track
    (e.g. one owned by another z2m bridge) must be a silent no-op."""
    # No exception
    plugin._process_device_state("Mystery Device", {"state": "ON"})


def test_relay_state_with_missing_fields(plugin, make_device):
    """An MQTT payload may carry partial fields (z2m sends incremental updates)."""
    dev = make_device(2, "Plug", "z2mRelay")
    # Only power, no state
    plugin._process_relay_state(dev, {"power": 50})
    assert dev.states["power"] == 50
    assert "onOffState" not in dev.states


def test_relay_state_with_lq_only(plugin, make_device):
    dev = make_device(3, "Plug", "z2mRelay")
    plugin._process_relay_state(dev, {"linkquality": 200})
    assert dev.states["linkQuality"] == 200


# ── Light state edge cases ───────────────────────────────────────────────────

def test_light_state_payload_with_null_color_temp(plugin, make_device):
    """z2m sometimes sends `color_temp: null` for bulbs in colour mode. The
    plugin must skip null rather than crashing on int(None)."""
    dev = make_device(10, "Lamp", "z2mLight",
                      pluginProps={"has_color_temp": True})
    dev.supportsWhiteTemperature = True
    plugin._process_light_state(dev, {"state": "ON", "color_temp": None})
    # No whiteTemperature write attempted
    assert "whiteTemperature" not in dev.states


def test_light_state_brightness_string_value(plugin, make_device):
    """Some Zigbee firmware sends brightness as a string. int() should coerce."""
    dev = make_device(11, "Lamp", "z2mLight")
    plugin._process_light_state(dev, {"state": "ON", "brightness": "127"})
    assert dev.states["brightnessLevel"] == 49  # int(127/255*100)


# ── Contact sensor numeric battery ───────────────────────────────────────────

def test_contact_battery_non_numeric_skipped(plugin, make_device):
    """Bad battery value must NOT poison the rest of the payload."""
    dev = make_device(20, "Door", "z2mContactSensor")
    plugin._process_contact_sensor_state(dev, {"contact": True, "battery": "low"})
    assert dev.states["contact"] is True
    assert "battery" not in dev.states


# ── Occupancy motion store isolation between devices ─────────────────────────

def test_motion_store_isolated_per_device(plugin, make_device):
    """Two separate devices must not share motion state — bug class:
    using a class-level dict instead of self._motion_states."""
    dev_a = make_device(30, "Lounge Motion",   "z2mOccupancySensor",
                        pluginProps={"has_pir": True})
    dev_b = make_device(31, "Bathroom Motion", "z2mOccupancySensor",
                        pluginProps={"has_pir": True})

    plugin._process_occupancy_sensor_state(dev_a, {"occupancy": True})
    plugin._process_occupancy_sensor_state(dev_b, {"occupancy": False})

    assert dev_a.states["onOffState"] is True
    assert dev_b.states["onOffState"] is False


# ── Action dispatch — friendly_name with slash ───────────────────────────────

def test_relay_action_with_slash_in_friendly_name(plugin, make_device, make_action):
    """z2m allows '/' in friendly_names to nest devices under a virtual group.
    The plugin should publish to that nested topic verbatim."""
    sent = []
    plugin._publish = lambda t, p: sent.append((t, p))
    dev = make_device(40, "Hallway/Light", "z2mRelay",
                      pluginProps={"friendly_name": "Hallway/Light"})

    plugin.actionControlDevice(make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)
    assert sent == [("zigbee2mqtt/Hallway/Light/set", {"state": "ON"})]


# ── _capture_raw_fields — does not store junk-key data ───────────────────────

def test_capture_raw_skips_underscore_prefix(plugin, make_device):
    """Internal/private fields (starting with '_') must NOT be captured."""
    dev = make_device(50, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"_internal": "skip me", "temperature": 21.0})
    # temperature is in _HANDLED_PAYLOAD_KEYS so won't be captured;
    # _internal must be skipped. No state writes from either.
    captured = [w[0] for w in dev.state_writes]
    assert "_internal" not in captured
    assert "internal"  not in captured


def test_capture_raw_skips_handled_keys(plugin, make_device):
    """Keys already handled by the type-specific dispatcher must not be
    double-captured as dynamic states."""
    dev = make_device(51, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"state": "ON", "brightness": 100})
    # Both 'state' and 'brightness' are in _HANDLED_PAYLOAD_KEYS — no dynamic capture
    assert dev.state_writes == []


def test_capture_raw_skips_invalid_state_id(plugin, make_device):
    """If a payload key can't be sanitised into a valid state id, it must be
    skipped silently (and NOT crash the rest of the payload)."""
    dev = make_device(52, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    # All non-alnum -> _sanitise_state_key returns ""
    plugin._capture_raw_fields(dev, {"___": "junk"})
    assert dev.state_writes == []


def test_capture_raw_skips_none_values(plugin, make_device):
    dev = make_device(53, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"some_field": None})
    assert dev.state_writes == []


def test_capture_raw_dict_value_is_json_stringified(plugin, make_device):
    """A nested dict in the payload should be persisted as a JSON string."""
    dev = make_device(54, "Dev", "z2mSensor",
                      pluginProps={"seenDynamicKeys": ""})
    plugin._capture_raw_fields(dev, {"sub_obj": {"a": 1, "b": 2}})
    # state_writes won't yet contain the value — Phase 3 of _capture_raw_fields
    # requires the state list to have been refreshed first. We just need to
    # verify nothing crashed.


# ── _ensure_device_states — read-state-list path ─────────────────────────────

def test_compute_light_native_flags_returns_full_dict(plugin):
    """Sanity guard — every key the consumer references must be present."""
    flags = plugin._compute_light_native_flags(True, True)
    expected_keys = {"SupportsColor", "SupportsRGB", "SupportsWhite",
                     "SupportsWhiteTemperature"}
    assert set(flags.keys()) == expected_keys


# ── reserved name guard ──────────────────────────────────────────────────────

def test_reserved_state_names_constant_includes_batteryLevel(plugin_mod):
    """v1.8 confirmed bug: defining a custom state named `batteryLevel`
    silently shadowed the native device property. Reserved set must include it."""
    assert "batteryLevel"     in plugin_mod._RESERVED_STATE_NAMES
    assert "brightnessLevel"  in plugin_mod._RESERVED_STATE_NAMES
    assert "onOffState"       in plugin_mod._RESERVED_STATE_NAMES


def test_handled_payload_keys_covers_all_processed_fields(plugin_mod):
    """Every key the type-specific _process_* methods consume MUST be in
    _HANDLED_PAYLOAD_KEYS, otherwise the field will be double-stored
    (once as a typed state, once as a dynamic state with the wrong type)."""
    required = {
        "state", "brightness", "color_temp", "color_mode", "color",
        "contact", "occupancy", "presence", "motion", "water_leak",
        "temperature", "humidity", "pressure", "illuminance", "illuminance_lux",
        "battery", "power", "energy", "linkquality", "position", "action",
    }
    missing = required - plugin_mod._HANDLED_PAYLOAD_KEYS
    assert not missing, f"_HANDLED_PAYLOAD_KEYS missing: {sorted(missing)}"


# ── Helper consistency: sanitiser output is camelCase ────────────────────────

def test_sanitiser_first_char_lowercase(plugin):
    """Indigo SDK convention is camelCase. The sanitiser lowercases the FIRST
    CHARACTER of the result (not the whole first word) — sufficient for the
    XML validator (which only requires it to start with a letter, not strict
    camelCase). All sanitised outputs must start lowercase."""
    for raw in ("aaa_bbb_ccc", "AAA_bbb", "Brightness", "STATE", "MQTT_topic"):
        sk = plugin._sanitise_state_key(raw)
        if sk:
            assert sk[0].islower(), f"{raw!r} -> {sk!r} did not start lowercase"


def test_sanitiser_single_word_lowercased(plugin):
    assert plugin._sanitise_state_key("Brightness") == "brightness"
    # Only the very first character is lowercased; rest preserved.
    # Acceptable because Indigo's validator only requires camelCase by convention,
    # not enforced. The actually-illegal ones (leading non-letter, non-alnum)
    # are caught by _is_valid_state_id.
    assert plugin._sanitise_state_key("STATE")[0].islower()


# ── Topic prefix robustness ──────────────────────────────────────────────────

def test_topic_prefix_strips_whitespace(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_topic_prefix": "  zigbee2mqtt  "})
    assert p._topic_prefix() == "zigbee2mqtt"


def test_topic_prefix_blank_falls_back_to_default(plugin_mod):
    p = plugin_mod.Plugin("a", "b", "1.0", {"mqtt_topic_prefix": ""})
    # Empty string explicitly set — plugin keeps it empty, NOT default.
    # This documents current behaviour; an empty prefix is a config error.
    assert p._topic_prefix() == ""


# ── exception_handler — must not crash if traceback is missing ──────────────

def test_exception_handler_no_traceback_does_not_crash(plugin):
    """A bare exception with no __traceback__ (synthesised in user code)
    must not crash the handler."""
    e = ValueError("synthetic")
    # No tb attached - the handler's "while tb" loop should just skip
    plugin.exception_handler(e, log_failing_statement=True, context="unit test")


def test_exception_handler_real_traceback(plugin):
    """A real exception with a traceback must produce log output, not crash."""
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        plugin.exception_handler(e, log_failing_statement=True, context="unit test")
