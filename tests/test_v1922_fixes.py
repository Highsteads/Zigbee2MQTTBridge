#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v1922_fixes.py
# Description: Regression tests for the v1.9.22 deep-review batch (Fable 5
#              review, 16-07-2026, mediums): prefix-qualified friendly_name
#              maps (cross-bridge name collisions), honest _publish/_publish_cmd
#              results, the two-stage liveness probe, configurable silence
#              limit, _hs_to_rgb 0-100 saturation, the _try_create_device
#              malformed-definition guard, tracked state-request timers, and
#              first-ever coverage for deviceStartComm's happy path,
#              didDeviceCommPropertyChange, _ensure_device_states gating and
#              refresh_device_capabilities.
# Author:      CliveS & Claude Fable 5
# Date:        16-07-2026
# Version:     1.0

import time


# ── prefix-qualified friendly_name maps (cross-bridge collisions) ─────────────

def test_same_name_on_two_bridges_routes_independently(plugin, make_device):
    house  = make_device(201, "House Door", "z2mContactSensor",
                         pluginProps={"friendly_name": "Door",
                                      "mqtt_prefix": "zigbee2mqtt"},
                         static_state_keys=["contact"])
    garage = make_device(202, "Garage Door", "z2mContactSensor",
                         pluginProps={"friendly_name": "Door",
                                      "mqtt_prefix": "zigbee2mqtt_garage"},
                         static_state_keys=["contact"])
    plugin.friendly_name_map[("zigbee2mqtt", "Door")]        = house.id
    plugin.friendly_name_map[("zigbee2mqtt_garage", "Door")] = garage.id

    plugin._process_device_state("Door", {"contact": False},
                                 prefix="zigbee2mqtt_garage")
    assert "contact" in garage.states
    assert garage.states["contact"] is False
    assert house.states == {}, "house device must not receive garage payloads"


def test_availability_is_prefix_qualified(plugin, make_device):
    house  = make_device(203, "House Door", "z2mContactSensor",
                         pluginProps={"friendly_name": "Door"})
    garage = make_device(204, "Garage Door", "z2mContactSensor",
                         pluginProps={"friendly_name": "Door",
                                      "mqtt_prefix": "zigbee2mqtt_garage"})
    plugin.friendly_name_map[("zigbee2mqtt", "Door")]        = house.id
    plugin.friendly_name_map[("zigbee2mqtt_garage", "Door")] = garage.id

    plugin._process_availability("Door", {"state": "offline"},
                                 prefix="zigbee2mqtt_garage")
    assert garage.states.get("availability") == "offline"
    assert "availability" not in house.states


def test_device_start_registers_prefix_qualified_key(plugin, make_device):
    dev = make_device(205, "Garage Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Sensor X",
                                   "ieee_address": "0xg1",
                                   "mqtt_prefix": "zigbee2mqtt_garage"})
    plugin.deviceStartComm(dev)
    assert plugin.friendly_name_map.get(
        ("zigbee2mqtt_garage", "Sensor X")) == dev.id
    assert plugin.ieee_map.get("0xg1") == dev.id
    plugin._cancel_state_request(dev.id)


def test_prefix_migration_moves_map_key_without_rename(plugin, make_device):
    dev = make_device(206, "Mover", "z2mSensor",
                      pluginProps={"friendly_name": "Mover",
                                   "ieee_address": "0xmv",
                                   "mqtt_prefix": "zigbee2mqtt"})
    plugin.ieee_map["0xmv"] = dev.id
    plugin.friendly_name_map[("zigbee2mqtt", "Mover")] = dev.id

    payload = [{"ieee_address": "0xmv", "friendly_name": "Mover",
                "type": "Router", "definition": {"exposes": []}}]
    plugin._process_bridge_devices(payload, prefix="zigbee2mqtt_garage")

    assert dev.pluginProps["mqtt_prefix"] == "zigbee2mqtt_garage"
    assert ("zigbee2mqtt", "Mover") not in plugin.friendly_name_map
    assert plugin.friendly_name_map.get(
        ("zigbee2mqtt_garage", "Mover")) == dev.id


def test_creation_not_blocked_by_same_name_on_other_prefix(plugin, make_device):
    import indigo
    from indigo_stub import DeviceShim
    existing = make_device(207, "House Button", "z2mButton",
                           pluginProps={"friendly_name": "Button",
                                        "mqtt_prefix": "zigbee2mqtt"})
    del existing  # only needs to exist in the registry
    names = plugin._get_existing_friendly_names()
    assert ("zigbee2mqtt", "Button") in names
    # A garage-bridge device with the SAME friendly name must not read as
    # 'exists' — pre-v1.9.22 the bare-name check blocked it forever.
    data = {"friendly_name": "Button", "type": "Router",
            "_mqtt_prefix": "zigbee2mqtt_garage",
            "definition": {"exposes": [
                {"name": "action", "type": "enum", "access": 1,
                 "values": ["single"]}]}}
    import pytest
    shim = DeviceShim(indigo.devices)
    old_device = getattr(indigo, "device", None)
    indigo.device = shim
    try:
        result = plugin._try_create_device(data, folder_id=1,
                                           existing_names=names)
    finally:
        indigo.device = old_device
    assert result == "created"
    created = [d for d in indigo.devices if d.pluginProps.get("mqtt_prefix")
               == "zigbee2mqtt_garage"]
    assert created and created[0].deviceTypeId == "z2mButton"
    for d in created:
        indigo.devices._by_id.pop(d.id, None)


# ── _try_create_device guard: one malformed definition costs only itself ──────

def test_malformed_definition_returns_error_not_raise(plugin):
    data = {"friendly_name": "Broken", "type": "Router",
            "_mqtt_prefix": "zigbee2mqtt",
            "definition": "not-a-dict"}     # .get() will raise AttributeError
    assert plugin._try_create_device(data, 1, set()) == "error"


def test_iter_features_skips_non_dict_entries(plugin_mod):
    exposes = [None, "junk", 42,
               {"name": "state", "type": "binary", "access": 7}]
    assert plugin_mod._detect_device_type(exposes) == "z2mRelay"


# ── honest _publish / _publish_cmd ────────────────────────────────────────────

def test_publish_returns_false_when_not_connected(plugin):
    plugin.mqtt_connected = False
    plugin.mqtt_client    = None
    assert plugin._publish("zigbee2mqtt/x/set", {"state": "ON"}) is False


class _FakeInfo:
    def __init__(self, rc): self.rc = rc


class _FakeClient:
    def __init__(self, rc=0):
        self._rc = rc
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return _FakeInfo(self._rc)


def test_publish_returns_true_on_success(plugin):
    plugin.mqtt_connected = True
    plugin.mqtt_client    = _FakeClient(rc=0)
    assert plugin._publish("zigbee2mqtt/x/set", {"state": "ON"}) is True


def test_publish_returns_false_on_bad_rc(plugin):
    plugin.mqtt_connected = True
    plugin.mqtt_client    = _FakeClient(rc=4)   # MQTT_ERR_NO_CONN
    assert plugin._publish("zigbee2mqtt/x/set", {"state": "ON"}) is False


def test_publish_cmd_logs_error_on_failure(plugin, make_device, plugin_mod,
                                            monkeypatch):
    logged = []
    monkeypatch.setattr(plugin_mod, "log",
                        lambda msg, level="INFO": logged.append((level, msg)))
    plugin.mqtt_connected = False
    plugin.mqtt_client    = None
    dev = make_device(210, "Dead Lamp", "z2mLight")
    ok = plugin._publish_cmd("zigbee2mqtt/Dead Lamp/set", {"state": "ON"},
                             dev, "on")
    assert ok is False
    assert any(level == "ERROR" and "Dead Lamp" in msg
               for level, msg in logged), "failure must name the device"
    assert not any("sent" in msg and level == "INFO"
                   for level, msg in logged), "must not claim 'sent'"


# ── two-stage liveness probe ──────────────────────────────────────────────────

def _arm_watchdog(plugin, silent_for):
    plugin.mqtt_client     = object()      # anything non-None
    plugin.mqtt_connected  = True
    plugin.last_rx_ts      = time.time() - silent_for
    plugin._last_mqtt_check = 0.0          # let the check run now


def test_watchdog_probes_before_rebuilding(plugin, monkeypatch):
    _arm_watchdog(plugin, silent_for=400)
    probes, rebuilds = [], []
    monkeypatch.setattr(plugin, "_publish",
                        lambda t, p: probes.append(t) or True)
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: rebuilds.append(1))

    plugin._mqtt_liveness_check()
    assert probes and probes[0].endswith("/bridge/request/devices")
    assert rebuilds == [], "first silent tick must probe, not rebuild"
    assert plugin._probe_sent_ts > 0


def test_watchdog_rebuilds_when_probe_unanswered(plugin, monkeypatch):
    _arm_watchdog(plugin, silent_for=400)
    plugin._probe_sent_ts  = time.time() - 30   # probe outstanding, no answer
    rebuilds = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: rebuilds.append(1))
    plugin._mqtt_liveness_check()
    assert rebuilds == [1]
    assert plugin._probe_sent_ts == 0.0


def test_watchdog_stands_down_when_probe_answered(plugin, monkeypatch):
    _arm_watchdog(plugin, silent_for=0)         # traffic flowing again
    plugin._probe_sent_ts = time.time() - 30
    rebuilds = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: rebuilds.append(1))
    plugin._mqtt_liveness_check()
    assert rebuilds == []
    assert plugin._probe_sent_ts == 0.0, "answered probe must clear"


def test_watchdog_rebuilds_immediately_if_client_says_disconnected(plugin, monkeypatch):
    _arm_watchdog(plugin, silent_for=400)
    monkeypatch.setattr(plugin, "_publish", lambda t, p: False)
    rebuilds = []
    monkeypatch.setattr(plugin, "_rebuild_mqtt", lambda: rebuilds.append(1))
    plugin._mqtt_liveness_check()
    assert rebuilds == [1]


def test_silence_limit_pref_guarded(plugin):
    assert plugin._silence_limit() == 300               # default
    plugin.pluginPrefs["mqtt_silence_limit"] = "600"
    assert plugin._silence_limit() == 600
    plugin.pluginPrefs["mqtt_silence_limit"] = "10"
    assert plugin._silence_limit() == 60                # floor
    plugin.pluginPrefs["mqtt_silence_limit"] = "gibberish"
    assert plugin._silence_limit() == 300               # guarded fallback


# ── _hs_to_rgb — z2m saturation is 0-100 ─────────────────────────────────────

def test_hs_full_saturation_at_100(plugin_mod):
    assert plugin_mod._hs_to_rgb(0, 100) == (100, 0, 0)      # pure red


def test_hs_half_saturation_at_50(plugin_mod):
    r, g, b = plugin_mod._hs_to_rgb(0, 50)
    assert r == 100
    assert g == b == 50, "sat=50 must be HALF saturation (old /255 gave ~80)"


def test_hs_overrange_saturation_clamped(plugin_mod):
    assert plugin_mod._hs_to_rgb(0, 255) == (100, 0, 0)      # clamped to 1.0


# ── deviceStartComm happy path (#23 — first coverage) ────────────────────────

def test_device_start_comm_happy_path(plugin, make_device, monkeypatch):
    scheduled = []
    monkeypatch.setattr(plugin, "_schedule_state_request",
                        lambda dev_id, fname, type_id, prefix, dev_props=None:
                        scheduled.append((dev_id, fname, type_id, prefix)))
    dev = make_device(220, "Lounge Contact", "z2mContactSensor",
                      pluginProps={"friendly_name": "Lounge Contact",
                                   "ieee_address": "0xcc1",
                                   "has_battery": True})
    plugin.deviceStartComm(dev)
    assert plugin.friendly_name_map[("zigbee2mqtt", "Lounge Contact")] == dev.id
    assert plugin.ieee_map["0xcc1"] == dev.id
    assert scheduled == [(dev.id, "Lounge Contact", "z2mContactSensor",
                          "zigbee2mqtt")]
    # _ensure_device_states seeded the universal + gated states
    assert "availability" in dev.states
    assert "battery" in dev.states


def test_device_start_comm_no_friendly_name_skips(plugin, make_device,
                                                  monkeypatch):
    scheduled = []
    monkeypatch.setattr(plugin, "_schedule_state_request",
                        lambda *a: scheduled.append(a))
    dev = make_device(221, "Anon", "z2mSensor", pluginProps={})
    plugin.deviceStartComm(dev)
    assert scheduled == []
    assert dev.id not in plugin.friendly_name_map.values()


def test_state_request_timer_tracked_and_cancelled(plugin, make_device):
    dev = make_device(222, "Timed", "z2mSensor",
                      pluginProps={"friendly_name": "Timed"})
    plugin._schedule_state_request(dev.id, "Timed", "z2mSensor", "zigbee2mqtt")
    t = plugin._state_request_timers.get(dev.id)
    assert t is not None and t.daemon
    plugin._cancel_state_request(dev.id)
    assert dev.id not in plugin._state_request_timers


# ── didDeviceCommPropertyChange contract (#24 — first coverage) ───────────────

def test_comm_property_change_contract(plugin_mod, make_device):
    old = make_device(230, "A", "z2mSensor",
                      pluginProps={"friendly_name": "A", "ieee_address": "0x1",
                                   "mqtt_prefix": "zigbee2mqtt",
                                   "capabilities_display": "x",
                                   "seenDynamicKeys": ""})
    fn = plugin_mod.Plugin.didDeviceCommPropertyChange

    def clone(**overrides):
        props = dict(old.pluginProps)
        props.update(overrides)
        from indigo_stub import FakeDevice
        return FakeDevice(id=230, name="A", deviceTypeId="z2mSensor",
                          pluginProps=props)

    # identity: nothing changed -> no comm cycle
    assert fn(old, clone()) is False
    # the three comm-relevant props DO cycle
    assert fn(old, clone(friendly_name="B")) is True
    assert fn(old, clone(ieee_address="0x2")) is True
    assert fn(old, clone(mqtt_prefix="zigbee2mqtt_garage")) is True
    # dynamic-state bookkeeping and cosmetic props must NOT cycle comm —
    # a regression here re-cycles every device on every dynamic capture
    assert fn(old, clone(seenDynamicKeys="a,b")) is False
    assert fn(old, clone(capabilities_display="y")) is False


# ── _ensure_device_states capability gating (#25 — first coverage) ────────────

def test_ensure_states_gates_on_capabilities(plugin, make_device):
    dev = make_device(240, "Smokey", "z2mSensor",
                      pluginProps={"friendly_name": "Smokey",
                                   "has_smoke": True,
                                   "has_battery": True,
                                   "has_temperature": False})
    plugin._ensure_device_states(dev)
    seeded = set(dev.states.keys())
    assert {"smoke", "battery", "availability", "linkQuality"} <= seeded
    assert "temperature" not in seeded, "ungated states must stay hidden"
    assert dev.states["smoke"] is False


def test_ensure_states_does_not_overwrite_existing(plugin, make_device):
    dev = make_device(241, "Live", "z2mSensor",
                      pluginProps={"friendly_name": "Live",
                                   "has_temperature": True},
                      states={"temperature": 21.5})
    plugin._ensure_device_states(dev)
    assert dev.states["temperature"] == 21.5


# ── refresh_device_capabilities (#26 — first coverage) ────────────────────────

def test_refresh_capabilities_heals_flags_from_cache(plugin, make_device):
    dev = make_device(250, "Healed Sensor", "z2mSensor",
                      pluginProps={"friendly_name": "Healed Sensor",
                                   "ieee_address": "0xh1",
                                   "has_temperature": False,
                                   "has_humidity": False})
    plugin.bridge_devices = {"0xh1": {
        "ieee_address": "0xh1", "friendly_name": "Healed Sensor",
        "_mqtt_prefix": "zigbee2mqtt",
        "definition": {"exposes": [
            {"name": "temperature", "type": "numeric", "access": 1},
            {"name": "humidity",    "type": "numeric", "access": 1},
        ]},
    }}
    plugin.refresh_device_capabilities()
    assert dev.pluginProps.get("has_temperature") is True
    assert dev.pluginProps.get("has_humidity") is True


def test_refresh_capabilities_fname_fallback_is_prefix_qualified(plugin, make_device):
    # No ieee on the Indigo device -> falls back to (prefix, fname); an entry
    # with the same name on the OTHER prefix must not match.
    dev = make_device(251, "NoIeee", "z2mSensor",
                      pluginProps={"friendly_name": "NoIeee",
                                   "mqtt_prefix": "zigbee2mqtt",
                                   "has_temperature": False})
    plugin.bridge_devices = {"0xz9": {
        "ieee_address": "0xz9", "friendly_name": "NoIeee",
        "_mqtt_prefix": "zigbee2mqtt_garage",
        "definition": {"exposes": [
            {"name": "temperature", "type": "numeric", "access": 1}]},
    }}
    plugin.refresh_device_capabilities()
    assert dev.pluginProps.get("has_temperature") is False, \
        "other-prefix cache entry must not heal this device"


# ── stub strictness (#22 — drift guard) ───────────────────────────────────────

def test_strict_stub_rejects_undeclared_state_write(plugin, make_device):
    import pytest
    dev = make_device(260, "Strict", "z2mContactSensor",
                      static_state_keys=["contact", "battery", "availability",
                                         "linkQuality"])
    dev.strict_states = True
    plugin._process_contact_sensor_state(dev, {"contact": True, "battery": 90,
                                               "linkquality": 60})
    assert dev.states["contact"] is True   # declared writes pass
    with pytest.raises(KeyError):
        dev.updateStateOnServer("neverDeclared", 1)
