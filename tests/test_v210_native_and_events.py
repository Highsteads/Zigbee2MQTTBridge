#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v210_native_and_events.py
# Description: Tests for the v2.1.0 batch — Indigo's native battery and
#              energy-meter attributes, error state driven from zigbee2mqtt
#              availability, bridge/health ingestion, and the new custom
#              trigger events raised from bridge/event.
#
#              Several of these assert a NEGATIVE: an absent battery reading
#              must not become 0%, a cumulative counter must not raise an
#              event on its first sighting, and a retained bridge/state replay
#              must not announce an outage. Those are the cases that would
#              otherwise reach the house as false alerts.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import indigo  # stub
from indigo_stub import FakeTrigger


# ── native battery ────────────────────────────────────────────────────────────

def test_battery_write_enables_native_prop_and_populates(plugin, make_device):
    dev = make_device(700, "Hall Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Hall Sensor"})
    plugin._apply_updates(dev, [("battery", 87)])
    assert dev.pluginProps.get("SupportsBatteryLevel") is True
    assert dev.states.get("battery") == 87, "the custom state is still written"
    assert dev.states.get("batteryLevel") == 87, "and mirrored to the native one"


def test_native_battery_carries_a_percent_ui_value(plugin, make_device):
    dev = make_device(701, "Hall Sensor", "z2mSensor")
    plugin._apply_updates(dev, [("battery", 42)])
    ui = [w for w in dev.state_writes if w[0] == "batteryLevel"][-1][2]
    assert ui == "42%"


def test_absent_battery_never_becomes_zero(plugin, make_device):
    """None is 'no reading', not 'flat' — reporting 0 would be a false alert."""
    dev = make_device(702, "Quiet Sensor", "z2mSensor")
    plugin._apply_updates(dev, [("battery", None)])
    assert "batteryLevel" not in dev.states
    assert dev.pluginProps.get("SupportsBatteryLevel") is not True


def test_unparseable_battery_is_ignored(plugin, make_device):
    dev = make_device(703, "Odd Sensor", "z2mSensor")
    plugin._apply_updates(dev, [("battery", "not a number")])
    assert "batteryLevel" not in dev.states


def test_boolean_battery_is_ignored(plugin, make_device):
    """True would otherwise coerce to 1% and read as a nearly-flat cell."""
    dev = make_device(704, "Odd Sensor", "z2mSensor")
    plugin._apply_updates(dev, [("battery", True)])
    assert "batteryLevel" not in dev.states


def test_battery_percent_is_clamped(plugin_mod):
    coerce = plugin_mod.Plugin._coerce_battery_percent
    assert coerce(150) == 100
    assert coerce(-5) == 0
    assert coerce("88.6") == 89
    assert coerce(0) == 0, "a genuine zero is still a reading"


def test_backfill_populates_native_battery_at_startcomm(plugin, make_device):
    dev = make_device(705, "Old Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Old Sensor"},
                      states={"battery": 61})
    plugin._backfill_native_attributes(dev)
    assert dev.states.get("batteryLevel") == 61


def test_backfill_skips_a_stored_zero_battery(plugin, make_device):
    """_ensure_device_states seeds `battery` to 0, so 0 cannot be told apart
    from never-reported. Announcing a flat battery is the worse way to be
    wrong, so the backfill declines and waits for a real payload."""
    dev = make_device(706, "Never Reported", "z2mSensor",
                      states={"battery": 0})
    plugin._backfill_native_attributes(dev)
    assert "batteryLevel" not in dev.states


# ── native energy meter ───────────────────────────────────────────────────────

def test_power_and_energy_reach_the_native_attributes(plugin, make_device):
    dev = make_device(710, "Salus Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Salus Plug"})
    plugin._apply_updates(dev, [("power", 12.5), ("energy", 6.84)])
    assert dev.pluginProps.get("SupportsEnergyMeterCurPower") is True
    assert dev.pluginProps.get("SupportsEnergyMeter") is True
    assert dev.states.get("curEnergyLevel") == 12.5
    assert dev.states.get("accumEnergyTotal") == 6.84


def test_null_energy_after_a_z2m_restart_is_ignored(plugin, make_device):
    dev = make_device(711, "Salus Plug", "z2mRelay")
    plugin._apply_updates(dev, [("power", None), ("energy", None)])
    assert "curEnergyLevel" not in dev.states
    assert "accumEnergyTotal" not in dev.states


def test_energy_reset_rebases_against_the_device_counter(plugin, make_device,
                                                         make_action):
    """z2m's kWh counter lives on the device and cannot be reset from here, so
    a reset must store an offset — otherwise the next payload undoes it."""
    dev = make_device(712, "Salus Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Salus Plug"})
    plugin._apply_updates(dev, [("energy", 100.0)])
    assert dev.states.get("accumEnergyTotal") == 100.0

    plugin.actionControlUniversal(
        make_action(deviceAction=indigo.kUniversalAction.EnergyReset), dev)
    assert dev.states.get("accumEnergyTotal") == 0.0
    assert dev.pluginProps.get("energyResetOffset") == 100.0

    # The next payload must count from the reset point, not jump back to 100.
    plugin._apply_updates(dev, [("energy", 102.5)])
    assert dev.states.get("accumEnergyTotal") == 2.5


def test_energy_reset_without_a_reading_is_refused(plugin, make_device,
                                                   make_action):
    dev = make_device(713, "Silent Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Silent Plug"})
    plugin.actionControlUniversal(
        make_action(deviceAction=indigo.kUniversalAction.EnergyReset), dev)
    assert "energyResetOffset" not in dev.pluginProps


def test_device_counter_going_backwards_clears_the_offset(plugin, make_device):
    """A factory-reset plug restarts its own counter. Keeping the old offset
    would report a negative total for ever."""
    dev = make_device(714, "Salus Plug", "z2mRelay",
                      pluginProps={"friendly_name": "Salus Plug",
                                   "energyResetOffset": 100.0})
    plugin._apply_updates(dev, [("energy", 3.0)])
    assert dev.pluginProps.get("energyResetOffset") == 0.0
    assert dev.states.get("accumEnergyTotal") == 3.0


# ── error state from availability ─────────────────────────────────────────────

def _register(plugin, dev, fname, prefix="zigbee2mqtt"):
    plugin.friendly_name_map[(prefix, fname)] = dev.id


def test_offline_availability_sets_the_indigo_error_state(plugin, make_device):
    dev = make_device(720, "Shed Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Shed Sensor"})
    _register(plugin, dev, "Shed Sensor")
    plugin._process_availability("Shed Sensor", {"state": "offline"})
    assert dev.errorState == "offline"


def test_coming_back_online_clears_the_error_state(plugin, make_device):
    dev = make_device(721, "Shed Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Shed Sensor"})
    _register(plugin, dev, "Shed Sensor")
    plugin._process_availability("Shed Sensor", {"state": "offline"})
    plugin._process_availability("Shed Sensor", {"state": "online"})
    assert dev.errorState == ""


def test_repeated_offline_reports_set_the_error_state_once(plugin, make_device):
    dev = make_device(722, "Shed Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Shed Sensor"})
    _register(plugin, dev, "Shed Sensor")
    for _ in range(3):
        plugin._process_availability("Shed Sensor", {"state": "offline"})
    assert dev.error_writes == ["offline"]


def test_repeater_availability_still_drives_onoffstate(plugin, make_device):
    dev = make_device(723, "Hall Repeater", "z2mRepeater",
                      pluginProps={"friendly_name": "Hall Repeater"})
    _register(plugin, dev, "Hall Repeater")
    plugin._process_availability("Hall Repeater", {"state": "offline"})
    assert dev.states.get("onOffState") is False
    assert dev.errorState == "offline", \
        "the onOffState write must not clear the error set after it"


# ── bridge/health ─────────────────────────────────────────────────────────────

HEALTH = {
    "response_time": 1786726129574,
    "os":      {"load_average": [0.12, 0.08, 0.05], "memory_percent": 88.37},
    "process": {"uptime_sec": 1045872, "memory_used_mb": 114.06},
    "mqtt":    {"connected": True, "queued": 0, "published": 273162,
                "received": 941},
    "devices": {"0xaaa": {"messages": 6575, "messages_per_sec": 0.0063,
                          "leave_count": 0, "network_address_changes": 0}},
}


def _coordinator(plugin, make_device, prefix="zigbee2mqtt", dev_id=730):
    coord = make_device(dev_id, f"Bridge {prefix}", "z2mCoordinator",
                        pluginProps={"mqtt_prefix": prefix},
                        states={"healthOsMemoryPercent": 0.0,
                                "healthOsLoad1": 0.0,
                                "healthProcessMemoryMb": 0.0,
                                "healthProcessUptime": "",
                                "healthMqttQueued": 0,
                                "healthMqttPublished": 0,
                                "healthMqttReceived": 0,
                                "healthLastUpdate": "",
                                "lastEvent": "", "lastEventDevice": "",
                                "lastEventTime": "", "lastUpdate": "",
                                "status": ""})
    plugin.coordinator_map[prefix] = coord.id
    return coord


def test_health_populates_the_coordinator(plugin, make_device):
    coord = _coordinator(plugin, make_device)
    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")
    assert coord.states["healthOsMemoryPercent"] == 88.37
    assert coord.states["healthOsLoad1"] == 0.12
    assert coord.states["healthMqttPublished"] == 273162
    assert coord.states["healthProcessUptime"] == "12d 2h"


def test_health_writes_per_device_counters(plugin, make_device):
    _coordinator(plugin, make_device)
    dev = make_device(731, "Hall Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = dev.id
    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")
    assert dev.states["leaveCount"] == 0
    assert dev.states["networkAddressChanges"] == 0
    assert dev.states["messagesPerSec"] == 0.0063


def test_first_health_report_raises_no_events(plugin, make_device):
    """Counters are cumulative since zigbee2mqtt started. On the first report
    a non-zero value is history, and announcing it would fire every trigger in
    the house on plugin start."""
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    dev = make_device(732, "Flaky Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = dev.id
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceRejoined"))

    busy = {**HEALTH, "devices": {"0xaaa": {"messages_per_sec": 0.01,
                                            "leave_count": 9,
                                            "network_address_changes": 4}}}
    plugin._process_bridge_health(busy, "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_a_device_first_seen_mid_session_raises_nothing(plugin, make_device):
    """A device that joins after the plugin started arrives with a lifetime
    counter already on it. That is still not a rejoin we witnessed."""
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    known = make_device(735, "Known Sensor", "z2mSensor")
    newcomer = make_device(736, "New Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = known.id
    plugin.ieee_map["0xddd"] = newcomer.id
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceRejoined"))

    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")   # only 0xaaa present
    later = {**HEALTH, "devices": {
        **HEALTH["devices"],
        "0xddd": {"messages_per_sec": 0.02, "leave_count": 7,
                  "network_address_changes": 3},
    }}
    plugin._process_bridge_health(later, "zigbee2mqtt")
    assert indigo.trigger.executed == []
    assert newcomer.states["leaveCount"] == 7, \
        "the counter is still recorded — it just isn't announced"


def test_a_rise_in_leave_count_raises_the_rejoin_event(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    dev = make_device(733, "Flaky Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = dev.id
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceRejoined"))

    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")          # baseline
    risen = {**HEALTH, "devices": {"0xaaa": {"messages_per_sec": 0.01,
                                             "leave_count": 1,
                                             "network_address_changes": 0}}}
    plugin._process_bridge_health(risen, "zigbee2mqtt")
    assert [t.pluginTypeId for t in indigo.trigger.executed] == ["deviceRejoined"]


def test_an_unchanged_counter_raises_nothing(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    dev = make_device(734, "Steady Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = dev.id
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceRejoined"))
    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")
    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_a_counter_going_backwards_is_not_a_rejoin(plugin_mod):
    """zigbee2mqtt restarting zeroes its counters — that is not a rejoin."""
    rose = plugin_mod.Plugin._counter_rose
    assert rose(5, 6) is True
    assert rose(5, 5) is False
    assert rose(5, 0) is False
    assert rose(None, 3) is False, "unknown is never 'no change'"
    assert rose(3, None) is False


def test_health_with_an_unexpected_payload_is_survivable(plugin, make_device):
    _coordinator(plugin, make_device)
    plugin._process_bridge_health(["not", "a", "dict"], "zigbee2mqtt")
    plugin._process_bridge_health({}, "zigbee2mqtt")


def test_uptime_formatting(plugin_mod):
    fmt = plugin_mod.Plugin._format_uptime
    assert fmt(1045872) == "12d 2h"
    assert fmt(7500)    == "2h 5m"
    assert fmt(90)      == "1m"
    assert fmt(None)    == ""
    assert fmt("nope")  == ""


# ── bridge/event ──────────────────────────────────────────────────────────────

def test_device_joined_raises_the_matching_event(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceJoined"))
    plugin.triggerStartProcessing(FakeTrigger(2, "deviceLeft"))
    plugin._process_bridge_event(
        {"type": "device_joined",
         "data": {"friendly_name": "New Bulb", "ieee_address": "0xbbb"}},
        "zigbee2mqtt")
    assert [t.pluginTypeId for t in indigo.trigger.executed] == ["deviceJoined"]


def test_event_details_land_on_the_coordinator(plugin, make_device):
    """Plugin events carry no payload, so a trigger's actions read the details
    off the coordinator device instead."""
    coord = _coordinator(plugin, make_device)
    plugin._process_bridge_event(
        {"type": "device_leave", "data": {"friendly_name": "Old Bulb"}},
        "zigbee2mqtt")
    assert coord.states["lastEvent"] == "deviceLeft"
    assert coord.states["lastEventDevice"] == "Old Bulb"
    assert coord.states["lastEventTime"]


def test_failed_interview_raises_its_own_event(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceInterviewFailed"))
    plugin.triggerStartProcessing(FakeTrigger(2, "deviceInterviewSuccessful"))
    plugin._process_bridge_event(
        {"type": "device_interview",
         "data": {"friendly_name": "Awkward Bulb", "status": "failed"}},
        "zigbee2mqtt")
    assert [t.pluginTypeId for t in indigo.trigger.executed] == \
        ["deviceInterviewFailed"]


def test_interview_started_raises_nothing(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceInterviewFailed"))
    plugin._process_bridge_event(
        {"type": "device_interview",
         "data": {"friendly_name": "Awkward Bulb", "status": "started"}},
        "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_an_unknown_event_type_is_logged_not_raised(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "deviceJoined"))
    plugin._process_bridge_event(
        {"type": "device_teleported", "data": {"friendly_name": "X"}},
        "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_event_with_no_friendly_name_falls_back_to_ieee(plugin, make_device):
    coord = _coordinator(plugin, make_device)
    plugin._process_bridge_event(
        {"type": "device_joined", "data": {"ieee_address": "0xccc"}},
        "zigbee2mqtt")
    assert coord.states["lastEventDevice"] == "0xccc"


def test_a_stopped_trigger_no_longer_fires(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    trig = FakeTrigger(1, "deviceJoined")
    plugin.triggerStartProcessing(trig)
    plugin.triggerStopProcessing(trig)
    plugin._process_bridge_event(
        {"type": "device_joined", "data": {"friendly_name": "New Bulb"}},
        "zigbee2mqtt")
    assert indigo.trigger.executed == []


# ── bridge online / offline events ────────────────────────────────────────────

def test_first_bridge_state_does_not_announce(plugin, make_device):
    """bridge/state is retained, so it replays on every reconnect. Firing on
    arrival would announce an outage that never happened."""
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "bridgeOnline"))
    plugin.triggerStartProcessing(FakeTrigger(2, "bridgeOffline"))
    plugin._process_bridge_state({"state": "online"}, "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_bridge_going_offline_then_online_raises_both(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "bridgeOnline"))
    plugin.triggerStartProcessing(FakeTrigger(2, "bridgeOffline"))
    plugin._process_bridge_state({"state": "online"},  "zigbee2mqtt")
    plugin._process_bridge_state({"state": "offline"}, "zigbee2mqtt")
    plugin._process_bridge_state({"state": "online"},  "zigbee2mqtt")
    assert [t.pluginTypeId for t in indigo.trigger.executed] == \
        ["bridgeOffline", "bridgeOnline"]


def test_repeated_identical_bridge_state_is_quiet(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "bridgeOffline"))
    plugin._process_bridge_state({"state": "online"},  "zigbee2mqtt")
    for _ in range(4):
        plugin._process_bridge_state({"state": "online"}, "zigbee2mqtt")
    assert indigo.trigger.executed == []


def test_restart_required_raises_on_the_rising_edge_only(plugin, make_device):
    indigo.trigger.reset()
    _coordinator(plugin, make_device)
    plugin.triggerStartProcessing(FakeTrigger(1, "bridgeRestartRequired"))
    plugin._process_bridge_info({"restart_required": False}, "zigbee2mqtt")
    plugin._process_bridge_info({"restart_required": True},  "zigbee2mqtt")
    plugin._process_bridge_info({"restart_required": True},  "zigbee2mqtt")
    assert [t.pluginTypeId for t in indigo.trigger.executed] == \
        ["bridgeRestartRequired"]


# ── routing ───────────────────────────────────────────────────────────────────

def test_health_and_event_topics_are_routed(plugin, make_device, monkeypatch):
    seen = []
    monkeypatch.setattr(plugin, "_process_bridge_health",
                        lambda p, pre: seen.append(("health", pre)))
    monkeypatch.setattr(plugin, "_process_bridge_event",
                        lambda p, pre: seen.append(("event", pre)))
    plugin._process_message("zigbee2mqtt/bridge/health", {})
    plugin._process_message("zigbee2mqtt/bridge/event", {})
    assert seen == [("health", "zigbee2mqtt"), ("event", "zigbee2mqtt")]


# ── new-state registration on upgrade ─────────────────────────────────────────

def test_missing_new_states_trigger_a_state_list_refresh(plugin, make_device):
    """States added to Devices.xml do not exist on an already-created device
    until its cached state list is refreshed. Indigo refuses the write
    SERVER-side and only logs, so nothing raises and the state would silently
    never populate."""
    dev = make_device(740, "Old Sensor", "z2mSensor")
    calls = []
    dev.stateListOrDisplayStateIdChanged = lambda: calls.append("refreshed")
    plugin._refresh_state_list_if_missing(dev, ("leaveCount", "messagesPerSec"))
    assert calls == ["refreshed"]


def test_present_states_do_not_trigger_a_refresh(plugin, make_device):
    dev = make_device(741, "New Sensor", "z2mSensor",
                      states={"leaveCount": 0, "messagesPerSec": 0.0})
    calls = []
    dev.stateListOrDisplayStateIdChanged = lambda: calls.append("refreshed")
    plugin._refresh_state_list_if_missing(dev, ("leaveCount", "messagesPerSec"))
    assert calls == []


def test_a_failing_state_list_refresh_does_not_stop_startup(plugin, make_device):
    dev = make_device(742, "Awkward Sensor", "z2mSensor")

    def _boom():
        raise RuntimeError("server said no")

    dev.stateListOrDisplayStateIdChanged = _boom
    assert plugin._refresh_state_list_if_missing(dev, ("leaveCount",)) is dev


# ── network health report ─────────────────────────────────────────────────────

def test_health_report_says_so_when_there_is_no_data(plugin):
    plugin.report_network_health()
    lines = [m for _, m in indigo.server.log_lines]
    assert any("No health data yet" in m for m in lines)


def test_health_report_names_the_troublemakers(plugin, make_device):
    _coordinator(plugin, make_device)
    steady = make_device(750, "Steady Sensor", "z2mSensor")
    flaky = make_device(751, "Flaky Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = steady.id
    plugin.ieee_map["0xeee"] = flaky.id
    payload = {**HEALTH, "devices": {
        "0xaaa": {"messages_per_sec": 0.01, "leave_count": 0,
                  "network_address_changes": 0},
        "0xeee": {"messages_per_sec": 0.5, "leave_count": 12,
                  "network_address_changes": 4},
    }}
    plugin._process_bridge_health(payload, "zigbee2mqtt")

    indigo.server.log_lines.clear()
    plugin.report_network_health()
    lines = [m for _, m in indigo.server.log_lines]
    assert any("Flaky Sensor" in m and "12 rejoin" in m for m in lines)
    assert not any("Steady Sensor" in m for m in lines), \
        "a steady device is noise in a troubleshooting report"


def test_health_report_says_all_clear_when_nothing_is_flapping(plugin,
                                                               make_device):
    _coordinator(plugin, make_device)
    dev = make_device(752, "Steady Sensor", "z2mSensor")
    plugin.ieee_map["0xaaa"] = dev.id
    plugin._process_bridge_health(HEALTH, "zigbee2mqtt")

    indigo.server.log_lines.clear()
    plugin.report_network_health()
    lines = [m for _, m in indigo.server.log_lines]
    assert any("steady" in m for m in lines)
