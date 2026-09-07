#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_event_log_quiet.py
# Description: Guards the split between the shared Indigo Event Log and this
#              plugin's own log file. Routine narration -- command echoes,
#              status requests, device announcements, the MQTT connect steps --
#              belongs in the plugin's file; every WARNING and ERROR must keep
#              reaching the Event Log, because Log_Error_Watch.py reads the
#              Event Log and nothing else.
#
#              The plugin was writing about 100 Event Log lines a day and 82 of
#              them were command echoes (measured over the five days to
#              05-09-2026). Those grow with the size of the Zigbee network, so
#              the quiet is worth a test rather than worth remembering.
# Author:      CliveS & Claude Opus 5
# Date:        06-09-2026
# Version:     1.0

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conftest import SERVER_DIR


# --- Command echoes leave the Event Log but are NOT lost ---------------------

class _OkClient:
    """paho stand-in whose publish always succeeds."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return type("_Info", (), {"rc": 0})()


def _connected(plugin):
    plugin.mqtt_connected = True
    plugin.mqtt_client    = _OkClient()
    return plugin.mqtt_client


def test_command_echo_leaves_the_event_log(plugin, make_device, logs):
    _connected(plugin)
    dev = make_device(900, "Hall Lamp", "z2mLight")

    assert plugin._publish_cmd("zigbee2mqtt/Hall Lamp/set",
                               {"brightness": 102}, dev,
                               "set brightness to 40%") is True

    assert not logs.event_has("sent"), "the command echo must not reach the Event Log"
    assert logs.activity_has('sent "Hall Lamp" set brightness to 40%')


def test_command_echo_still_reaches_the_plugins_own_log(plugin, make_device, logs):
    """Redirected, not deleted. A DEBUG record goes to the plugin's own file
    handler (THREADDEBUG) and can never reach the Event Log handler (INFO)."""
    _connected(plugin)
    dev = make_device(901, "Hall Lamp", "z2mLight")

    plugin._publish_cmd("zigbee2mqtt/Hall Lamp/set", {"state": "ON"}, dev, "on")

    assert ("DEBUG", 'sent "Hall Lamp" on') in plugin.logger.records


def test_status_request_echo_leaves_the_event_log(plugin, make_device, make_action,
                                                  logs, monkeypatch):
    import indigo
    _connected(plugin)
    dev = make_device(902, "Back Door Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Back Door Sensor"})
    monkeypatch.setattr(plugin, "_request_state", lambda *a, **k: None)

    plugin.actionControlSensor(
        make_action(sensorAction=indigo.kSensorAction.RequestStatus), dev)

    assert not logs.event_has("status request")
    assert logs.activity_has('sent "Back Door Sensor" status request')


# --- Faults still reach the Event Log. This is the one that matters ----------

def test_failed_command_still_errors_to_the_event_log(plugin, make_device, logs):
    """A command that never reached the network is exactly what someone needs
    telling, and Log_Error_Watch.py only sees the Event Log."""
    plugin.mqtt_connected = False
    plugin.mqtt_client    = None
    dev = make_device(903, "Dead Lamp", "z2mLight")

    assert plugin._publish_cmd("zigbee2mqtt/Dead Lamp/set", {"state": "ON"},
                               dev, "on") is False

    assert logs.event_has("Dead Lamp", level="ERROR")
    assert not logs.activity_has("FAILED"), "a fault must not be filed as activity"


def test_unexpected_disconnect_still_warns_to_the_event_log(plugin, logs):
    plugin._process_message("__disconnected__", {"rc": 7, "reason": "socket closed"})
    assert logs.event_has("disconnected unexpectedly", level="WARNING")


def test_bridge_going_offline_still_warns_to_the_event_log(plugin, logs, monkeypatch):
    monkeypatch.setattr(plugin, "_fire_event", lambda *a, **k: None)
    plugin._process_bridge_state("online",  "zigbee2mqtt")   # arms the change test
    plugin._process_bridge_state("offline", "zigbee2mqtt")
    assert logs.event_has("went offline", level="WARNING")


def test_repeater_rejecting_a_command_still_warns(plugin, make_device, make_action, logs):
    import indigo
    dev = make_device(904, "Hall Repeater", "z2mRepeater",
                      pluginProps={"friendly_name": "Hall Repeater"})

    plugin.actionControlDevice(
        make_action(deviceAction=indigo.kDeviceAction.TurnOn), dev)

    assert logs.event_has("takes no on/off commands", level="WARNING")


# --- Genuine network changes stay; a device saying hello does not ------------

def test_device_joining_the_network_stays_in_the_event_log(plugin, logs, monkeypatch):
    monkeypatch.setattr(plugin, "_fire_event", lambda *a, **k: None)
    plugin._process_bridge_event(
        {"type": "device_joined", "data": {"friendly_name": "New Plug"}},
        "zigbee2mqtt")
    assert logs.event_has("'New Plug' joined the network")


def test_device_announcing_itself_leaves_the_event_log(plugin, logs, monkeypatch):
    """A device announces after a battery change, a power blip or a reboot.
    It happens unprompted and changes nothing about the network."""
    monkeypatch.setattr(plugin, "_fire_event", lambda *a, **k: None)
    plugin._process_bridge_event(
        {"type": "device_announce", "data": {"friendly_name": "Hall Lamp"}},
        "zigbee2mqtt")
    assert not logs.event_has("announced itself")
    assert logs.activity_has("'Hall Lamp' announced itself")


def test_startup_and_shutdown_do_not_double_indigos_own_lines(plugin, logs, monkeypatch):
    monkeypatch.setattr(plugin, "_start_mqtt", lambda *a, **k: None)
    monkeypatch.setattr(plugin, "_stop_mqtt",  lambda *a, **k: None)

    plugin.startup()
    plugin.shutdown()

    assert not logs.event_has("starting up")
    assert not logs.event_has("shutting down")
    assert logs.activity_has("starting up")
    assert logs.activity_has("shutting down")


# --- The opt-in preference --------------------------------------------------

def test_activity_is_off_by_default(plugin):
    assert plugin.log_activity_to_event_log is False


def test_pref_puts_the_narration_back_on_the_event_log(plugin, make_device, logs):
    plugin.log_activity_to_event_log = True
    _connected(plugin)
    dev = make_device(905, "Hall Lamp", "z2mLight")

    plugin._publish_cmd("zigbee2mqtt/Hall Lamp/set", {"state": "OFF"}, dev, "off")

    assert logs.event_has('sent "Hall Lamp" off')
    # Nothing is diverted when the user asks for it: it goes to BOTH.
    assert ("DEBUG", 'sent "Hall Lamp" off') in plugin.logger.records


@pytest.mark.parametrize("stored, expected", [
    (True,    True),
    (False,   False),
    ("true",  True),
    ("false", False),   # bool("false") is True -- the trap as_bool exists for
    ("",      False),
    (None,    False),
])
def test_pref_survives_indigos_re_serialisation(plugin_mod, stored, expected):
    p = plugin_mod.Plugin(
        pluginId          = "com.clives.indigoplugin.z2mbridge",
        pluginDisplayName = "Zigbee2MQTT Bridge",
        pluginVersion     = "test",
        pluginPrefs       = {"mqtt_topic_prefix": "zigbee2mqtt",
                             "logActivityToEventLog": stored},
    )
    assert p.log_activity_to_event_log is expected


def test_saving_the_dialog_updates_the_pref(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda *a, **k: None)

    plugin.closedPrefsConfigUi({"logActivityToEventLog": True}, False)
    assert plugin.log_activity_to_event_log is True

    plugin.closedPrefsConfigUi({"logActivityToEventLog": False}, False)
    assert plugin.log_activity_to_event_log is False


def test_cancelling_the_dialog_changes_nothing(plugin):
    plugin.log_activity_to_event_log = True
    plugin.closedPrefsConfigUi({"logActivityToEventLog": False}, True)
    assert plugin.log_activity_to_event_log is True


# --- Structural guard: a fault can never be filed as activity ----------------

def _bundle_sources():
    for path in sorted(Path(SERVER_DIR).glob("*.py")):
        if path.name in ("IndigoSecrets_example.py",):
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def test_log_activity_is_never_given_a_level():
    """log_activity() has no level: it is INFO-or-nothing by construction.

    Adding one would be the whole regression in a single keyword -- a WARNING
    routed through here would vanish from the Event Log, and Log_Error_Watch.py
    would never see the fault. Checked structurally because it is cheap and
    because nothing else would notice until something went wrong quietly.
    """
    calls = 0
    for path, tree in _bundle_sources():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "log_activity"):
                continue
            calls += 1
            assert not node.keywords, (
                f"{path.name}:{node.lineno} passes a keyword to log_activity")
            assert len(node.args) == 2, (
                f"{path.name}:{node.lineno} must be log_activity(self, message)")
    # A scan that matched nothing passes every assertion above it.
    assert calls >= 10, f"expected the activity call sites, found {calls}"


def _literal_text(node):
    """Every string constant inside a call, joined with a SPACE.

    A space, because joining bare constants lets the seam between two f-string
    pieces manufacture a match that neither half contains.
    """
    return " ".join(sub.value for sub in ast.walk(node)
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str))


def test_no_command_echo_is_left_on_the_event_log():
    """Catches the sites a behavioural test would have to reach one at a time.

    There are four 'sent "X" status request' lines (lock, relay, sensor,
    thermostat) and one 'sent "X" <verb>'; a mutation sweep found the lock
    branch had no test of its own. Structural, so a sixth added later is
    covered on the day it is written.
    """
    offenders, echoes = [], 0
    for path, tree in _bundle_sources():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if 'sent "' not in _literal_text(node):
                continue
            if node.func.id == "log_activity":
                echoes += 1
            elif node.func.id == "log":
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"command echoes still on the Event Log: {offenders}"
    assert echoes >= 5, f"expected the five command-echo sites, found {echoes}"


def test_every_warning_and_error_still_goes_through_log():
    """The counts are a tripwire, not a target. If a later change routes a
    fault away from log(), this notices before the estate's error watch stops
    seeing it."""
    warnings = errors = 0
    for _path, tree in _bundle_sources():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "log"):
                continue
            for kw in node.keywords:
                if kw.arg != "level" or not isinstance(kw.value, ast.Constant):
                    continue
                if kw.value.value == "WARNING":
                    warnings += 1
                elif kw.value.value == "ERROR":
                    errors += 1
    assert warnings >= 50, f"WARNING call sites dropped to {warnings}"
    assert errors   >= 20, f"ERROR call sites dropped to {errors}"


def _dialog_help_for(field_id):
    """The user-visible help for a setting, wherever it lives.

    A <Description> never wraps, so any prose longer than a phrase now sits in the
    companion `label_<id>_info` field beside the control (v2.8.1). These tests care
    about what the user READS, not which element carries it, so look in both.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(Path(SERVER_DIR) / "PluginConfig.xml").getroot()
    fields = {f.get("id"): f for f in root.iter("Field")}
    parts = []
    field = fields.get(field_id)
    if field is not None:
        parts.append(field.findtext("Description") or "")
    companion = fields.get(f"label_{field_id}_info")
    if companion is not None:
        parts.append(companion.findtext("Label") or "")
    return " ".join(p for p in parts if p).strip()


def test_the_pref_exists_in_the_config_dialog():
    """A pref the code reads and the dialog cannot set is a pref nobody has."""
    import xml.etree.ElementTree as ET

    root = ET.parse(Path(SERVER_DIR) / "PluginConfig.xml").getroot()
    fields = {f.get("id"): f for f in root.iter("Field")}
    field  = fields.get("logActivityToEventLog")

    assert field is not None, "no logActivityToEventLog field in PluginConfig.xml"
    assert field.get("type") == "checkbox"
    assert field.get("defaultValue") == "false", "the quiet behaviour is the default"
    assert _dialog_help_for("logActivityToEventLog"), \
        "say plainly what the checkbox does"


# --- The justification for the demotion must stay factually true -------------

def _docstring_of(filename, target):
    """Return the docstring of a top-level function or a method, by name.

    Reads the parsed docstring rather than the file text on purpose: a scan of
    raw source also matches a comment or changelog line that DESCRIBES the old
    wording, so it would fail on a correct file and could never be satisfied.
    """
    tree = ast.parse((Path(SERVER_DIR) / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target:
            return ast.get_docstring(node) or ""
    return None


# Checked against the live Indigo Event Log on 06-09-2026: on 04-09 the only
# lines naming a bulb this plugin switched were the plugin's own echo and the
# script that asked for it. Indigo contributes no state-change line of its own,
# so any justification resting on one is false -- and a comment asserting a
# fact about the system is evidence the next reader reasons from.
_FALSE_CLAIMS = (
    "already logs the device state change",
    "logs the resulting state change itself",
    "one line away",
)


@pytest.mark.parametrize("filename, target", [
    ("z2m_helpers.py", "log_activity"),
    ("z2m_mqtt.py",    "_publish_cmd"),
])
def test_demotion_rationale_does_not_claim_indigo_logs_state_changes(filename, target):
    doc = _docstring_of(filename, target)
    assert doc, f"no docstring found for {target} in {filename}"

    lowered = doc.lower()
    for claim in _FALSE_CLAIMS:
        assert claim not in lowered, (
            f"{filename}:{target} justifies the demotion with '{claim}', which is "
            "false -- Indigo logs no state change for this plugin's devices."
        )


@pytest.mark.parametrize("filename, target", [
    ("z2m_helpers.py", "log_activity"),
    ("z2m_mqtt.py",    "_publish_cmd"),
])
def test_demotion_rationale_says_the_echo_is_the_only_record(filename, target):
    """The true reason must be stated, not merely the false one removed.

    The echo is the sole record that a command went out, which is why it is
    redirected to the plugin's own log rather than dropped.
    """
    doc = (_docstring_of(filename, target) or "").lower()
    assert "only record" in doc or "sole record" in doc, (
        f"{filename}:{target} should say the echo is the only record that a "
        "command went out -- that is the reason it is kept at all."
    )


def test_the_checkbox_description_does_not_repeat_the_false_claim():
    """The dialog text is read by the user, so it has to be true as well."""
    import xml.etree.ElementTree as ET

    description = _dialog_help_for("logActivityToEventLog").lower()

    assert description, "the checkbox must explain itself"
    for claim in _FALSE_CLAIMS:
        assert claim not in description, (
            f"the checkbox help claims '{claim}', which is false."
        )
