#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v230_device_settings.py
# Description: Tests for managed device settings — pinning a firmware setting,
#              noticing when the device drifts off it, and re-applying.
#
#              The most important tests here are the refusals. A write-only
#              expose is a COMMAND, not a setting: `restart_device`,
#              `spatial_learning`, `identify`. Re-asserting one whenever a
#              device reconnected would reboot the sensor in a loop, so the
#              access-bitmask rule that excludes them is load-bearing and gets
#              tested from both directions.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0



# Real shapes, taken from the live PS-S04D (FP300) definition.
EXPOSES = [
    {"property": "ai_sensitivity_adaptive", "type": "binary", "access": 7,
     "label": "AI sensitivity adaptive"},
    {"property": "motion_sensitivity", "type": "enum", "access": 7,
     "values": ["low", "medium", "high"], "label": "Motion sensitivity"},
    {"property": "absence_delay_timer", "type": "numeric", "access": 7,
     "value_min": 1, "value_max": 300, "value_step": 1,
     "label": "Absence delay timer"},
    # Write-only COMMANDS — must never be managed or re-asserted.
    {"property": "restart_device", "type": "enum", "access": 2,
     "values": ["Restart Device"]},
    {"property": "spatial_learning", "type": "enum", "access": 2,
     "values": ["Start Learning"]},
    {"property": "detection_range_0", "type": "binary", "access": 2},
    # Read-only — nothing to set.
    {"property": "presence", "type": "binary", "access": 1},
]


def _sensor(make_device, dev_id=800, props=None, states=None):
    base = {"friendly_name": "Bedroom 1 Wall", "ieee_address": "0xfp300",
            "mqtt_prefix": "zigbee2mqtt"}
    base.update(props or {})
    return make_device(dev_id, "Bedroom 1 Wall Presence Sensor",
                       "z2mOccupancySensor", pluginProps=base,
                       states=states or {})


def _with_definition(plugin):
    plugin.bridge_devices["0xfp300"] = {
        "ieee_address": "0xfp300", "friendly_name": "Bedroom 1 Wall",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"model": "PS-S04D", "exposes": EXPOSES},
    }


def _sent(monkeypatch, plugin):
    out = []
    monkeypatch.setattr(plugin, "_publish",
                        lambda topic, payload: out.append((topic, payload)) or True)
    return out


# ── which exposes count as manageable settings ────────────────────────────────

def test_only_settable_and_readable_exposes_are_managed(plugin_mod):
    props = [s["property"] for s in
             plugin_mod.Plugin._iter_settable_exposes(EXPOSES)]
    assert props == ["ai_sensitivity_adaptive", "motion_sensitivity",
                     "absence_delay_timer"]


def test_write_only_commands_are_never_managed(plugin_mod):
    """restart_device and friends are commands wearing a setting's clothes.
    Managing one would reboot the sensor every time it reconnected."""
    props = [s["property"] for s in
             plugin_mod.Plugin._iter_settable_exposes(EXPOSES)]
    for command in ("restart_device", "spatial_learning", "detection_range_0"):
        assert command not in props


def test_read_only_exposes_are_not_managed(plugin_mod):
    props = [s["property"] for s in
             plugin_mod.Plugin._iter_settable_exposes(EXPOSES)]
    assert "presence" not in props


def test_composites_are_walked(plugin_mod):
    nested = [{"type": "composite", "features": [
        {"property": "inner_setting", "type": "numeric", "access": 7},
    ]}]
    props = [s["property"] for s in
             plugin_mod.Plugin._iter_settable_exposes(nested)]
    assert props == ["inner_setting"]


# ── coercion back out of the ConfigUI ─────────────────────────────────────────

def test_binary_coercion_handles_configui_strings(plugin_mod):
    coerce = plugin_mod.Plugin._coerce_setting
    spec = {"type": "binary"}
    assert coerce(spec, "false") is False
    assert coerce(spec, "true") is True
    assert coerce(spec, "") is None
    assert coerce(spec, "perhaps") is None


def test_numeric_coercion_respects_the_declared_range(plugin_mod):
    coerce = plugin_mod.Plugin._coerce_setting
    spec = {"type": "numeric", "value_min": 1, "value_max": 300}
    assert coerce(spec, "120") == 120
    assert coerce(spec, "0") is None, "below the device's minimum"
    assert coerce(spec, "301") is None, "above the device's maximum"
    assert coerce(spec, "abc") is None


def test_enum_coercion_publishes_the_exact_declared_token(plugin_mod):
    coerce = plugin_mod.Plugin._coerce_setting
    spec = {"type": "enum", "values": ["low", "medium", "high"]}
    assert coerce(spec, "HIGH") == "high", "matched loosely, published exactly"
    assert coerce(spec, "enormous") is None


# ── drift detection ───────────────────────────────────────────────────────────

def test_drift_is_detected_and_re_applied(plugin, make_device, monkeypatch):
    """The live case: adaptive sensitivity was set OFF and a battery change put
    it back ON, unnoticed for four weeks."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": True})
    assert len(sent) == 1
    topic, payload = sent[0]
    assert topic == "zigbee2mqtt/Bedroom 1 Wall/set"
    assert payload == {"ai_sensitivity_adaptive": False}


def test_agreement_sends_nothing(plugin, make_device, monkeypatch):
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": False})
    assert sent == []


def test_a_payload_silent_on_the_setting_sends_nothing(plugin, make_device,
                                                       monkeypatch):
    """Most payloads carry only a reading. Absence of the field is not drift."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"presence": True, "battery": 96})
    assert sent == []


def test_an_unmanaged_device_sends_nothing(plugin, make_device, monkeypatch):
    _with_definition(plugin)
    dev = _sensor(make_device)          # nothing pinned
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": True})
    assert sent == []


def test_a_cleared_field_stops_being_managed(plugin, make_device, monkeypatch):
    """Blank means 'no opinion', not 'pin it to blank'."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": ""})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": True})
    assert sent == []


def test_an_unusable_stored_value_is_never_published(plugin, make_device,
                                                     monkeypatch):
    """A stored value out of range publishes nothing rather than a guess."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_absence_delay_timer": "9999"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"absence_delay_timer": 10})
    assert sent == []


def test_several_drifted_settings_go_in_one_message(plugin, make_device,
                                                    monkeypatch):
    _with_definition(plugin)
    dev = _sensor(make_device, props={
        "z2mset_ai_sensitivity_adaptive": "false",
        "z2mset_motion_sensitivity": "high",
        "z2mset_absence_delay_timer": "120",
    })
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": True,
                                      "motion_sensitivity": "low",
                                      "absence_delay_timer": 10})
    assert len(sent) == 1, "one message, not three"
    assert sent[0][1] == {"ai_sensitivity_adaptive": False,
                          "motion_sensitivity": "high",
                          "absence_delay_timer": 120}


def test_a_pinned_command_would_never_be_re_asserted(plugin, make_device,
                                                     monkeypatch):
    """Even if a stale prop somehow pins a write-only command, the spec lookup
    must refuse it — this is the one that would reboot the sensor in a loop."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_restart_device": "Restart Device"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"restart_device": "idle"})
    assert sent == []


def test_a_setting_no_longer_offered_is_ignored(plugin, make_device, monkeypatch):
    """A firmware update can drop a setting. A stale pin must not be published
    to a device that no longer understands it."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_gone_away": "42"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"gone_away": 1})
    assert sent == []


def test_drift_needs_a_reported_value(plugin, make_device, monkeypatch):
    """A null reading is unknown, and unknown must never satisfy or trigger a
    comparison — the same rule as an absent device state."""
    _with_definition(plugin)
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": None})
    assert sent == []


# ── the generated config dialog ───────────────────────────────────────────────

def test_settings_fields_are_added_to_the_device_dialog(plugin, make_device):
    _with_definition(plugin)
    dev = _sensor(make_device, states={"aiSensitivityAdaptive": True})
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "z2mset_ai_sensitivity_adaptive" in xml
    assert "z2mset_motion_sensitivity" in xml
    assert "z2mset_absence_delay_timer" in xml
    assert xml.rstrip().endswith("</ConfigUI>")


def test_commands_get_no_field_in_the_dialog(plugin, make_device):
    _with_definition(plugin)
    dev = _sensor(make_device)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "z2mset_restart_device" not in xml
    assert "z2mset_spatial_learning" not in xml


def test_binary_settings_offer_a_not_managed_choice(plugin, make_device):
    """A checkbox has no third state, so it could not say 'not managed' and
    would pin every binary setting to Off the first time the dialog was saved."""
    _with_definition(plugin)
    dev = _sensor(make_device)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "-- not managed --" in xml
    assert 'id="z2mset_ai_sensitivity_adaptive" type="menu"' in xml


def test_enum_options_come_from_the_device_definition(plugin, make_device):
    _with_definition(plugin)
    dev = _sensor(make_device)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    for value in ("low", "medium", "high"):
        assert f'<Option value="{value}">' in xml


def test_a_device_with_no_definition_gets_the_plain_dialog(plugin, make_device):
    dev = _sensor(make_device)          # nothing in the bridge cache
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "z2mset_" not in xml


def test_a_broken_generator_still_returns_a_usable_dialog(plugin, make_device,
                                                          monkeypatch):
    """A device that cannot open its config dialog would be far worse than one
    without this section, so any failure falls back to the static XML."""
    _with_definition(plugin)
    dev = _sensor(make_device)

    def _boom(*_a, **_k):
        raise RuntimeError("generator fell over")

    monkeypatch.setattr(plugin, "_build_settings_fields", _boom)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    assert "</ConfigUI>" in xml
    assert "z2mset_" not in xml


def test_descriptions_are_xml_escaped(plugin, make_device):
    """A device description containing & or < would otherwise produce XML the
    client cannot parse, and the dialog would fail to open at all."""
    plugin.bridge_devices["0xfp300"] = {
        "ieee_address": "0xfp300", "friendly_name": "Bedroom 1 Wall",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": [
            {"property": "odd_one", "type": "numeric", "access": 7,
             "label": "Odd & <awkward>",
             "description": 'Uses "quotes" & <angle> brackets'},
        ]},
    }
    dev = _sensor(make_device)
    xml = plugin.getDeviceConfigUiXml("z2mOccupancySensor", dev.id)
    import xml.dom.minidom as minidom
    minidom.parseString(xml)     # raises if the escaping is wrong


# ── saving the dialog ─────────────────────────────────────────────────────────

def test_saving_publishes_only_what_changed(plugin, make_device, monkeypatch):
    _with_definition(plugin)
    dev = _sensor(make_device, states={"motionSensitivity": "high"})
    sent = _sent(monkeypatch, plugin)
    plugin.closedDeviceConfigUi(
        {"z2mset_motion_sensitivity": "high",        # already correct
         "z2mset_absence_delay_timer": "120"},       # new
        False, "z2mOccupancySensor", dev.id)
    assert len(sent) == 1
    assert sent[0][1] == {"absence_delay_timer": 120}


def test_cancelling_the_dialog_publishes_nothing(plugin, make_device, monkeypatch):
    _with_definition(plugin)
    dev = _sensor(make_device)
    sent = _sent(monkeypatch, plugin)
    plugin.closedDeviceConfigUi({"z2mset_absence_delay_timer": "120"},
                                True, "z2mOccupancySensor", dev.id)
    assert sent == []


def test_saving_an_invalid_value_warns_and_sends_nothing(plugin, make_device,
                                                         monkeypatch, helpers_mod):
    _with_definition(plugin)
    dev = _sensor(make_device)
    logged = []
    monkeypatch.setattr(helpers_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    sent = _sent(monkeypatch, plugin)
    plugin.closedDeviceConfigUi({"z2mset_absence_delay_timer": "9999"},
                                False, "z2mOccupancySensor", dev.id)
    assert sent == []
    assert any(lv == "WARNING" and "not valid" in m for lv, m in logged)


# ── binary tokens: the live shapes, which broke this once already ─────────────
#
# The FP300 publishes ai_sensitivity_adaptive as the STRINGS "ON"/"OFF" and
# led_disabled_night as REAL BOOLEANS — on the same device. The original tests
# used a binary with no value_on/value_off, which defaults to True/False, so
# they exercised the one shape that happened to work and the bug shipped.

BIN_TOKENS = {"property": "ai_sensitivity_adaptive", "type": "binary", "access": 7,
              "value_on": "ON", "value_off": "OFF"}
BIN_BOOLS  = {"property": "led_disabled_night", "type": "binary", "access": 7,
              "value_on": True, "value_off": False}


def test_string_token_binary_agrees_with_a_reported_bool(plugin_mod):
    """`bool("OFF")` is True, so naive truthiness made intent "OFF" and a
    reported False disagree for ever — republishing on every payload that
    mentioned the property. On a battery sensor that is a write storm."""
    agree = plugin_mod.Plugin._values_agree
    assert agree(BIN_TOKENS, "OFF", False) is True
    assert agree(BIN_TOKENS, "ON", True) is True
    assert agree(BIN_TOKENS, "OFF", True) is False
    assert agree(BIN_TOKENS, "ON", False) is False


def test_string_token_binary_agrees_with_a_reported_token(plugin_mod):
    agree = plugin_mod.Plugin._values_agree
    assert agree(BIN_TOKENS, "OFF", "OFF") is True
    assert agree(BIN_TOKENS, "OFF", "ON") is False


def test_boolean_binary_still_compares(plugin_mod):
    agree = plugin_mod.Plugin._values_agree
    assert agree(BIN_BOOLS, False, False) is True
    assert agree(BIN_BOOLS, True, False) is False


def test_an_uncomparable_binary_is_unknown_not_drift(plugin_mod):
    compare = plugin_mod.Plugin._compare_values
    assert compare(BIN_TOKENS, "OFF", "MAYBE") is None
    assert compare(BIN_TOKENS, "OFF", None) is None


def test_unknown_never_triggers_a_write(plugin, make_device, monkeypatch):
    """Only a DEFINITE difference is drift. Anything we cannot compare leaves
    the device alone rather than writing off a value we did not understand."""
    plugin.bridge_devices["0xfp300"] = {
        "ieee_address": "0xfp300", "friendly_name": "Bedroom 1 Wall",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": [BIN_TOKENS]},
    }
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": "MAYBE"})
    assert sent == []


def test_the_live_case_sends_nothing_when_already_correct(plugin, make_device,
                                                          monkeypatch):
    """The exact live shape: pinned OFF, device reporting False. This published
    on save and would have republished for ever."""
    plugin.bridge_devices["0xfp300"] = {
        "ieee_address": "0xfp300", "friendly_name": "Bedroom 1 Wall",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": [BIN_TOKENS]},
    }
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"},
                  states={"aiSensitivityAdaptive": False})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": False})
    assert sent == [], "already correct — nothing to send"
    # ...and the dialog save path, which is what actually fired live
    plugin.closedDeviceConfigUi({"z2mset_ai_sensitivity_adaptive": "false"},
                                False, "z2mOccupancySensor", dev.id)
    assert sent == [], "saving an already-correct value must not disturb the device"


def test_real_drift_on_a_token_binary_is_still_caught_and_sent_as_a_token(
        plugin, make_device, monkeypatch):
    """The fix must not blunt detection: a genuine change is still caught, and
    published using the device's OWN token rather than a Python bool."""
    plugin.bridge_devices["0xfp300"] = {
        "ieee_address": "0xfp300", "friendly_name": "Bedroom 1 Wall",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": [BIN_TOKENS]},
    }
    dev = _sensor(make_device, props={"z2mset_ai_sensitivity_adaptive": "false"})
    sent = _sent(monkeypatch, plugin)
    plugin._check_setting_drift(dev, {"ai_sensitivity_adaptive": True})
    assert sent == [("zigbee2mqtt/Bedroom 1 Wall/set",
                     {"ai_sensitivity_adaptive": "OFF"})]


def test_blank_settings_are_not_stored(plugin, make_device):
    """A generated dialog offers a field per settable expose — two dozen on an
    FP300 — and Indigo stores every one. Keeping the blanks buries the handful
    that mean something."""
    dev = _sensor(make_device, dev_id=810)
    ok, values = plugin.validateDeviceConfigUi(
        {"z2mset_ai_sensitivity_adaptive": "false",
         "z2mset_motion_sensitivity": "",
         "z2mset_absence_delay_timer": "   ",
         "friendly_name": "Bedroom 1 Wall"},
        "z2mOccupancySensor", dev.id)
    assert ok is True
    assert values == {"z2mset_ai_sensitivity_adaptive": "false",
                      "friendly_name": "Bedroom 1 Wall"}


def test_stripping_blanks_leaves_other_props_alone(plugin, make_device):
    dev = _sensor(make_device, dev_id=811)
    _, values = plugin.validateDeviceConfigUi(
        {"ieee_address": "", "z2mset_x": ""}, "z2mOccupancySensor", dev.id)
    assert "ieee_address" in values, "only pinned settings are stripped"
    assert "z2mset_x" not in values
