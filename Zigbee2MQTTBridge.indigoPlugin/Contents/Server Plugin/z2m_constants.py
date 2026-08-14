#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_constants.py
# Description: Plugin-wide constants: identity, timings, the declared lastAction
#              enum, the per-type handled-payload-key map, and the Indigo state
#              names that must never be used as dynamic state IDs.
#              Extracted from plugin.py in v2.2.0 — it had reached 5,238 lines
#              and every new feature made it worse. Behaviour is unchanged; the
#              names are re-exported from plugin.py so existing imports and the
#              test suite keep working.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

# ── Constants ─────────────────────────────────────────────────────────────────
PLUGIN_ID      = "com.clives.indigoplugin.z2mbridge"
PLUGIN_NAME    = "Zigbee2MQTT Bridge"
# Plugin version is read dynamically from Info.plist via self.pluginVersion;
# do NOT hardcode here — Info.plist is the single source of truth.

RECONNECT_DELAY      = 30   # seconds between MQTT reconnect attempts
# Application-level liveness backstop (paho's own auto-reconnect can wedge silently):
MQTT_SILENCE_LIMIT   = 300  # no inbound MQTT message for this long => rebuild the client
MQTT_WATCHDOG_EVERY  = 30   # seconds between liveness checks in runConcurrentThread
STATE_REQUEST_DELAY  = 2    # seconds after deviceStartComm before requesting state
DEVICE_FOLDER_NAME   = "Zigbee2MQTT"

# Declared lastAction enum Option values (must stay in sync with the z2mButton
# <State id="lastAction"> <List> in Devices.xml). _normalise_action maps any token
# NOT in this set to "other", so a multi-function remote's action always lands on a
# real Option (and fires its auto-generated lastAction.<value> bool sub-state)
# instead of writing a token the enum can't display — which silently vanished.
_BUTTON_ACTION_VALUES = frozenset({
    "single", "double", "triple", "quadruple", "hold", "release", "press",
    "on", "off", "toggle",
    "brightnessMoveUp", "brightnessMoveDown", "brightnessStop",
    "brightnessStepUp", "brightnessStepDown",
    "arrowLeftClick", "arrowRightClick", "arrowLeftHold", "arrowRightHold",
    "arrowLeftRelease", "arrowRightRelease",
    "colorTemperatureMoveUp", "colorTemperatureMoveDown",
    "moveUp", "moveDown", "upPress", "downPress", "upHold", "downHold",
    "other",
})

# MQTT payload keys consumed for EVERY device type (mesh/meta fields that either
# every handler writes semantically, or the plugin deliberately swallows).
# last_seen left this set in v1.10.0 — _capture_raw_fields transforms it into a
# human-readable `lastSeen` dynamic String state instead of swallowing it.
_ALWAYS_CONSUMED_KEYS = {
    "linkquality",                    # written as linkQuality by every handler
    "update_available", "update",     # OTA meta — deliberately not states
    "click",                          # legacy reclassification trigger only
}

# Payload keys each device type's _process_*_state handler ACTUALLY writes as
# named states. _capture_raw_fields skips these (plus _ALWAYS_CONSUMED_KEYS) for
# the device's own type and imports everything else as a typed dynamic state.
#
# v1.9.21: this replaces the old single global _HANDLED_PAYLOAD_KEYS set, which
# claimed keys NO handler wrote (smoke/vibration/tamper/voltage/current/
# battery_low) and claimed keys globally that only SOME types handle — so a
# smoke alarm, a contact sensor's temperature or a metering bulb's power was
# neither semantically handled NOR dynamically captured: silent total data loss.
_HANDLED_KEYS_BY_TYPE = {
    "z2mLight":             {"state", "brightness", "color_temp", "color_mode", "color"},
    "z2mRelay":             {"state", "power", "energy"},
    "z2mCover":             {"state", "position", "tilt"},
    "z2mButton":            {"action", "battery"},
    "z2mRepeater":          set(),
    "z2mContactSensor":     {"contact", "battery"},
    "z2mOccupancySensor":   {"motion", "occupancy", "presence", "pir", "illuminance",
                             "illuminance_lux", "temperature", "humidity", "battery"},
    "z2mWaterLeakSensor":   {"water_leak", "temperature", "battery"},
    "z2mTemperatureSensor": {"temperature", "humidity", "pressure", "illuminance",
                             "illuminance_lux", "battery"},
    "z2mSensor":            {"smoke", "water_leak", "motion", "occupancy", "presence",
                             "pir", "contact", "temperature", "humidity", "pressure",
                             "illuminance", "illuminance_lux", "battery"},
    "z2mLock":              {"state", "lock_state", "battery"},
    "z2mThermostat":        {"local_temperature", "current_heating_setpoint",
                             "occupied_heating_setpoint", "system_mode",
                             "running_state", "position", "battery"},
}

# Conservative fallback for any type not in the table (e.g. future types):
# the union of everything any handler writes — matches the old global set's
# behaviour minus the never-written keys.
_HANDLED_KEYS_FALLBACK = set().union(*_HANDLED_KEYS_BY_TYPE.values())


def _handled_keys_for(device_type_id):
    """Keys _capture_raw_fields must NOT import for this device type."""
    return _ALWAYS_CONSUMED_KEYS | _HANDLED_KEYS_BY_TYPE.get(
        device_type_id, _HANDLED_KEYS_FALLBACK)

# Indigo-reserved state names to avoid as dynamic state IDs (silently shadow
# native device properties — see global CLAUDE.md and feedback_indigo_state_visibility).
_RESERVED_STATE_NAMES = {
    "batteryLevel", "brightnessLevel", "onOffState", "sensorValue",
    "whiteTemperature", "redLevel", "greenLevel", "blueLevel",
    "coolerIsOn", "heaterIsOn", "hvacOperationMode", "temperatureInput1",
    "setpointHeat", "setpointCool",
}
