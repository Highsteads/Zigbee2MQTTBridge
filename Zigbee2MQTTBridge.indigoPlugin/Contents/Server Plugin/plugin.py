#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Zigbee2MQTT Bridge — general zigbee2mqtt device integration for Indigo.
#              Auto-discovers all device types (lights, relays, sensors, covers) from
#              the zigbee2mqtt bridge and creates matching Indigo devices in a
#              "Zigbee2MQTT" device folder via Plugins > Discover & Create Devices.
# Author:      CliveS & Claude Opus 4.8
# Date:        06-06-2026
# Version:     1.9.15
# v1.9.15 (06-06-2026): deep-review fixes.
#   * HIGH: universal-action handler was named actionControlUniversalDevices — Indigo's
#     callback is actionControlUniversal (confirmed vs all SDK examples), so it was dead
#     code (everyday Send Status Request still worked via the class-specific handlers).
#     Renamed. (Global CLAUDE.md dispatch table corrected — it had the wrong name.)
#   * HIGH (script): startup_z2m_check.py Pushover used executeAction("sendMessage",
#     {title,message}) — wrong id + keys, so the watchdog's restart-failed alert never
#     sent. Fixed to "send" / msgTitle / msgBody / msgPriority / msgSound.
#   * MEDIUM (data-loss): _process_device_state reclassified ANY non-button device that
#     received an 'action' into a button — deleting + recreating it, destroying a real
#     dimmer/cover/switch-with-scenes and orphaning every trigger/link. New
#     _should_reclassify_as_button re-checks the device's CURRENT exposes and only
#     converts when there is no brightness/position/writable-state/light-cover-switch.
#   * MEDIUM: unguarded int()/float() in _process_light_state and the relay/cover
#     linkquality coercions dropped the WHOLE update batch on one malformed field; each
#     numeric block is now try/except-guarded (mirrors the contact/relay power handlers).
#
# v1.9.13 (28-05-2026): Dynamic state-type inference for captured z2m payload
# fields. Each dynamic key is tagged with a type token (bool/onoff/int/real/str)
# persisted in the new dynamicKeyTypes pluginProp, so getDeviceStateList declares
# it with the correct Indigo state type (BoolTrueFalse / BoolOnOff / Integer /
# Real / String) instead of declaring everything as String. The type is inferred
# when the raw value is in hand (in _capture_raw_fields) — getDeviceStateList
# runs at declaration time when dev.states is still None, so it reads the
# persisted token map rather than the (absent) value. Type drift (int then
# float) widens to Real; genuine disagreement falls back to String. Existing
# String states migrate to their proper type on the next payload that includes
# them. dynamicKeyTypes is excluded from didDeviceCommPropertyChange (cosmetic
# healing write, must not cycle comm). Reconciled from the stash that was parked
# alongside the v1.9.12 enum work so the two coexist cleanly.
#
# v1.9.12 (28-05-2026): z2mButton lastAction migrated from a plain String
# state to a List enumeration. Indigo now auto-generates per-value boolean
# sub-states (lastAction.single, lastAction.double, lastAction.hold, ...) so
# users can trigger on a specific action straight from the Triggers UI rather
# than writing an `if action == "double"` string compare. The raw z2m action
# is normalised before writing (the leading "<n>_" button-index prefix — kept
# separately in lastButton — is stripped and remaining underscore tokens are
# camelCased) so the value is a legal enum sub-state suffix: "1_single" ->
# "single", "brightness_move_up" -> "brightnessMoveUp". Existing button devices
# get a one-time stateListOrDisplayStateIdChanged() refresh in deviceStartComm.
#
# v1.9.14 (29-05-2026): Added an application-level MQTT liveness backstop. paho's
# loop_start auto-reconnect can wedge on a half-open socket after a network blip
# WITHOUT firing on_disconnect — leaving the client "connected" but deaf (this is
# what left Jane Lamp dead on 29-05-2026: "sent" published into a dead socket, zero
# inbound, lastSuccessfulComm frozen). runConcurrentThread now stamps last_rx_ts on
# every inbound message and rebuilds the client (_stop_mqtt + _start_mqtt) if nothing
# has arrived for MQTT_SILENCE_LIMIT (300s), independent of paho's own loop. Pairs
# with the estate-wide Device Health Monitor watchdog as defence-in-depth.
#
# v1.9.11 (27-05-2026): Added prepare_to_sleep / wake_up overrides
# harvested from the 27-May plugin_base.py sweep. Mac sleep used to leave
# Mosquitto holding our previous session as a stale ghost client until
# paho's keepalive fired (60s); on wake the bridge would just sit there
# until the Mac re-noticed the broker. Now MQTT disconnects cleanly on
# sleep, reconnects on wake.
#
# v1.9.9 (25-05-2026): Bug fix surfaced by new pytest suite —
# _reclassify_as_button used `self._ensure_device_folder()` with no
# argument, but the method requires `name`. Every reclassify of a
# device sitting at the root level (folderId=0) crashed with
# TypeError, leaving the device deleted but not recreated. Now passes
# DEVICE_FOLDER_NAME to match the other three call sites.
# Adds a ~226-test pytest suite under tests/ (no Indigo runtime needed)
# covering pure helpers, device-type detection, capability flags, state
# sanitiser, action dispatch (Dimmer/Sensor/Universal), state processing
# for every device class, MQTT topic routing, and bug-regression tests.
#
# v1.9.8 (25-05-2026): Added actionControlSensor() — sensor-class devices
# (z2mSensor, z2mContactSensor, z2mOccupancySensor, z2mWaterLeakSensor,
# z2mTemperatureSensor, z2mButton) had no handler, so any "Send Status
# Request" action against them logged
#   "plugin does not define method actionControlSensor"
# in the event log. New method handles indigo.kSensorAction.RequestStatus
# by re-publishing the z2m /get topic; all other sensor actions log a
# WARNING (sensors are read-only — no commands flow back to the network).
#
# v1.9.7 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. Module-level log() helper bumped to ms.
# New "Toggle Timestamps in Log" menu item.
#
# v1.9.5 (22-05-2026):
# - Refactor from code-review pass (no behaviour change):
#   * Extracted `_compute_light_native_flags(has_color, has_color_temp)`
#     @staticmethod — single source of truth for SupportsColor / SupportsRGB /
#     SupportsWhite / SupportsWhiteTemperature. Both _apply_light_capabilities
#     (deviceStartComm path) and refresh_device_capabilities (menu path) now
#     call this helper, eliminating the flip-flop risk noted in v1.9.3.
#   * Unified the two diff-detection loops in refresh_device_capabilities
#     into a single pass over a merged `target` dict.
#   * Moved `_build_capabilities_display` call inside the `if diffs:` guard —
#     skips ~50 string-format calls per menu invocation on no-op refreshes.
#   * Pruned the 14-line contradictory comment above the displayStateId guard
#     in deviceStartComm; investigation history stays in the v1.9.4 changelog.
#
# v1.9.4 (22-05-2026):
# - deviceStartComm now logs a WARNING when an existing device's cached
#   displayStateId disagrees with the current Devices.xml <UiDisplayStateId>.
#   For z2mButton (lastAction) and z2mTemperatureSensor (temperature) the XML
#   value was updated in v1.8.0, but Indigo caches displayStateId on the
#   device record at create time — it is a read-only attribute on existing
#   devices and stateListOrDisplayStateIdChanged() does NOT update it.
#   Confirmed: assignment raises "the attribute \"displayStateId\" is read-only
#   on this instance". The only fix for an existing device is delete +
#   recreate via Plugins -> Discover & Create Devices. The new
#   _EXPECTED_DISPLAY_STATE map drives the per-device check and a clear
#   user-facing warning that names the affected devices.
#
# v1.9.3 (22-05-2026):
# - "Refresh Device Capabilities" now sets SupportsColor / SupportsRGB /
#   SupportsWhite / SupportsWhiteTemperature on z2mLight using the SAME formula
#   as _apply_light_capabilities (SupportsColor = has_color OR has_color_temp,
#   because CT-only bulbs need it as the prereq for SupportsWhiteTemperature).
#   v1.9.2 used create-time logic (SupportsColor = has_color alone) and so
#   downgraded CT-only Hue White Ambiance bulbs on first refresh; the
#   subsequent deviceStartComm would then re-set them, causing a flip-flop.
#
# v1.9.2 (22-05-2026):
# - New menu item "Refresh Device Capabilities" — walks every existing Z2M
#   Indigo device, looks it up in self.bridge_devices by ieee_address (then
#   friendly_name as fallback), re-runs the per-type _detect_*_capabilities()
#   against the live exposes, and merges any has_* / capabilities_display
#   changes via replacePluginPropsOnServer. Then re-applies _apply_indigo_subtype
#   so the catch-all z2mSensor subType backfill runs after the flags update.
#   Logs per-device diffs. Idempotent. Fixes devices created before Z2M had
#   emitted a full exposes definition (e.g. Aqara FP1 presence sensors, contact
#   sensors with empty has_* flags but real state values).
#
# v1.9.1 (22-05-2026):
# - z2mSensor catch-all now gets a backfilled Indigo subType. Devices created
#   before the v1.8.0 specific sensor types existed (z2mContactSensor /
#   z2mOccupancySensor / z2mTemperatureSensor) stayed on z2mSensor and so got
#   no subType — meaning HomeKitLink-Siri, control pages and Indigo's UI all
#   treated them as generic. _apply_indigo_subtype() now infers the correct
#   subType from the device's stored capability flags (has_contact / has_occupancy
#   / has_temperature etc.): pure-contact → DoorWindow, pure-occupancy → Motion,
#   pure-environmental → Temperature. Mixed-capability sensors stay unset
#   (they ARE genuinely generic). Device IDs are preserved — no triggers or
#   control pages break, unlike a delete-and-recreate migration.
#
# v1.9.0 (22-05-2026):
# - New z2mCoordinator custom device representing the Z2M bridge itself
#   (one per MQTT prefix — supports multi-bridge setups like CliveS's
#   zigbee2mqtt + zigbee2mqtt_garage). States: status, version, coordinator,
#   permitJoin, permitJoinEnd, networkChannel, panId, extendedPanId,
#   deviceCount, restartRequired, logLevel, lastUpdate. Populated from
#   prefix/bridge/state and prefix/bridge/info MQTT topics. deviceCount is
#   kept fresh from the existing bridge/devices cache.
# - New menu item "Create Coordinator Devices" — auto-creates one device
#   per configured prefix (primary + garage). Idempotent.
# - _on_mqtt_message now passes bare-string payloads through (older Z2M
#   bridge/state publishes "online" without JSON quotes) instead of dropping.
#
# v1.8.0 (22-05-2026):
# - Indigo device subType applied to every device type (was 0 — confirmed gap
#   vs autolog Zigbee2mqtt Bridge).  Lights, relays, contacts, occupancy,
#   temperature sensors and covers now get the right SDK subType so
#   HomeKitLink-Siri, control pages and Indigo's UI render the right icon /
#   accessory kind.  Set statically in Devices.xml + dynamically in
#   _apply_indigo_subtype() (z2mLight → ColorDimmer vs Dimmer based on
#   has_color; also backfills devices created before 1.8.0).
# - UiDisplayStateId added to z2mTemperatureSensor (temperature) and z2mButton
#   (lastAction) so the device list shows the actually-useful state.
# - exception_handler() helper added — logs traceback PLUS the failing source
#   line and function name extracted from the deepest traceback frame.  Wired
#   into the high-traffic raw-field capture path and availability handler so
#   per-device failures finally name themselves.  Pattern lifted from autolog.
#
# v1.7.2 (13-05-2026):
# - Secrets import split into per-key try/except blocks. Previous single-line
#   `from IndigoSecrets import MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD`
#   would fail entirely if any one key was missing, blanking all four. Now
#   each key falls back independently per CLAUDE.md secrets policy.
#
# v1.7 (10-05-2026):
# - Show only the entities each device actually supports.  Pre-init of default
#   states is now filtered by the device's `has_*` capability flags instead of
#   blindly seeding every state from Devices.xml.  Per the Indigo state-visibility
#   rule (memory: feedback_indigo_state_visibility.md), states that are never
#   written do not appear in the Custom States panel — so unused states are now
#   hidden automatically.
# - Capture ALL Z2M data: any MQTT payload field not handled by the type-
#   specific dispatcher is now imported as a dynamic Indigo state.  First time a
#   field is seen for a device, the state list is refreshed via
#   stateListOrDisplayStateIdChanged() and the device's seen-fields union is
#   persisted in pluginProps so they survive restarts.  getDeviceStateList() is
#   overridden to advertise the dynamic states to Indigo's state machinery.
# - Reserved-state guard: dynamic state names are mangled to avoid colliding
#   with native or reserved Indigo state IDs (batteryLevel, brightnessLevel etc).

import colorsys
import json
import os as _os
import queue
import sys as _sys
import threading
import time
from datetime import datetime

# ── Startup banner + secrets ─────────────────────────────────────────────────
_sys.path.insert(0, _os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
# Per-key try/except so a single missing key doesn't blank all four
# (per CLAUDE.md secrets policy).
try:
    from IndigoSecrets import MQTT_BROKER
except ImportError:
    MQTT_BROKER = ""
try:
    from IndigoSecrets import MQTT_PORT
except ImportError:
    MQTT_PORT = 1883
try:
    from IndigoSecrets import MQTT_USERNAME
except ImportError:
    MQTT_USERNAME = ""
try:
    from IndigoSecrets import MQTT_PASSWORD
except ImportError:
    MQTT_PASSWORD = ""

import indigo  # noqa: E402  (Indigo injects this at runtime)

# ── paho-mqtt (installed by Indigo from requirements.txt) ────────────────────
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# ── colormath (XY → RGB conversion) ─────────────────────────────────────────
try:
    from colormath.color_objects import xyYColor, sRGBColor
    from colormath.color_conversions import convert_color
    COLORMATH_AVAILABLE = True
except ImportError:
    COLORMATH_AVAILABLE = False

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

# MQTT payload keys handled semantically by type-specific _process_*_state methods.
# Anything NOT in this set is captured as a dynamic state by _capture_raw_fields.
_HANDLED_PAYLOAD_KEYS = {
    # binary / state
    "state", "contact", "occupancy", "presence", "motion", "pir", "water_leak",
    "smoke", "vibration", "tamper",
    # light
    "brightness", "color_temp", "color_mode", "color",
    # numeric metering
    "power", "energy", "voltage", "current",
    # environmental (handled per-type)
    "temperature", "humidity", "pressure", "illuminance", "illuminance_lux",
    # cover
    "position", "tilt",
    # button
    "action",
    # battery / health (handled per-type)
    "battery", "battery_low",
    # mesh
    "linkquality", "last_seen", "update_available", "update",
    # reclassification trigger only — ignored for state writes
    "click",
}

# Indigo-reserved state names to avoid as dynamic state IDs (silently shadow
# native device properties — see global CLAUDE.md and feedback_indigo_state_visibility).
_RESERVED_STATE_NAMES = {
    "batteryLevel", "brightnessLevel", "onOffState", "sensorValue",
    "whiteTemperature", "redLevel", "greenLevel", "blueLevel",
    "coolerIsOn", "heaterIsOn", "hvacOperationMode", "temperatureInput1",
    "setpointHeat", "setpointCool",
}


# ── Pure helper functions (no Indigo dependency) ─────────────────────────────

def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=level)


def _xy_to_rgb(x, y):
    """Convert CIE 1931 xy chromaticity to sRGB 0-100 integers."""
    if COLORMATH_AVAILABLE:
        try:
            xyz = xyYColor(x, y, 1.0, observer="10")
            rgb = convert_color(xyz, sRGBColor)
            r = max(0.0, min(1.0, rgb.clamped_rgb_r))
            g = max(0.0, min(1.0, rgb.clamped_rgb_g))
            b = max(0.0, min(1.0, rgb.clamped_rgb_b))
            return int(r * 100), int(g * 100), int(b * 100)
        except Exception:
            pass
    # Fallback: simple matrix conversion without colormath
    z = 1.0 - x - y
    Y = 1.0
    X = (Y / y) * x if y > 0 else 0
    Z = (Y / y) * z if y > 0 else 0
    r =  X * 1.656492 - Y * 0.354851 - Z * 0.255038
    g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
    b =  X * 0.051713 - Y * 0.121364 + Z * 1.011530
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    return int(r * 100), int(g * 100), int(b * 100)


def _hs_to_rgb(hue_360, saturation_255):
    """Convert zigbee2mqtt hue (0-360) + saturation (0-255) to sRGB 0-100."""
    h = hue_360 / 360.0
    s = saturation_255 / 255.0
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    return int(r * 100), int(g * 100), int(b * 100)


def _brightness_255_to_100(val):
    """Convert MQTT brightness 0-255 to Indigo 0-100."""
    pct = int(val / 255 * 100)
    return 100 if pct >= 99 else pct


def _brightness_100_to_255(val):
    """Convert Indigo 0-100 to MQTT brightness 0-255 (range 1-254)."""
    return max(1, min(254, int(val * 2.55)))


def _kelvin_to_mireds(kelvin):
    """Convert Kelvin to mireds (zigbee2mqtt color_temp)."""
    return round(1_000_000 / max(1, kelvin))


def _mireds_to_kelvin(mireds):
    """Convert mireds to Kelvin."""
    return round(1_000_000 / max(1, mireds))


def _flatten_features(exposes):
    """
    Yield all leaf feature dicts from a zigbee2mqtt exposes list,
    recursively descending into 'features' arrays of composite types.
    """
    for entry in exposes:
        features = entry.get("features")
        if features:
            yield from _flatten_features(features)
        else:
            yield entry
    # Also yield the top-level composite entries themselves so callers can
    # check entry["type"] == "light" etc. without recursing into them first.
    # We do NOT yield composites here — callers iterate exposes directly for
    # composite-type detection; this helper is for leaf feature names only.


def _iter_features(exposes):
    """
    Yield (entry, is_top_level) for every item in exposes, plus recursively
    yield all nested features from any composite entries.
    """
    for entry in exposes:
        yield entry
        sub = entry.get("features", [])
        if sub:
            yield from _iter_features(sub)


def _detect_device_type(exposes, model=""):
    """
    Determine the best Indigo device type for a zigbee2mqtt device from its
    exposes list.  Priority: Repeater > Light > Cover > Relay > Sensor (default).

    Returns one of: "z2mLight", "z2mRelay", "z2mContactSensor", "z2mOccupancySensor",
                    "z2mWaterLeakSensor", "z2mTemperatureSensor", "z2mSensor",
                    "z2mCover", "z2mRepeater"
    """
    # Repeater: model name contains "repeater", or is a known coordinator/repeater
    # model that exposes a writable state (e.g. SMLIGHT SLZB series).
    _KNOWN_REPEATER_MODELS = {
        "ts0207_repeater",  # Tuya USB repeater
        "slzb-06p7",        # SMLIGHT Zigbee coordinator in repeater mode
        "slzb-06",          # SMLIGHT SLZB-06 coordinator/repeater
        "slzb-07",          # SMLIGHT SLZB-07
    }
    model_lower = model.lower() if model else ""
    if "repeater" in model_lower or model_lower in _KNOWN_REPEATER_MODELS:
        return "z2mRepeater"
    if exposes:
        feature_names = {feat.get("name") for feat in _iter_features(exposes)}
        if feature_names <= {"linkquality", "link_quality"} or not feature_names:
            return "z2mRepeater"

    if not exposes:
        return "z2mSensor"

    # Check for Light (composite type "light" OR nested "brightness" feature)
    for entry in exposes:
        if entry.get("type") == "light":
            return "z2mLight"
    # Also detect lights that expose "brightness" at any nesting level
    for feat in _iter_features(exposes):
        if feat.get("name") == "brightness" and feat.get("type") == "numeric":
            return "z2mLight"

    # Check for Cover (composite type "cover" or any "position" feature)
    for entry in exposes:
        if entry.get("type") == "cover":
            return "z2mCover"
    for feat in _iter_features(exposes):
        if feat.get("name") == "position":
            return "z2mCover"

    # Check for Button/Scene controller (has "action" enum feature — TuYa TS0042, Ikea remotes etc.)
    for feat in _iter_features(exposes):
        if feat.get("name") == "action" and feat.get("type") == "enum":
            return "z2mButton"

    # Check for Relay (writable binary "state" feature at top level or inside "switch" composite)
    for entry in exposes:
        if entry.get("type") == "switch":
            # switch composites always contain a writable state feature
            return "z2mRelay"
    for feat in _iter_features(exposes):
        if (feat.get("name") == "state"
                and feat.get("type") == "binary"
                and (feat.get("access", 0) & 2)):  # bit 1 = writable
            return "z2mRelay"

    # Distinguish sensor sub-types before falling back to generic sensor
    feature_names = {feat.get("name") for feat in _iter_features(exposes)}
    has_contact    = "contact"    in feature_names
    has_occupancy  = "occupancy"  in feature_names
    has_presence   = "presence"   in feature_names
    has_water_leak = "water_leak" in feature_names
    has_temp       = "temperature" in feature_names
    has_humidity   = "humidity"    in feature_names
    has_pressure   = "pressure"    in feature_names
    has_illuminance = any(n in feature_names for n in ("illuminance", "illuminance_lux"))

    # Pure contact sensor: has contact, no occupancy/presence/water_leak
    if has_contact and not has_occupancy and not has_presence and not has_water_leak:
        return "z2mContactSensor"

    # Occupancy/presence sensor: has occupancy or presence, no contact
    if (has_occupancy or has_presence) and not has_contact:
        return "z2mOccupancySensor"

    # Water leak sensor: has water_leak, no contact/occupancy
    if has_water_leak and not has_contact and not has_occupancy and not has_presence:
        return "z2mWaterLeakSensor"

    # Environmental sensor: temperature/humidity/pressure/illuminance, no binary alarms
    has_env = has_temp or has_humidity or has_pressure or has_illuminance
    if has_env and not has_contact and not has_occupancy and not has_presence and not has_water_leak:
        return "z2mTemperatureSensor"

    # Default: generic catch-all (mixed capabilities or unknown)
    return "z2mSensor"


def _detect_light_capabilities(exposes):
    """Return dict of capability flags for a z2mLight device."""
    has_color_temp = False
    has_color      = False
    for feat in _iter_features(exposes):
        name = feat.get("name", "")
        if name == "color_temp":
            has_color_temp = True
        elif name in ("color_xy", "color_hs", "color"):
            has_color = True
    return {
        "has_brightness":  True,
        "has_color_temp":  has_color_temp,
        "has_color":       has_color,
    }


def _detect_contact_sensor_capabilities(exposes):
    """Return capability flags for a z2mContactSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery": "battery" in names,
    }


def _detect_occupancy_sensor_capabilities(exposes):
    """Return capability flags for a z2mOccupancySensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":      "battery"      in names,
        "has_pir":          "occupancy"    in names,
        "has_presence":     "presence"     in names,
        "has_illuminance":  any(n in names for n in ("illuminance", "illuminance_lux")),
        "has_temperature":  "temperature"  in names,
        "has_humidity":     "humidity"     in names,
    }


def _detect_water_leak_sensor_capabilities(exposes):
    """Return capability flags for a z2mWaterLeakSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":     "battery"     in names,
        "has_temperature": "temperature" in names,  # some leak sensors also report temp
    }


def _detect_temperature_sensor_capabilities(exposes):
    """Return capability flags for a z2mTemperatureSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":     "battery"     in names,
        "has_temperature": "temperature" in names,
        "has_humidity":    "humidity"    in names,
        "has_pressure":    "pressure"    in names,
        "has_illuminance": any(n in names for n in ("illuminance", "illuminance_lux")),
    }


def _detect_sensor_capabilities(exposes):
    """Return capability flags for a generic z2mSensor device (catch-all)."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_temperature":  "temperature"  in names,
        "has_humidity":     "humidity"     in names,
        "has_contact":      "contact"      in names,
        "has_occupancy":    ("occupancy" in names or "presence" in names or "motion" in names),
        "has_water_leak":   "water_leak"   in names,
        "has_battery":      "battery"      in names,
        "has_pressure":     "pressure"     in names,
        "has_illuminance":  any(n in names for n in ("illuminance", "illuminance_lux")),
    }


def _detect_relay_capabilities(exposes):
    """Return dict of relay capability flags for a z2mRelay device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_power":  "power"  in names,
        "has_energy": "energy" in names,
    }


def _build_capabilities_display(device_type_id, caps):
    """Build a human-readable capabilities string for the device ConfigUI."""
    parts = []
    if device_type_id == "z2mLight":
        parts.append("on/off")
        if caps.get("has_brightness"):
            parts.append("brightness")
        if caps.get("has_color_temp"):
            parts.append("color temp")
        if caps.get("has_color"):
            parts.append("full color")
    elif device_type_id == "z2mRelay":
        parts.append("on/off")
        if caps.get("has_power"):
            parts.append("power (W)")
        if caps.get("has_energy"):
            parts.append("energy (kWh)")
    elif device_type_id == "z2mContactSensor":
        parts.append("contact (open/closed)")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mOccupancySensor":
        parts.append("occupancy/presence")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mWaterLeakSensor":
        parts.append("water leak")
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mTemperatureSensor":
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_pressure"):
            parts.append("pressure")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_battery"):
            parts.append("battery")
        if not parts:
            parts.append("environmental sensor")
    elif device_type_id == "z2mSensor":
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_contact"):
            parts.append("contact")
        if caps.get("has_occupancy"):
            parts.append("motion/occupancy")
        if caps.get("has_water_leak"):
            parts.append("water leak")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_pressure"):
            parts.append("pressure")
        if caps.get("has_battery"):
            parts.append("battery")
        if not parts:
            parts.append("generic sensor")
    elif device_type_id == "z2mRepeater":
        parts.append("repeater / router")
    elif device_type_id == "z2mCover":
        parts.append("position (0-100)")
        if caps.get("has_tilt"):
            parts.append("tilt")
    elif device_type_id == "z2mButton":
        parts.append("button actions")
        if caps.get("has_battery"):
            parts.append("battery")
    return ", ".join(parts) if parts else device_type_id


# ── Plugin ────────────────────────────────────────────────────────────────────

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.pluginId          = pluginId
        self.pluginDisplayName = pluginDisplayName
        self.pluginVersion     = pluginVersion

        self.timestamp_enabled = bool(pluginPrefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        self.debug = pluginPrefs.get("showDebugInfo", False)

        # MQTT state
        self.mqtt_client    = None
        self.mqtt_connected = False
        self.mqtt_lock      = threading.Lock()

        # Message queue (paho callback -> main thread via runConcurrentThread)
        self.msg_queue = queue.Queue()

        # MQTT liveness backstop — stamp of last inbound message + last watchdog check.
        self.last_rx_ts       = time.time()
        self._last_mqtt_check = 0.0

        # bridge/devices cache: ieee_address -> full device dict
        self.bridge_devices = {}     # type: dict[str, dict]

        # Active Indigo devices: friendly_name -> indigo device id
        self.friendly_name_map = {}  # type: dict[str, int]

        # Active Indigo devices: ieee_address -> indigo device id
        # Used for O(1) rename detection when Z2M changes a friendly_name
        self.ieee_map = {}  # type: dict[str, int]

        # Tracks which non-primary prefixes have produced at least one MQTT message.
        # Used for diagnostic logging — fires once per prefix per session.
        self._seen_prefixes = set()  # type: set[str]

        # Coordinator devices: mqtt_prefix -> indigo device id (one per Z2M bridge)
        self.coordinator_map = {}  # type: dict[str, int]

        # Latest bridge/info payload per prefix (cached so menu items / refresh can
        # re-populate states without round-tripping MQTT).
        self._bridge_info_cache = {}  # type: dict[str, dict]

        # Latest bridge/state per prefix — cached because the retained MQTT message
        # may arrive before any coordinator device exists.  Replayed on
        # deviceStartComm so the freshly created device picks up online/offline.
        self._bridge_state_cache = {}  # type: dict[str, str]

        # Per-device motion component states for occupancy sensors.
        # Stores last known bool for each motion-related key the device has ever sent
        # (motion, occupancy, presence, pir, ...).  Partial payloads only update the
        # keys they contain, so the OR across all stored values is always correct.
        self._motion_states = {}  # type: dict[int, dict[str, bool]]

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def startup(self):
        log(f"{PLUGIN_NAME} starting up")
        self._start_mqtt()

    def shutdown(self):
        log(f"{PLUGIN_NAME} shutting down")
        self._stop_mqtt()

    # ── Mac sleep / wake — disconnect MQTT cleanly on sleep so Mosquitto
    # ── doesn't hold the previous session as a stale ghost client. On wake
    # ── reconnect; retained messages will reseed device state.
    def prepare_to_sleep(self):
        log("Mac going to sleep — disconnecting from Mosquitto cleanly")
        self._stop_mqtt()
        super().prepare_to_sleep()
    prepareToSleep = prepare_to_sleep

    def wake_up(self):
        log("Mac woke — reconnecting to Mosquitto")
        super().wake_up()
        self._start_mqtt()
    wakeUp = wake_up

    def runConcurrentThread(self):
        """Drain the MQTT message queue on the Indigo main thread."""
        while True:
            try:
                while not self.msg_queue.empty():
                    topic, payload = self.msg_queue.get_nowait()
                    self._process_message(topic, payload)
            except Exception as e:
                log(f"runConcurrentThread error: {e}", level="ERROR")
            self._mqtt_liveness_check()
            self.sleep(0.2)

    def stopConcurrentThread(self):
        self.stopThread = True

    # ── Plugin preferences ────────────────────────────────────────────────────

    def validatePrefsConfigUi(self, valuesDict):
        errors = indigo.Dict()
        prefix = valuesDict.get("mqtt_topic_prefix", "").strip()
        if not prefix:
            errors["mqtt_topic_prefix"] = "Topic prefix is required."
        return (len(errors) == 0), valuesDict, errors

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.debug = valuesDict.get("showDebugInfo", False)
            log("Preferences saved — reconnecting MQTT")
            self._stop_mqtt()
            self.sleep(1)
            self._start_mqtt()

    # ── Device lifecycle ──────────────────────────────────────────────────────

    def deviceStartComm(self, dev):
        # Coordinator devices have no friendly_name — they're indexed by mqtt_prefix
        if dev.deviceTypeId == "z2mCoordinator":
            prefix = dev.pluginProps.get("mqtt_prefix", "").strip()
            if not prefix:
                log(f"Coordinator '{dev.name}' has no mqtt_prefix — skipping",
                    level="WARNING")
                return
            self.coordinator_map[prefix] = dev.id
            self._ensure_device_states(dev)
            # If we already have a cached bridge/info or bridge/state for this
            # prefix (retained MQTT may have arrived before this device existed),
            # push them now so the device populates immediately.
            cached_info = self._bridge_info_cache.get(prefix)
            if cached_info:
                self._process_bridge_info(cached_info, prefix)
            cached_state = self._bridge_state_cache.get(prefix)
            if cached_state:
                self._update_coordinator(prefix, status=cached_state)
            # Backfill deviceCount from current cache
            count = sum(1 for d in self.bridge_devices.values()
                        if d.get("_mqtt_prefix") == prefix)
            if count:
                dev.updateStateOnServer("deviceCount", value=count)
            if self.debug:
                log(f"Started coordinator: {dev.name} (prefix={prefix})")
            return

        props = dev.pluginProps
        fname = props.get("friendly_name", "").strip()
        if not fname:
            log(f"Device '{dev.name}' has no friendly_name — skipping", level="WARNING")
            return

        self.friendly_name_map[fname] = dev.id
        ieee = props.get("ieee_address", "")
        if ieee:
            self.ieee_map[ieee] = dev.id

        # Apply Indigo subType — dynamic for lights (Dimmer vs ColorDimmer);
        # static for everything else.  Also backfills devices created before
        # subType was declared in Devices.xml.
        self._apply_indigo_subtype(dev)

        # Apply stored color/capability flags to Indigo device
        if dev.deviceTypeId == "z2mLight":
            self._apply_light_capabilities(dev)

        # Ensure all custom states exist — guards against states added to Devices.xml
        # after a device was originally created (avoids "state key not defined" errors)
        self._ensure_device_states(dev)

        # displayStateId is cached on the device record at create time and is
        # read-only on existing instances — only fix for a stale value after a
        # <UiDisplayStateId> change in Devices.xml is delete + recreate.
        expected_display = self._EXPECTED_DISPLAY_STATE.get(dev.deviceTypeId)
        if expected_display and dev.displayStateId != expected_display:
            log(f"{dev.name}: displayStateId is {dev.displayStateId!r} but XML "
                f"now declares {expected_display!r} — delete + recreate this "
                f"device to pick up the new primary display state",
                level="WARNING")

        # v1.9.12 one-time migration: lastAction became a List enumeration, so
        # Indigo now auto-generates lastAction.<value> boolean sub-states. A
        # device created before the change keeps its old (String) cached state
        # list until we refresh it. Detect by the absence of a known sub-state:
        # stateListOrDisplayStateIdChanged() surfaces the sub-states and they
        # persist on the device record, so this skips on subsequent starts.
        # (A guard pluginProp is NOT used — replacePluginPropsOnServer during
        # deviceStartComm doesn't reliably persist.)
        if dev.deviceTypeId == "z2mButton" and "lastAction.single" not in dev.states:
            try:
                dev.stateListOrDisplayStateIdChanged()
                log(f"{dev.name}: migrated lastAction to enumeration — per-action "
                    f"sub-states (lastAction.single/.double/.hold/...) now "
                    f"available; the matching one goes true on the next press")
            except Exception as e:
                log(f"{dev.name}: lastAction enum state-list refresh failed: {e}",
                    level="WARNING")

        if self.debug:
            log(f"Started device: {dev.name} (type={dev.deviceTypeId}, name={fname})")

        # Request current state after brief delay (MQTT needs time to settle)
        prefix = self._device_prefix(dev)
        threading.Timer(STATE_REQUEST_DELAY, self._request_state, args=(fname, dev.deviceTypeId, prefix)).start()

    # Expected displayStateId per device type — must match <UiDisplayStateId> in
    # Devices.xml.  Used by deviceStartComm to retroactively repair the cached
    # displayStateId on devices created before the XML value was changed.
    _EXPECTED_DISPLAY_STATE = {
        "z2mButton":            "lastAction",
        "z2mTemperatureSensor": "temperature",
    }

    # Default custom states for every device type.
    # Key   = state id as declared in Devices.xml
    # Value = safe initial value (correct Python type for the ValueType)
    # Native states (onOffState, brightnessLevel, sensorValue) are NOT listed —
    # Indigo owns those and they're always present.
    _DEVICE_STATE_DEFAULTS = {
        "z2mLight": [
            ("colorMode",    ""),
            ("colorTemp",    0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mRelay": [
            ("power",        0.0),
            ("energy",       0.0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mContactSensor": [
            ("contact",      False),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mOccupancySensor": [
            ("motion",       False),
            ("occupancy",    False),
            ("presence",     False),
            ("illuminance",  0.0),
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mWaterLeakSensor": [
            ("waterLeak",    False),
            ("temperature",  0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mTemperatureSensor": [
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("pressure",     0.0),
            ("illuminance",  0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mCover": [
            ("coverState",   ""),
            ("tiltAngle",    0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mSensor": [
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("contact",      False),
            ("motion",       False),
            ("waterLeak",    False),
            ("battery",      0),
            ("pressure",     0.0),
            ("illuminance",  0.0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mRepeater": [
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mCoordinator": [
            ("status",          "unknown"),
            ("version",         ""),
            ("coordinator",     ""),
            ("permitJoin",      False),
            ("permitJoinEnd",   ""),
            ("networkChannel",  0),
            ("panId",           0),
            ("extendedPanId",   ""),
            ("deviceCount",     0),
            ("restartRequired", False),
            ("logLevel",        ""),
            ("lastUpdate",      ""),
        ],
    }

    # Map of state-id -> (capability flag(s) that must be true for the state to be
    # pre-initialised).  None means "always init for this device type" (universal
    # states like availability/linkQuality).  Used to filter _DEVICE_STATE_DEFAULTS
    # so unsupported entities don't appear in the Custom States panel.
    _STATE_CAPABILITY_GATE = {
        "z2mLight":            {"colorMode": "has_color", "colorTemp": "has_color_temp"},
        "z2mRelay":            {"power": "has_power", "energy": "has_energy",
                                "voltage": "has_voltage", "current": "has_current"},
        "z2mContactSensor":    {"battery": "has_battery"},
        "z2mOccupancySensor":  {"occupancy": "has_pir", "presence": "has_presence",
                                "illuminance": "has_illuminance",
                                "temperature": "has_temperature",
                                "humidity": "has_humidity",
                                "battery": "has_battery"},
        "z2mWaterLeakSensor":  {"battery": "has_battery", "temperature": "has_temperature"},
        "z2mTemperatureSensor": {"temperature": "has_temperature",
                                 "humidity": "has_humidity",
                                 "pressure": "has_pressure",
                                 "illuminance": "has_illuminance",
                                 "battery": "has_battery"},
        "z2mSensor":           {"temperature": "has_temperature",
                                "humidity": "has_humidity",
                                "contact": "has_contact",
                                "motion": "has_occupancy",
                                "waterLeak": "has_water_leak",
                                "pressure": "has_pressure",
                                "illuminance": "has_illuminance",
                                "battery": "has_battery"},
    }

    def _ensure_device_states(self, dev):
        """Initialise the states this device's hardware actually supports.

        Filters _DEVICE_STATE_DEFAULTS by the device's `has_*` capability flags
        (set at create-time from zigbee2mqtt's exposes data) so the Custom States
        panel only shows entities the physical Zigbee device reports.  States with
        no gating in _STATE_CAPABILITY_GATE are universal (availability / linkQuality
        / motion-mirror / etc.) and are always initialised.

        Per Indigo's state-visibility rule (memory: feedback_indigo_state_visibility),
        states that are never written never appear in the panel — so simply NOT
        pre-initialising unsupported states is enough to hide them.
        """
        defaults = self._DEVICE_STATE_DEFAULTS.get(dev.deviceTypeId)
        if not defaults:
            return  # unknown or native-only type — nothing to do

        gates = self._STATE_CAPABILITY_GATE.get(dev.deviceTypeId, {})
        props = dev.ownerProps
        existing = set(dev.states.keys())
        to_write = []
        for key, val in defaults:
            if key in existing:
                # State already exists on the device record.  We DO NOT clear it back
                # to default — preserves any value already received.
                continue
            gate_prop = gates.get(key)
            if gate_prop and not props.get(gate_prop, False):
                continue  # capability not advertised — leave the state hidden
            to_write.append((key, val))

        if not to_write:
            return

        log(f"{dev.name}: initialising {len(to_write)} supported state(s): "
            f"{[k for k, _ in to_write]}")
        for key, val in to_write:
            try:
                dev.updateStateOnServer(key, val)
            except Exception as e:
                log(f"{dev.name}: could not initialise state '{key}': {e}",
                    level="WARNING")

    # ── Dynamic state capture ───────────────────────────────────────────────
    # Any MQTT payload field not listed in _HANDLED_PAYLOAD_KEYS (and not handled
    # by a type-specific dispatcher) is captured as a dynamic Indigo state.  The
    # union of all keys ever seen for a device is persisted in pluginProps as
    # seenDynamicKeys (CSV).  getDeviceStateList() advertises these to Indigo
    # so they appear in the Custom States panel after stateListOrDisplayStateIdChanged.

    @staticmethod
    def _normalise_action(action):
        """Reduce a raw z2m button action to a clean camelCase token for the
        lastAction enumeration state and its auto-generated boolean sub-states.

        Indigo builds enum sub-state IDs as "lastAction.<value>", and a state-id
        segment must be camelCase ASCII — no leading digit, no underscore (see
        the state-id naming rules). Raw z2m actions break that in two ways:
        a leading "<n>_" button-index prefix ("1_single") and underscore-joined
        compound names ("brightness_move_up"). We therefore drop the button
        index (it is captured separately in lastButton) and camelCase whatever
        remains:
            "1_single"            -> "single"
            "single"              -> "single"
            "2_double"            -> "double"
            "brightness_move_up"  -> "brightnessMoveUp"
            "hold"                -> "hold"
        An action that reduces to nothing usable (e.g. a bare "2") returns
        "unknown" — it simply won't match any declared Option, which the enum
        state handles gracefully (no sub-state fires).
        """
        parts = [p for p in str(action).split("_") if p != ""]
        if parts and parts[0].isdigit():
            parts = parts[1:]  # drop button-index prefix — kept in lastButton
        if not parts:
            return "unknown"
        token = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
        token = "".join(c for c in token if c.isascii() and c.isalnum())
        token = token.lstrip("0123456789")
        return token or "unknown"

    def _sanitise_state_key(self, key):
        """Convert an MQTT field name into a valid Indigo state ID (camelCase).

        Indigo's XML state-id validator rejects any non-ASCII-alphanumeric
        character including the underscore — even though XML itself allows them
        — with LowLevelBadParameterError 'illegal XML tag name character'.
        We therefore convert snake_case to camelCase (the SDK convention used
        in Devices.xml everywhere) so MQTT names like `color_temp_startup` and
        `power_on_behavior` become `colorTempStartup` and `powerOnBehavior`.
        """
        if not key:
            return ""
        # Split on any non-alnum (underscore, dash, dot, space, etc.) to get parts
        parts = []
        cur = []
        for c in key:
            if c.isascii() and c.isalnum():
                cur.append(c)
            else:
                if cur:
                    parts.append("".join(cur))
                    cur = []
        if cur:
            parts.append("".join(cur))
        if not parts:
            return ""
        # First part lowercase, subsequent parts Capitalised — camelCase
        sk = parts[0][0].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
        # Strip any remaining non-ASCII-alnum (defensive — should be impossible after split)
        sk = "".join(c for c in sk if c.isascii() and c.isalnum())
        # Must start with an ASCII letter
        if not sk or not sk[0].isalpha():
            sk = "z2m" + (sk[:1].upper() + sk[1:] if sk else "")
        # XML reserves names starting with "xml" (case-insensitive)
        if sk[:3].lower() == "xml":
            sk = "z" + sk[0].upper() + sk[1:]
        if sk in _RESERVED_STATE_NAMES:
            sk = "z2m" + sk[0].upper() + sk[1:]
        return sk

    # ── Dynamic state type inference ─────────────────────────────────────────
    # Each captured field is tagged with a type token so getDeviceStateList can
    # declare it with the correct Indigo state type (Integer / Real / BoolOnOff /
    # BoolTrueFalse) instead of String.  Tokens are persisted per-device in the
    # dynamicKeyTypes pluginProp (JSON), because the value itself isn't written
    # until AFTER the state list is refreshed — so at declaration time dev.states
    # holds None and the type can only be known from the recorded token.

    @staticmethod
    def _infer_state_type(raw_val):
        """Map a raw payload value to a state-type token.

        bool           -> "bool"  (BoolTrueFalse)
        "ON" / "OFF"   -> "onoff" (BoolOnOff)
        int            -> "int"   (Integer)
        float          -> "real"  (Real)
        anything else  -> "str"   (String; dicts/lists are JSON-stringified)

        bool is checked before int because bool is a subclass of int.
        """
        if isinstance(raw_val, bool):
            return "bool"
        if isinstance(raw_val, int):
            return "int"
        if isinstance(raw_val, float):
            return "real"
        if isinstance(raw_val, str) and raw_val.strip().upper() in ("ON", "OFF"):
            return "onoff"
        return "str"

    @staticmethod
    def _merge_state_type(old, new):
        """Combine a previously recorded token with a freshly observed one.

        Same token wins.  int/real widen to "real" (a Real state holds whole
        numbers too).  Every other disagreement (bool vs number, onoff vs
        anything, etc.) is type drift — fall back to the most permissive type,
        "str", so no typed write is ever rejected.
        """
        if old == new:
            return new
        if {old, new} == {"int", "real"}:
            return "real"
        return "str"

    @staticmethod
    def _coerce_dynamic_value(raw_val, token):
        """Coerce a raw payload value to match its declared state-type token.

        The write value MUST match the declared type, so we coerce by the
        merged/declared token rather than the per-payload Python type.
        """
        if isinstance(raw_val, (dict, list)):
            try:
                return json.dumps(raw_val, separators=(",", ":"), default=str)[:512]
            except Exception:
                return str(raw_val)[:512]
        if token == "bool":
            return bool(raw_val)
        if token == "onoff":
            return str(raw_val).strip().upper() == "ON"
        if token == "int":
            try:
                return int(raw_val)
            except (TypeError, ValueError):
                return str(raw_val)
        if token == "real":
            try:
                return float(raw_val)
            except (TypeError, ValueError):
                return str(raw_val)
        return str(raw_val)

    def _load_dynamic_types(self, dev):
        """Return the persisted {state_id: type_token} map for a device."""
        raw = dev.pluginProps.get("dynamicKeyTypes", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _state_dict_for_token(self, key, label, token):
        """Build the Indigo state-list entry for a dynamic key, choosing the
        type-specific builder that matches its recorded type token."""
        if token == "bool":
            return self.getDeviceStateDictForBoolTrueFalseType(key, label, label)
        if token == "onoff":
            return self.getDeviceStateDictForBoolOnOffType(key, label, label)
        if token == "int":
            return self.getDeviceStateDictForIntegerType(key, label, label)
        if token == "real":
            return self.getDeviceStateDictForRealType(key, label, label)
        return self.getDeviceStateDictForStringType(key, label, label)

    def _capture_raw_fields(self, dev, payload):
        """Write every payload field that the type-specific dispatcher did not
        already handle.  First-time keys are added to pluginProps and the device's
        state list is refreshed.

        Each key's type is inferred from its value and persisted in
        dynamicKeyTypes so getDeviceStateList declares it with the correct Indigo
        state type.  bool -> BoolTrueFalse, "ON"/"OFF" -> BoolOnOff, int ->
        Integer, float -> Real, else String.  Complex types (dict, list) are
        JSON-stringified.  None values are skipped.  Type drift across payloads
        (e.g. int then float) is merged toward the most permissive type seen
        (see _merge_state_type); a refresh is triggered whenever a key is new OR
        its type token changes, so an existing String state migrates to its
        proper type on the next payload that includes it.

        State IDs are tightly validated against Indigo's XML element rules; any
        key that fails validation is dropped with a debug log so it never gets
        persisted to seen-set and corrupts subsequent stateListOrDisplay calls.
        """
        if not isinstance(payload, dict):
            return

        orig_props = dict(dev.pluginProps)
        seen_csv = orig_props.get("seenDynamicKeys", "")
        seen = set(s for s in seen_csv.split(",") if s and self._is_valid_state_id(s))
        type_map = self._load_dynamic_types(dev)
        new_keys = []
        type_changed = False
        # Phase 1: identify keys + values WITHOUT writing.  We must NOT call
        # updateStateOnServer for any state that isn't already declared in our
        # state list — Indigo logs a top-level "state key not defined" error
        # the first time, and we get one error per new key per device per session.
        # Collect them all, then declare in Phase 2, then write in Phase 3.
        pending = []  # list of (state_key, state_val)

        for raw_key, raw_val in payload.items():
            if raw_key in _HANDLED_PAYLOAD_KEYS or raw_key.startswith("_"):
                continue
            if raw_val is None:
                continue
            state_key = self._sanitise_state_key(raw_key)
            if not state_key or not self._is_valid_state_id(state_key):
                if self.debug:
                    log(f"{dev.name}: dropping invalid state-id derived from '{raw_key}' -> '{state_key}'",
                        level="WARNING")
                continue

            token = self._infer_state_type(raw_val)
            if state_key not in seen:
                seen.add(state_key)
                new_keys.append(state_key)
                type_map[state_key] = token
            else:
                old_token = type_map.get(state_key)
                if old_token is None:
                    # Migration: key seen before dynamicKeyTypes existed.  Adopt
                    # the first observed type so a legacy String state gets
                    # re-declared with its proper type on this refresh.
                    type_map[state_key] = token
                    type_changed = True
                else:
                    merged = self._merge_state_type(old_token, token)
                    if merged != old_token:
                        type_map[state_key] = merged
                        type_changed = True

            # Coerce by the final/declared token so the write matches the type.
            state_val = self._coerce_dynamic_value(raw_val, type_map[state_key])
            pending.append((state_key, state_val))

        # Phase 2: if any key is new OR changed type, persist + refresh the state
        # list FIRST so the writes in Phase 3 don't trigger "state key not
        # defined" errors and any retyped state is re-declared before reseeding.
        if new_keys or type_changed:
            try:
                new_props = dict(dev.pluginProps)
                new_props["seenDynamicKeys"] = ",".join(sorted(seen))
                new_props["dynamicKeyTypes"] = json.dumps(
                    type_map, separators=(",", ":"), sort_keys=True)
                dev.replacePluginPropsOnServer(new_props)
                refreshed = indigo.devices[dev.id]
                refreshed.stateListOrDisplayStateIdChanged()
                if new_keys:
                    log(f"{dev.name}: imported {len(new_keys)} new field(s): {new_keys}")
                if type_changed:
                    log(f"{dev.name}: refined dynamic state type(s) from payload")
            except Exception as e:
                log(f"{dev.name}: dynamic-state refresh failed; rolling back. err={e}; "
                    f"new_keys={new_keys}", level="ERROR")
                try:
                    dev.replacePluginPropsOnServer(orig_props)
                except Exception:
                    pass
                # Skip Phase 3: writes for the new keys would fail anyway.
                # Old keys' writes are also skipped to keep the message atomic.
                return

        # Phase 3: now safe to write all pending values.
        for state_key, state_val in pending:
            try:
                dev.updateStateOnServer(state_key, state_val)
            except Exception as e:
                if self.debug:
                    log(f"{dev.name}: dynamic state '{state_key}' write failed: {e}", level="WARNING")

    def getDeviceStateList(self, dev):
        """Override Indigo's static state list with the static + dynamic union.

        Static states come from Devices.xml.  Dynamic states are added on the fly
        as the device reports new fields via MQTT.  Every dynamic state ID is
        re-validated here as a defensive measure — even if a corrupted entry
        somehow lands in `seenDynamicKeys`, it cannot poison this list.

        IMPORTANT: indigo.PluginBase.getDeviceStateList returns the LIVE list
        object from the parser's internal devices_type_dict.  Mutating that
        list permanently corrupts subsequent reads (the same dynamic states
        get appended on every call, accumulating duplicates and eventually
        triggering "illegal XML tag name character" in Indigo's XML
        serialiser).  We therefore work on a fresh copy and return that.
        """
        original = indigo.PluginBase.getDeviceStateList(self, dev)
        if original is None:
            return original

        # Make a shallow copy.  indigo.List/indigo.Dict items inside are reused
        # by reference — that's fine; we only need the OUTER list to be a
        # distinct object so append() doesn't mutate the parser's cache.
        state_list = list(original)

        seen_csv = dev.pluginProps.get("seenDynamicKeys", "")
        if not seen_csv:
            return state_list

        type_map = self._load_dynamic_types(dev)

        # Build the set of static-state IDs already in the list.
        existing_ids = set()
        try:
            for s in state_list:
                k = s.get("Key") if hasattr(s, "get") else s["Key"]
                if k:
                    existing_ids.add(k)
        except Exception:
            existing_ids = set()

        for key in seen_csv.split(","):
            key = key.strip()
            if not key or key in existing_ids:
                continue
            if not self._is_valid_state_id(key):
                continue  # paranoid — should already be filtered by writer
            label = key[:1].upper() + key[1:]  # cosmetic camelCase -> CamelCase
            token = type_map.get(key)
            if token is None:
                # No recorded type yet (pre-upgrade device, before any payload has
                # arrived since the upgrade).  Fall back to inferring from the
                # current stored value, defaulting to String.  The next captured
                # payload records a proper token via _capture_raw_fields.
                current = dev.states.get(key) if hasattr(dev, "states") else None
                if isinstance(current, bool):
                    token = "bool"
                elif isinstance(current, float):
                    token = "real"
                elif isinstance(current, int):
                    token = "int"
                else:
                    token = "str"
            try:
                state_list.append(self._state_dict_for_token(key, label, token))
                existing_ids.add(key)
            except Exception:
                # Skip silently — the writer logs detail; this method must return
                # a clean list every time getDeviceStateList is called.
                continue
        return state_list

    def deviceStopComm(self, dev):
        if dev.deviceTypeId == "z2mCoordinator":
            prefix = dev.pluginProps.get("mqtt_prefix", "")
            self.coordinator_map.pop(prefix, None)
            if self.debug:
                log(f"Stopped coordinator: {dev.name}")
            return
        fname = dev.pluginProps.get("friendly_name", "")
        self.friendly_name_map.pop(fname, None)
        ieee = dev.pluginProps.get("ieee_address", "")
        self.ieee_map.pop(ieee, None)
        self._motion_states.pop(dev.id, None)
        if self.debug:
            log(f"Stopped device: {dev.name}")

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Restart device comm only for changes that materially affect the MQTT
        subscription or device identity.

        Z2M devices route via MQTT topics built from `friendly_name` and are
        identified by `ieee_address`; a change to either requires a fresh comm
        cycle so subscriptions and lookup maps track. The coordinator's
        `mqtt_prefix` defines the topic root.

        All other pluginProps — `vendor`, `model`, `capabilities_display`,
        internal capability flags, `seenDynamicKeys`, `dynamicKeyTypes` — are
        cosmetic or healing writes that should NOT cycle comm.
        """
        keys = ("friendly_name", "ieee_address", "mqtt_prefix")
        return any(oldDevice.pluginProps.get(k) != newDevice.pluginProps.get(k) for k in keys)

    # ── Action handlers ───────────────────────────────────────────────────────

    def actionControlDevice(self, action, dev):
        """Handle all plugin device actions.

        In Indigo 2025.x all plugin device actions are routed through actionControlDevice
        regardless of device class.  Forward dimmer-class devices (z2mLight, z2mCover) to
        actionControlDimmer so their SetBrightness / SetColorLevels / etc. are handled.
        """
        if dev.deviceTypeId in ("z2mLight", "z2mCover"):
            self.actionControlDimmer(action, dev)
            return

        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kDeviceAction.TurnOn:
            self._publish(f"{prefix}/{fname}/set", {"state": "ON"})
            log(f'sent "{dev.name}" on')
        elif cmd == indigo.kDeviceAction.TurnOff:
            self._publish(f"{prefix}/{fname}/set", {"state": "OFF"})
            log(f'sent "{dev.name}" off')
        elif cmd == indigo.kDeviceAction.Toggle:
            new_state = "OFF" if dev.onState else "ON"
            self._publish(f"{prefix}/{fname}/set", {"state": new_state})
            log(f'sent "{dev.name}" toggle -> {new_state.lower()}')
        elif cmd == indigo.kDeviceAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix)
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled relay action {cmd} for {dev.name}", level="WARNING")

    def actionControlDimmer(self, action, dev):
        """Handle dimmer-class device actions (z2mLight and z2mCover)."""
        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        is_cover = (dev.deviceTypeId == "z2mCover")

        if cmd == indigo.kDimmerRelayAction.TurnOn:
            if is_cover:
                self._publish(f"{prefix}/{fname}/set", {"state": "OPEN"})
                log(f'sent "{dev.name}" open')
            else:
                self._publish(f"{prefix}/{fname}/set", {"state": "ON"})
                log(f'sent "{dev.name}" on')

        elif cmd == indigo.kDimmerRelayAction.TurnOff:
            if is_cover:
                self._publish(f"{prefix}/{fname}/set", {"state": "CLOSE"})
                log(f'sent "{dev.name}" close')
            else:
                self._publish(f"{prefix}/{fname}/set", {"state": "OFF"})
                log(f'sent "{dev.name}" off')

        elif cmd == indigo.kDimmerRelayAction.Toggle:
            if is_cover:
                new_state = "CLOSE" if dev.onState else "OPEN"
                self._publish(f"{prefix}/{fname}/set", {"state": new_state})
                log(f'sent "{dev.name}" toggle -> {new_state.lower()}')
            else:
                new_state = "OFF" if dev.onState else "ON"
                self._publish(f"{prefix}/{fname}/set", {"state": new_state})
                log(f'sent "{dev.name}" toggle -> {new_state.lower()}')

        elif cmd == indigo.kDimmerRelayAction.SetBrightness:
            level = action.actionValue  # 0-100
            if is_cover:
                self._publish(f"{prefix}/{fname}/set", {"position": level})
                log(f'sent "{dev.name}" set position to {level}%')
            else:
                brightness = _brightness_100_to_255(level)
                payload = {"brightness": brightness, "state": "ON" if level > 0 else "OFF"}
                self._publish(f"{prefix}/{fname}/set", payload)
                log(f'sent "{dev.name}" set brightness to {level}%')

        elif cmd in (indigo.kDimmerRelayAction.BrightenBy, indigo.kDimmerRelayAction.DimBy):
            current = dev.brightness
            delta   = action.actionValue
            if cmd == indigo.kDimmerRelayAction.BrightenBy:
                new_level = min(100, current + delta)
            else:
                new_level = max(0, current - delta)
            if is_cover:
                self._publish(f"{prefix}/{fname}/set", {"position": new_level})
                verb = "open" if cmd == indigo.kDimmerRelayAction.BrightenBy else "close"
                log(f'sent "{dev.name}" {verb} by {delta}% -> {new_level}%')
            else:
                brightness = _brightness_100_to_255(new_level)
                payload = {"brightness": brightness, "state": "ON" if new_level > 0 else "OFF"}
                self._publish(f"{prefix}/{fname}/set", payload)
                verb = "brighten" if cmd == indigo.kDimmerRelayAction.BrightenBy else "dim"
                log(f'sent "{dev.name}" {verb} by {delta}% -> {new_level}%')

        elif cmd == indigo.kDimmerRelayAction.SetColorLevels:
            # Only applicable to z2mLight
            if is_cover:
                log(f"{dev.name}: SetColorLevels not applicable to cover", level="WARNING")
                return
            color_vals = action.actionValue
            if "whiteTemperature" in color_vals:
                kelvin = int(color_vals["whiteTemperature"])
                kelvin = max(1000, min(10000, kelvin))
                mireds = _kelvin_to_mireds(kelvin)
                self._publish(f"{prefix}/{fname}/set", {"color_temp": mireds, "state": "ON"})
                log(f'sent "{dev.name}" set color temp to {kelvin}K')
            elif all(k in color_vals for k in ("redLevel", "greenLevel", "blueLevel")):
                r = int(round(float(color_vals["redLevel"])   / 100.0 * 255))
                g = int(round(float(color_vals["greenLevel"]) / 100.0 * 255))
                b = int(round(float(color_vals["blueLevel"])  / 100.0 * 255))
                self._publish(f"{prefix}/{fname}/set", {"color": {"r": r, "g": g, "b": b}, "state": "ON"})
                log(f'sent "{dev.name}" set color RGB ({r}, {g}, {b})')
            else:
                log(f"{dev.name}: SetColorLevels — no actionable channels in {list(color_vals.keys())}", level="WARNING")

        else:
            log(f"Unhandled dimmer action {cmd} for {dev.name}", level="WARNING")

    def actionControlUniversal(self, action, dev):
        # Indigo's universal-action callback is actionControlUniversal (confirmed
        # against all SDK device examples) — NOT actionControlUniversalDevices, which
        # Indigo never calls (the old name left this handler dead; everyday Send Status
        # Request still worked because the class-specific handlers also service it).
        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kUniversalAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix)
        else:
            log(f"Unhandled universal action {cmd} for {dev.name}", level="WARNING")

    def actionControlSensor(self, action, dev):
        """Handle sensor-class device actions.

        z2m sensors are read-only — the network does not accept commands back
        to them — so the only meaningful action is RequestStatus, which we
        service by re-publishing the /get topic so z2mqtt resends the
        retained payload. Implementing this method silences the
        'plugin does not define method actionControlSensor' error that
        Indigo logs whenever any Send Status Request (or similar) action
        is fired against a z2m sensor device.

        NOTE: SensorAction uses .sensorAction (NOT .deviceAction — that
        attribute only exists on DeviceAction / DimmerAction). Confirmed
        25-05-2026: passing action.deviceAction raises
        "'SensorAction' object has no attribute 'deviceAction'".
        """
        cmd    = action.sensorAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kSensorAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix)
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled sensor action {cmd} for {dev.name} "
                f"(sensors are read-only)", level="WARNING")

    def action_set_color_temperature(self, action, dev=None, callerWaitingForResult=None):
        """Action: set light color temperature in Kelvin."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        if not (dev.pluginProps.get("has_color_temp", False) or dev.supportsWhiteTemperature):
            log(f"{dev.name}: color temperature not supported", level="WARNING")
            return
        try:
            kelvin = int(action.props.get("kelvin", 2700))
            kelvin = max(1000, min(10000, kelvin))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid kelvin value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        mireds = _kelvin_to_mireds(kelvin)
        self._publish(f"{prefix}/{fname}/set", {"color_temp": mireds, "state": "ON"})
        if self.debug:
            log(f"{dev.name}: set color temp {kelvin}K ({mireds} mireds)")

    def action_set_brightness(self, action, dev=None, callerWaitingForResult=None):
        """Action: set brightness (light) or position (cover) 0-100."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        try:
            level = max(0, min(100, int(action.props.get("brightness", 100))))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid brightness value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        if dev.deviceTypeId == "z2mCover":
            self._publish(f"{prefix}/{fname}/set", {"position": level})
            if self.debug:
                log(f"{dev.name}: set position {level}%")
        else:
            brightness = _brightness_100_to_255(level)
            self._publish(f"{prefix}/{fname}/set",
                          {"brightness": brightness, "state": "ON" if level > 0 else "OFF"})
            if self.debug:
                log(f"{dev.name}: set brightness {level}%")

    def action_set_cover_position(self, action, dev=None, callerWaitingForResult=None):
        """Action: set cover position 0-100."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        try:
            position = max(0, min(100, int(action.props.get("position", 50))))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid position value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._publish(f"{prefix}/{fname}/set", {"position": position})
        if self.debug:
            log(f"{dev.name}: set cover position {position}%")

    def action_refresh_state(self, action, dev=None, callerWaitingForResult=None):
        """Action: request current state from device."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._request_state(fname, dev.deviceTypeId, prefix)

    # ── Menu callbacks ────────────────────────────────────────────────────────

    def _get_existing_friendly_names(self):
        """Return a set of friendly_names for all active devices owned by this plugin."""
        names = set()
        for dev in indigo.devices.iter(self.pluginId):
            fn = dev.pluginProps.get("friendly_name", "")
            if fn:
                names.add(fn)
        return names

    def _try_create_device(self, device_data, folder_id, existing_names):
        """Attempt to create a single Indigo device from Z2M device_data.

        Returns one of: 'created', 'exists', 'coordinator', 'no_definition', 'error'.
        existing_names is updated in-place when a device is successfully created.
        """
        fname  = device_data.get("friendly_name", "")
        d_type = device_data.get("type", "")

        if d_type == "Coordinator":
            return "coordinator"
        if fname in existing_names:
            return "exists"

        definition = device_data.get("definition")
        if definition is None:
            log(f"  skip (not yet interviewed by z2m): {fname}", level="WARNING")
            return "no_definition"

        exposes        = definition.get("exposes", [])
        device_type_id = _detect_device_type(exposes, model=definition.get("model", ""))
        plugin_props   = self._build_plugin_props(device_type_id, device_data, definition, exposes)
        plugin_props["mqtt_prefix"] = device_data.get("_mqtt_prefix", self._topic_prefix())

        try:
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=fname,
                pluginId=self.pluginId,
                deviceTypeId=device_type_id,
                folder=folder_id,
                props=plugin_props,
            )
            vendor = definition.get("vendor", "")
            model  = definition.get("model", "")
            log(f"  created {device_type_id}: '{new_dev.name}'"
                + (f" ({vendor} {model})" if vendor or model else ""))
            existing_names.add(fname)  # prevent duplicate creation within same pass
            return "created"
        except Exception as e:
            log(f"  error creating '{fname}': {e}", level="ERROR")
            return "error"

    def discover_create_devices(self, valuesDict=None, typeId=None):
        """Scan the bridge device cache and create an Indigo device for every
        Z2M device not already in Indigo.  All devices land in the
        'Zigbee2MQTT' device folder (created if absent).
        """
        if not self.bridge_devices:
            log("No bridge device data yet. "
                "Wait for MQTT connection then use Refresh Device List, or wait ~10s.",
                level="WARNING")
            return

        folder_id      = self._ensure_device_folder(DEVICE_FOLDER_NAME)
        existing_names = self._get_existing_friendly_names()

        counts = {"created": 0, "exists": 0, "coordinator": 0,
                  "no_definition": 0, "error": 0}
        for device_data in self.bridge_devices.values():
            result = self._try_create_device(device_data, folder_id, existing_names)
            counts[result] += 1
            if result == "exists" and self.debug:
                log(f"  skip (exists): {device_data.get('friendly_name', '?')}")

        parts = [f"{counts['created']} created",
                 f"{counts['exists']} already existed"]
        if counts["coordinator"]:
            parts.append(f"{counts['coordinator']} coordinator(s) skipped")
        if counts["no_definition"]:
            parts.append(f"{counts['no_definition']} uninterviewed device(s) skipped")
        if counts["error"]:
            parts.append(f"{counts['error']} error(s)")
        log(f"Discover & Create complete: {', '.join(parts)}")

    def create_coordinator_devices(self, valuesDict=None, typeId=None):
        """Create a z2mCoordinator device for every configured MQTT prefix
        that doesn't already have one. Names are 'Z2M Bridge (<prefix>)'."""
        folder_id = self._ensure_device_folder(DEVICE_FOLDER_NAME)
        prefixes  = [self._topic_prefix()]
        garage    = self._garage_prefix()
        if garage:
            prefixes.append(garage)

        created = 0
        existed = 0
        for prefix in prefixes:
            if prefix in self.coordinator_map:
                log(f"  exists: coordinator for prefix '{prefix}'")
                existed += 1
                continue
            name = f"Z2M Bridge ({prefix})"
            # Avoid duplicate name collision
            base = name
            i = 2
            while name in indigo.devices:
                name = f"{base} #{i}"
                i += 1
            try:
                new_dev = indigo.device.create(
                    protocol     = indigo.kProtocol.Plugin,
                    address      = prefix,
                    name         = name,
                    description  = f"Z2M bridge / coordinator status — prefix {prefix}",
                    pluginId     = self.pluginId,
                    deviceTypeId = "z2mCoordinator",
                    folder       = folder_id,
                    props        = {"mqtt_prefix": prefix},
                )
                log(f"  created coordinator: '{new_dev.name}' (prefix={prefix})")
                created += 1
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"create coordinator for '{prefix}'")
        log(f"Create Coordinator Devices complete: {created} created, {existed} already existed")

    def refresh_bridge_devices(self, valuesDict=None, typeId=None):
        """Menu item: republish a get request for bridge/devices."""
        prefix = self._topic_prefix()
        self._publish(f"{prefix}/bridge/request/devices", {})
        garage = self._garage_prefix()
        if garage:
            self._publish(f"{garage}/bridge/request/devices", {})
        log("Requested device list refresh from MQTT bridge"
            + (f" (+ garage: {garage})" if garage else ""))

    _CAP_DETECTORS = {
        "z2mLight":             _detect_light_capabilities,
        "z2mContactSensor":     _detect_contact_sensor_capabilities,
        "z2mOccupancySensor":   _detect_occupancy_sensor_capabilities,
        "z2mWaterLeakSensor":   _detect_water_leak_sensor_capabilities,
        "z2mTemperatureSensor": _detect_temperature_sensor_capabilities,
        "z2mSensor":            _detect_sensor_capabilities,
        "z2mRelay":             _detect_relay_capabilities,
    }

    def refresh_device_capabilities(self, valuesDict=None, typeId=None):
        """Menu item: re-detect has_* / capabilities_display for every existing
        Z2M Indigo device by re-running the per-type capability detector against
        the live exposes in self.bridge_devices. Then re-apply the Indigo subType
        so devices created before a capability landed (or before z2mSensor
        subType backfill arrived in v1.8.0/1.9.1) get their flags + subType
        corrected without delete-and-recreate. Idempotent.
        """
        if not self.bridge_devices:
            log("No bridge device data yet — wait for MQTT or run "
                "'Refresh Device List from MQTT' first.", level="WARNING")
            return

        # Index bridge cache by both ieee and friendly_name for fast lookup
        by_ieee = {}
        by_fname = {}
        for d in self.bridge_devices.values():
            ieee = (d.get("ieee_address") or "").strip()
            fn   = (d.get("friendly_name") or "").strip()
            if ieee:
                by_ieee[ieee] = d
            if fn:
                by_fname[fn] = d

        changed = unchanged = missing = no_def = skipped = 0
        for dev in indigo.devices.iter(self.pluginId):
            type_id = dev.deviceTypeId
            if type_id == "z2mCoordinator":
                skipped += 1
                continue

            detector = self._CAP_DETECTORS.get(type_id)
            if detector is None:
                # No capability detector for this type (z2mRepeater, z2mCover,
                # z2mButton handled inline at create time). Still re-apply
                # subType in case it's missing.
                self._apply_indigo_subtype(dev)
                skipped += 1
                continue

            props = dev.pluginProps
            ieee  = (props.get("ieee_address") or "").strip()
            fname = (props.get("friendly_name") or "").strip()

            data = by_ieee.get(ieee) if ieee else None
            if data is None and fname:
                data = by_fname.get(fname)

            if data is None:
                log(f"  {dev.name}: not in bridge cache (ieee={ieee or '?'}, "
                    f"fname={fname or '?'}) — skipping", level="WARNING")
                missing += 1
                continue

            definition = data.get("definition")
            if definition is None:
                log(f"  {dev.name}: no Z2M definition (uninterviewed) — skipping",
                    level="WARNING")
                no_def += 1
                continue

            exposes = definition.get("exposes", []) or []
            try:
                caps = detector(exposes)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"refresh caps for {dev.name}")
                continue

            # Build the full set of target props in one dict, then diff in one pass.
            # For z2mLight we add the Indigo-native colour flags using the SAME
            # helper as _apply_light_capabilities to prevent the two paths drifting
            # apart (would cause a deviceStartComm <-> refresh flip-flop).
            target = dict(caps)
            if type_id == "z2mLight":
                target.update(self._compute_light_native_flags(
                    caps.get("has_color",      False),
                    caps.get("has_color_temp", False),
                ))

            new_props = dict(props)
            diffs = []
            for k, v in target.items():
                old = new_props.get(k)
                if old != v:
                    diffs.append((k, old, v))
                    new_props[k] = v

            if diffs:
                # Only worth rebuilding capabilities_display if a capability flag
                # actually changed — skips ~50 string-format calls on a no-op refresh.
                new_display = _build_capabilities_display(type_id, new_props)
                if new_props.get("capabilities_display") != new_display:
                    diffs.append(("capabilities_display",
                                  new_props.get("capabilities_display"),
                                  new_display))
                    new_props["capabilities_display"] = new_display

            if diffs:
                try:
                    dev.replacePluginPropsOnServer(new_props)
                except Exception as e:
                    self.exception_handler(e, log_failing_statement=True,
                                           context=f"replacePluginProps {dev.name}")
                    continue
                # Re-fetch so _apply_indigo_subtype sees the new props
                refreshed = indigo.devices[dev.id]
                old_subtype = refreshed.subType
                self._apply_indigo_subtype(refreshed)
                refreshed = indigo.devices[refreshed.id]
                summary = ", ".join(
                    f"{k}: {old!r}->{new!r}" for k, old, new in diffs
                )
                subtype_note = ""
                if refreshed.subType != old_subtype:
                    subtype_note = f"; subType {old_subtype or '∅'!r}->{refreshed.subType!r}"
                log(f"  {dev.name}: updated [{summary}]{subtype_note}")
                changed += 1
            else:
                # Props unchanged, but subType might still need backfilling
                old_subtype = dev.subType
                self._apply_indigo_subtype(dev)
                refreshed = indigo.devices[dev.id]
                if refreshed.subType != old_subtype:
                    log(f"  {dev.name}: no capability changes; "
                        f"subType {old_subtype or '∅'!r}->{refreshed.subType!r}")
                    changed += 1
                else:
                    if self.debug:
                        log(f"  {dev.name}: no change")
                    unchanged += 1

        parts = [f"{changed} updated", f"{unchanged} unchanged"]
        if missing:
            parts.append(f"{missing} not in bridge cache")
        if no_def:
            parts.append(f"{no_def} uninterviewed")
        if skipped:
            parts.append(f"{skipped} skipped (no detector)")
        log(f"Refresh Device Capabilities complete: {', '.join(parts)}")

    def showPluginInfo(self, valuesDict=None, typeId=None):
        z2m_count = sum(1 for _ in indigo.devices.iter(self.pluginId))
        if log_startup_banner:
            _extras = [
                ("MQTT Broker:", f"{self._effective_broker()}:{self._effective_port()}"),
                ("Topic Prefix:", self._topic_prefix()),
            ]
            _garage = self._garage_prefix()
            if _garage:
                _extras.append(("Garage Prefix:", _garage))
            _extras += [
                ("MQTT Status:", "connected" if self.mqtt_connected else "disconnected"),
                ("Bridge Devices Cached:", str(len(self.bridge_devices))),
                ("Z2M Indigo Devices:", str(z2m_count)),
                ("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"),
            ]
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion,
                               extras=_extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")

    # ── MQTT internals ────────────────────────────────────────────────────────

    def _effective_broker(self):
        # IndigoSecrets first, PluginConfig fallback, "" if neither set.
        return MQTT_BROKER or self.pluginPrefs.get("mqtt_broker", "").strip()

    def _effective_port(self):
        if MQTT_PORT:
            return MQTT_PORT
        try:
            return int(self.pluginPrefs.get("mqtt_port", "1883") or 1883)
        except (TypeError, ValueError):
            return 1883

    def _topic_prefix(self):
        return self.pluginPrefs.get("mqtt_topic_prefix", "zigbee2mqtt").strip()

    def _garage_prefix(self):
        """Return the optional garage Z2M topic prefix, or None if not configured."""
        p = self.pluginPrefs.get("mqtt_garage_topic_prefix", "").strip()
        return p if p else None

    def _device_prefix(self, dev):
        """Return the MQTT topic prefix for a device (stored per-device, falls back to primary)."""
        return dev.pluginProps.get("mqtt_prefix", self._topic_prefix())

    def _start_mqtt(self):
        if mqtt is None:
            log("paho-mqtt not available — cannot connect. Check requirements.txt installation.", level="ERROR")
            return

        broker   = self._effective_broker()
        port     = self._effective_port()
        username = MQTT_USERNAME or self.pluginPrefs.get("mqtt_username", "").strip()
        password = MQTT_PASSWORD or self.pluginPrefs.get("mqtt_password", "")

        if not broker:
            log("MQTT broker not configured. Set MQTT_BROKER in IndigoSecrets.py OR "
                "fill Broker Host in Plugins -> Zigbee2MQTT Bridge -> Configure.",
                level="ERROR")
            return

        with self.mqtt_lock:
            try:
                client = mqtt.Client(client_id=f"indigo_z2mbridge_{int(time.time())}")
                if username:
                    client.username_pw_set(username, password)
                client.on_connect    = self._on_mqtt_connect
                client.on_disconnect = self._on_mqtt_disconnect
                client.on_message    = self._on_mqtt_message
                client.reconnect_delay_set(min_delay=5, max_delay=RECONNECT_DELAY)
                client.connect_async(broker, port, keepalive=60)
                client.loop_start()
                self.mqtt_client = client
                log(f"MQTT connecting to {broker}:{port}")
            except Exception as e:
                log(f"MQTT connect error: {e}", level="ERROR")

    def _stop_mqtt(self):
        with self.mqtt_lock:
            if self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
                self.mqtt_client    = None
                self.mqtt_connected = False

    def _mqtt_liveness_check(self):
        """Self-heal backstop: paho's loop_start auto-reconnect can wedge on a
        half-open socket after a network blip without firing on_disconnect (this is
        what left Jane Lamp dead on 29-05-2026 — "sent" logged into a dead socket,
        zero inbound, mqtt_connected still True). If no MQTT message has arrived for
        MQTT_SILENCE_LIMIT seconds, tear the client down and rebuild it from scratch,
        regardless of what mqtt_connected reports."""
        now = time.time()
        if now - self._last_mqtt_check < MQTT_WATCHDOG_EVERY:
            return
        self._last_mqtt_check = now
        if self.mqtt_client is None:
            return  # not started, or deliberately stopped
        silent = now - self.last_rx_ts
        if silent > MQTT_SILENCE_LIMIT:
            log(f"MQTT silent for {silent:.0f}s (limit {MQTT_SILENCE_LIMIT}s) — rebuilding "
                f"connection (paho loop assumed wedged)", level="WARNING")
            self._stop_mqtt()
            self.last_rx_ts = time.time()   # give the rebuild a full fresh window
            self._start_mqtt()

    def _publish(self, topic, payload):
        """Publish a JSON payload to an MQTT topic."""
        with self.mqtt_lock:
            if not self.mqtt_connected or not self.mqtt_client:
                log(f"MQTT not connected — cannot publish to {topic}", level="WARNING")
                return
            try:
                self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
                if self.debug:
                    log(f"MQTT publish -> {topic}: {payload}")
            except Exception as e:
                log(f"MQTT publish error on {topic}: {e}", level="ERROR")

    def _request_state(self, friendly_name, device_type_id="z2mSensor", prefix=None):
        """Ask zigbee2mqtt to publish the current state for a device."""
        if prefix is None:
            prefix = self._topic_prefix()
        if device_type_id == "z2mLight":
            payload = {"state": "", "brightness": "", "color_temp": "", "color": "", "color_mode": ""}
        else:
            payload = {"state": ""}
        self._publish(f"{prefix}/{friendly_name}/get", payload)

    # ── paho callbacks (run on paho thread — queue only, no Indigo calls) ─────

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.mqtt_connected = True
            self.last_rx_ts     = time.time()   # fresh connection — reset the liveness clock
            prefix = self._topic_prefix()
            client.subscribe(f"{prefix}/#", qos=1)
            subscribed = [f"{prefix}/#"]
            garage = self._garage_prefix()
            if garage:
                client.subscribe(f"{garage}/#", qos=1)
                subscribed.append(f"{garage}/#")
            log(f"MQTT subscribed to: {', '.join(subscribed)}")
            self.msg_queue.put(("__connected__", {}))
        else:
            rc_labels = {
                1: "bad protocol",
                2: "bad client ID",
                3: "server unavailable",
                4: "bad credentials",
                5: "not authorised",
            }
            self.msg_queue.put(("__error__", {"msg": f"MQTT connect failed: {rc_labels.get(rc, rc)}"}))

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        self.msg_queue.put(("__disconnected__", {"rc": rc}))

    def _on_mqtt_message(self, client, userdata, msg):
        self.last_rx_ts = time.time()   # liveness: any inbound message proves the link is alive
        try:
            raw = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return  # binary payload
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Older Z2M publishes bare strings like `online` on bridge/state.
            # Pass the raw decoded string through so handlers can deal with it.
            payload = raw
        self.msg_queue.put((msg.topic, payload))

    # ── Message processing (Indigo main thread) ───────────────────────────────

    def _process_message(self, topic, payload):
        """Route an MQTT message to the appropriate handler."""
        # Internal control messages
        if topic == "__connected__":
            log(f"MQTT connected to {self._effective_broker()}:{self._effective_port()}")
            # Actively request bridge/devices from every configured prefix.
            # Retained messages alone are unreliable — the garage Z2M may not have
            # published since broker restart, or retain may be disabled.
            prefix = self._topic_prefix()
            self._publish(f"{prefix}/bridge/request/devices", {})
            garage = self._garage_prefix()
            if garage:
                self._publish(f"{garage}/bridge/request/devices", {})
                log(f"Requested device list from garage bridge: {garage}/bridge/request/devices")
            return
        if topic == "__disconnected__":
            rc = payload.get("rc", "?")
            if rc == 0:
                log("MQTT disconnected cleanly")
            else:
                log(f"MQTT disconnected unexpectedly (rc={rc}) — will auto-reconnect", level="WARNING")
            return
        if topic == "__error__":
            log(payload.get("msg", "MQTT error"), level="ERROR")
            return

        parts  = topic.split("/")
        if not parts or len(parts) < 2:
            return

        # Determine which prefix this message belongs to
        primary = self._topic_prefix()
        garage  = self._garage_prefix()
        if parts[0] == primary:
            effective_prefix = primary
        elif garage and parts[0] == garage:
            effective_prefix = garage
        else:
            return

        # First-message diagnostic for non-primary prefixes
        if effective_prefix != primary and effective_prefix not in self._seen_prefixes:
            self._seen_prefixes.add(effective_prefix)
            log(f"First MQTT message received from prefix '{effective_prefix}' — "
                f"topic: {topic}")

        # Bridge topics: prefix/bridge/...
        if parts[1] == "bridge":
            if len(parts) >= 3:
                bt = parts[2]
                if bt == "devices":
                    self._process_bridge_devices(payload, effective_prefix)
                elif bt == "state":
                    self._process_bridge_state(payload, effective_prefix)
                elif bt == "info":
                    self._process_bridge_info(payload, effective_prefix)
            return

        # Availability: last path component is "availability"
        # Handles friendly names with embedded slashes correctly
        if parts[-1] == "availability":
            fname = "/".join(parts[1:-1])
            self._process_availability(fname, payload)
            return

        # Device state: everything after prefix is the friendly_name
        fname = "/".join(parts[1:])
        self._process_device_state(fname, payload)

    def _process_bridge_devices(self, payload, prefix=None):
        """Cache ALL non-coordinator, non-disabled zigbee2mqtt devices.

        After updating the cache, auto-creates any device that is genuinely new
        (i.e. its IEEE address was not present for this prefix before this update).
        The startup flood is avoided by only acting when the cache already held
        entries for this prefix — meaning we have a baseline to compare against.
        """
        if not isinstance(payload, list):
            return
        if prefix is None:
            prefix = self._topic_prefix()

        # Snapshot IEEE addresses known for this prefix before the update
        old_ieee = {ieee for ieee, d in self.bridge_devices.items()
                    if d.get("_mqtt_prefix") == prefix}

        old_count = len(self.bridge_devices)
        # Preserve entries from the other prefix; replace only entries for this prefix
        new_cache = {ieee: d for ieee, d in self.bridge_devices.items()
                     if d.get("_mqtt_prefix") != prefix}
        for d in payload:
            ieee = d.get("ieee_address", "")
            if not ieee or d.get("disabled", False):
                continue
            if d.get("type") == "Coordinator":
                continue
            entry = dict(d)
            entry["_mqtt_prefix"] = prefix
            new_cache[ieee] = entry
        self.bridge_devices = new_cache
        count = len(self.bridge_devices)
        if self.debug or count != old_count:
            label = f" [{prefix}]" if prefix != self._topic_prefix() else ""
            log(f"Bridge device cache updated{label}: {count} device(s) total")

        # Detect friendly_name renames and prefix migrations for existing devices.
        # Uses ieee_map for O(1) lookup — no full Indigo device iteration needed.
        for ieee, data in new_cache.items():
            if data.get("_mqtt_prefix") != prefix:
                continue
            dev_id = self.ieee_map.get(ieee)
            if dev_id is None:
                continue
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            new_fname      = data.get("friendly_name", "")
            old_fname      = dev.pluginProps.get("friendly_name", "")
            stored_prefix  = dev.pluginProps.get("mqtt_prefix", self._topic_prefix())
            prefix_changed = stored_prefix != prefix
            name_changed   = new_fname and old_fname and new_fname != old_fname

            if prefix_changed or name_changed:
                try:
                    new_props = dict(dev.pluginProps)
                    if prefix_changed:
                        new_props["mqtt_prefix"] = prefix
                    if name_changed:
                        new_props["friendly_name"] = new_fname
                    dev.replacePluginPropsOnServer(new_props)
                    if name_changed:
                        dev.name = new_fname
                        dev.replaceOnServer()
                        self.friendly_name_map.pop(old_fname, None)
                        self.friendly_name_map[new_fname] = dev.id
                    if prefix_changed and name_changed:
                        log(f"Device moved+renamed: '{old_fname}' -> '{new_fname}' "
                            f"(prefix: {stored_prefix} -> {prefix})")
                    elif prefix_changed:
                        log(f"Device moved: '{new_fname}' "
                            f"(prefix: {stored_prefix} -> {prefix})")
                    else:
                        log(f"Device renamed: '{old_fname}' -> '{new_fname}'")
                except Exception as e:
                    log(f"Error updating device '{old_fname}': {e}", level="ERROR")

        # Auto-create devices that are brand new to this prefix.
        # Guard: old_ieee must be non-empty so we skip the initial startup load.
        if old_ieee:
            new_ieee = {ieee for ieee in new_cache
                        if new_cache[ieee].get("_mqtt_prefix") == prefix
                        and ieee not in old_ieee}
            if new_ieee:
                folder_id      = self._ensure_device_folder(DEVICE_FOLDER_NAME)
                existing_names = self._get_existing_friendly_names()
                for ieee in new_ieee:
                    self._try_create_device(new_cache[ieee], folder_id, existing_names)

        # Update the coordinator's deviceCount + lastUpdate (if one exists for this prefix)
        self._update_coordinator(prefix, deviceCount=sum(
            1 for d in self.bridge_devices.values()
            if d.get("_mqtt_prefix") == prefix))

    def _process_bridge_state(self, payload, prefix):
        """Handle prefix/bridge/state.  Payload is either a JSON dict
        {"state": "online"} (newer Z2M) or a bare string "online" (older)."""
        if isinstance(payload, dict):
            state = payload.get("state", "")
        elif isinstance(payload, str):
            state = payload.strip().strip('"')
        else:
            return
        if not state:
            return
        self._bridge_state_cache[prefix] = state
        self._update_coordinator(prefix, status=state)
        if self.debug:
            log(f"Bridge '{prefix}' state: {state}")

    def _process_bridge_info(self, payload, prefix):
        """Handle prefix/bridge/info — comprehensive bridge metadata."""
        if not isinstance(payload, dict):
            return
        self._bridge_info_cache[prefix] = payload

        kv = {}
        version = payload.get("version", "")
        if version:
            kv["version"] = str(version)
        coord = payload.get("coordinator", {})
        if isinstance(coord, dict):
            ctype = coord.get("type", "")
            if ctype:
                kv["coordinator"] = str(ctype)
        kv["permitJoin"]      = bool(payload.get("permit_join", False))
        permit_end = payload.get("permit_join_end")
        kv["permitJoinEnd"]   = "" if permit_end is None else str(permit_end)
        kv["restartRequired"] = bool(payload.get("restart_required", False))
        log_level = payload.get("log_level", "")
        if log_level:
            kv["logLevel"] = str(log_level)
        net = payload.get("network", {})
        if isinstance(net, dict):
            if "channel" in net:
                try:
                    kv["networkChannel"] = int(net["channel"])
                except (TypeError, ValueError):
                    pass
            if "pan_id" in net:
                try:
                    kv["panId"] = int(net["pan_id"])
                except (TypeError, ValueError):
                    pass
            if "extended_pan_id" in net:
                kv["extendedPanId"] = str(net["extended_pan_id"])

        self._update_coordinator(prefix, **kv)

    def _update_coordinator(self, prefix, **state_kv):
        """Push a batch of state updates to the coordinator device bound to
        this MQTT prefix. Silently no-ops if no coordinator device exists
        for the prefix (user hasn't created one yet)."""
        dev_id = self.coordinator_map.get(prefix)
        if dev_id is None:
            return
        try:
            dev = indigo.devices[dev_id]
        except KeyError:
            self.coordinator_map.pop(prefix, None)
            return
        state_kv["lastUpdate"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates = [{"key": k, "value": v} for k, v in state_kv.items()
                   if k in dev.states]
        if updates:
            try:
                dev.updateStatesOnServer(updates)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"coordinator '{dev.name}' update")

    def _process_availability(self, friendly_name, payload):
        """Handle availability message — update the 'availability' state."""
        dev_id = self.friendly_name_map.get(friendly_name)
        if dev_id is None:
            return
        try:
            dev   = indigo.devices[dev_id]
            state = payload.get("state", "offline") if isinstance(payload, dict) else str(payload)
            dev.updateStateOnServer("availability", state, uiValue=state.capitalize())

            # For z2mRepeater devices mirror availability into onOffState so the
            # device list shows Online/Offline instead of the relay default On/Off.
            if dev.deviceTypeId == "z2mRepeater":
                is_online = (state == "online")
                dev.updateStateOnServer(
                    "onOffState", is_online,
                    uiValue="Online" if is_online else "Offline"
                )

            if self.debug:
                log(f"{dev.name}: availability = {state}")
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"availability update for '{friendly_name}'")

    def _process_device_state(self, friendly_name, payload):
        """Dispatch a device state payload to the type-specific handler."""
        dev_id = self.friendly_name_map.get(friendly_name)
        if dev_id is None:
            return  # unknown device or from another plugin/prefix
        if not isinstance(payload, dict):
            return
        try:
            dev = indigo.devices[dev_id]
        except Exception:
            return

        # Auto-reclassify: if any non-button device receives an action payload
        # (e.g. a TuYa button misidentified as relay by zigbee2mqtt), delete
        # the wrong device and recreate it as z2mButton automatically.
        if "action" in payload and payload["action"] not in (None, ""):
            if dev.deviceTypeId != "z2mButton" and self._should_reclassify_as_button(dev):
                self._reclassify_as_button(dev, payload)
                return

        type_id = dev.deviceTypeId
        if type_id == "z2mLight":
            self._process_light_state(dev, payload)
        elif type_id == "z2mRelay":
            self._process_relay_state(dev, payload)
        elif type_id == "z2mContactSensor":
            self._process_contact_sensor_state(dev, payload)
        elif type_id == "z2mOccupancySensor":
            self._process_occupancy_sensor_state(dev, payload)
        elif type_id == "z2mWaterLeakSensor":
            self._process_water_leak_sensor_state(dev, payload)
        elif type_id == "z2mTemperatureSensor":
            self._process_temperature_sensor_state(dev, payload)
        elif type_id == "z2mSensor":
            self._process_sensor_state(dev, payload)
        elif type_id == "z2mRepeater":
            self._process_repeater_state(dev, payload)
        elif type_id == "z2mCover":
            self._process_cover_state(dev, payload)
        elif type_id == "z2mButton":
            self._process_button_state(dev, payload)

        # After type-specific handling, capture any remaining payload fields as
        # dynamic states so all Z2M data is imported (not just the semantically-
        # mapped subset).  See _capture_raw_fields docstring.
        try:
            self._capture_raw_fields(dev, payload)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"{dev.name} raw-field capture")

    def _is_valid_state_id(self, key):
        """Indigo XML state IDs must start with an ASCII letter and contain only
        ASCII letters and digits.  Underscores are NOT accepted — Indigo's XML
        validator rejects them with LowLevelBadParameterError 'illegal XML tag
        name character' even though XML itself permits them.  Convention in the
        Indigo SDK is camelCase (linkQuality, colorMode, batteryLevel, etc.).
        """
        if not key or not key[0].isascii() or not key[0].isalpha():
            return False
        for c in key:
            if not (c.isascii() and c.isalnum()):
                return False
        return True

    def _process_light_state(self, dev, payload):
        """Update z2mLight device states from MQTT payload."""
        has_ct  = getattr(dev, "supportsWhiteTemperature", False)
        has_col = getattr(dev, "supportsColor", False)

        updates = []

        if "state" in payload:
            updates.append(("onOffState", str(payload["state"]).upper() == "ON"))

        # Each numeric block is guarded so one malformed field (a non-numeric or
        # null value from a flaky device) is skipped rather than raising and dropping
        # the WHOLE update batch (the exception otherwise propagates to runConcurrentThread).
        if "brightness" in payload:
            try:
                is_on = str(payload.get("state", "ON")).upper() == "ON"
                level = _brightness_255_to_100(int(payload["brightness"])) if is_on else 0
                updates.append(("brightnessLevel", level))
            except (ValueError, TypeError):
                pass

        if has_ct and "color_temp" in payload and payload["color_temp"] is not None:
            try:
                kelvin = _mireds_to_kelvin(int(payload["color_temp"]))
                updates.append(("whiteTemperature", kelvin))
                updates.append(("colorTemp", kelvin, f"{kelvin} K"))
            except (ValueError, TypeError):
                pass

        if "color_mode" in payload:
            cm = payload["color_mode"]
            if cm == "color_temp":
                updates.append(("colorMode", "color_temp", "Color Temp"))
            elif cm in ("xy", "hs"):
                updates.append(("colorMode", "color_rgb", "Color"))

        if has_col:
            color = payload.get("color", {})
            if isinstance(color, dict):
                try:
                    if "x" in color and "y" in color:
                        r, g, b = _xy_to_rgb(float(color["x"]), float(color["y"]))
                        updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])
                    elif "hue" in color and "saturation" in color:
                        r, g, b = _hs_to_rgb(float(color["hue"]), float(color["saturation"]))
                        updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])
                except (ValueError, TypeError):
                    pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_relay_state(self, dev, payload):
        """Update z2mRelay device states from MQTT payload."""
        updates = []

        if "state" in payload:
            updates.append(("onOffState", str(payload["state"]).upper() == "ON"))

        if "power" in payload:
            try:
                watts = float(payload["power"])
                updates.append(("power", watts, f"{watts:.1f} W"))
            except (ValueError, TypeError):
                pass

        if "energy" in payload:
            try:
                kwh = float(payload["energy"])
                updates.append(("energy", kwh, f"{kwh:.3f} kWh"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_contact_sensor_state(self, dev, payload):
        """Update z2mContactSensor device states from MQTT payload.

        contact=True  → door/window closed → onOffState=False  (sensor at rest)
        contact=False → door/window open   → onOffState=True   (sensor triggered)
        """
        updates = []

        if "contact" in payload:
            val     = bool(payload["contact"])
            is_open = not val
            updates.append(("contact",    val))
            updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_occupancy_sensor_state(self, dev, payload):
        """Update z2mOccupancySensor device states from MQTT payload.

        Both 'occupancy' (PIR) and 'presence' (mmWave) map to onOffState.
        Either being True sets onOffState=True so a fast PIR trigger is not lost.
        """
        updates = []

        # Motion-related keys that different sensors use under different names.
        # We track the last known value of every key a device has ever sent so
        # partial payloads (only one key changing) don't lose the other sensors' state.
        MOTION_KEYS = ("motion", "occupancy", "presence", "pir")

        store = self._motion_states.setdefault(dev.id, {})
        motion_updated = False
        for key in MOTION_KEYS:
            if key in payload:
                store[key] = bool(payload[key])
                motion_updated = True

        if motion_updated:
            detected = any(store.values())
            # Update named custom states for keys the device actually sends
            if "occupancy" in store:
                updates.append(("occupancy", store["occupancy"],
                                "Detected" if store["occupancy"] else "Clear"))
            if "presence" in store:
                updates.append(("presence",  store["presence"],
                                "Detected" if store["presence"]  else "Clear"))
            updates.append(("motion",     detected))
            updates.append(("onOffState", detected, "Detected" if detected else "Clear"))

            if self.debug:
                log(f"{dev.name}: motion store={store} -> detected={detected}")

        # Self-heal capability flags if payload contains data the stored flags deny.
        # This corrects devices created when exposes data was incomplete.
        props = dev.ownerProps
        heal = {}
        if "occupancy" in store and not props.get("has_pir",      False):
            heal["has_pir"]      = True
        if "presence"  in store and not props.get("has_presence", False):
            heal["has_presence"] = True
        if heal:
            new_props = dict(props)
            new_props.update(heal)
            dev.replacePluginPropsOnServer(new_props)
            log(f"{dev.name}: corrected capability flags: {heal}")

        if "illuminance_lux" in payload or "illuminance" in payload:
            try:
                raw = payload.get("illuminance_lux", payload.get("illuminance"))
                illum = round(float(raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_water_leak_sensor_state(self, dev, payload):
        """Update z2mWaterLeakSensor device states from MQTT payload.

        water_leak=True  → leak detected → onOffState=True
        water_leak=False → all clear     → onOffState=False
        """
        updates = []

        if "water_leak" in payload:
            leak = bool(payload["water_leak"])
            updates.append(("waterLeak",   leak))
            updates.append(("onOffState",  leak, "Leak!" if leak else "OK"))

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_temperature_sensor_state(self, dev, payload):
        """Update z2mTemperatureSensor device states from MQTT payload.

        Environmental sensor — no binary alarm state; onOffState is not used.
        """
        updates = []

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "pressure" in payload:
            try:
                pres = round(float(payload["pressure"]), 1)
                updates.append(("pressure", pres, f"{pres} hPa"))
            except (ValueError, TypeError):
                pass

        if "illuminance_lux" in payload or "illuminance" in payload:
            try:
                raw   = payload.get("illuminance_lux", payload.get("illuminance"))
                illum = round(float(raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_sensor_state(self, dev, payload):
        """Update z2mSensor device states from MQTT payload."""
        updates = []

        # Track which binary states are present for onOffState priority
        water_leak = None
        occupancy  = None
        contact    = None

        if "water_leak" in payload:
            val = bool(payload["water_leak"])
            water_leak = val
            updates.append(("waterLeak", val))

        # Handle motion/occupancy/presence — different sensors use different key names:
        #   "motion"     — Aqara FP300 and similar (fires on movement, clears quickly)
        #   "occupancy"  — PIR sensors (fast trigger, clears after timeout)
        #   "presence"   — mmWave/radar sensors (slower trigger, stays True while stationary)
        # Any of the three being True sets the Indigo motion state True.
        # Only clears when all present keys are False.
        motion_raw = payload.get("motion")
        occ_raw    = payload.get("occupancy")
        pres_raw   = payload.get("presence")
        if motion_raw is not None or occ_raw is not None or pres_raw is not None:
            combined = bool(motion_raw) or bool(occ_raw) or bool(pres_raw)
            occupancy = combined
            updates.append(("motion", combined))

        if "contact" in payload:
            # contact=True means closed (sensor active), contact=False means open
            val = bool(payload["contact"])
            contact = val
            updates.append(("contact", val))

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "pressure" in payload:
            try:
                pres = round(float(payload["pressure"]), 1)
                updates.append(("pressure", pres, f"{pres} hPa"))
            except (ValueError, TypeError):
                pass

        # Prefer illuminance_lux; fall back to illuminance
        illum_raw = payload.get("illuminance_lux", payload.get("illuminance"))
        if illum_raw is not None:
            try:
                illum = round(float(illum_raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        # Assign onOffState: priority waterLeak > occupancy/presence > contact
        if water_leak is not None:
            updates.append(("onOffState", water_leak, "Leak!" if water_leak else "OK"))
        elif occupancy is not None:
            updates.append(("onOffState", occupancy, "Detected" if occupancy else "Clear"))
        elif contact is not None:
            # contact=False means open (door/window open) -> sensor triggered -> onOffState=True
            is_open = not contact
            updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))

        self._apply_updates(dev, updates)

    def _process_repeater_state(self, dev, payload):
        """Update z2mRepeater device states from MQTT payload.

        Repeaters only report linkquality. onOffState is driven by availability,
        not by payload, so no onOffState update is made here.
        """
        updates = []
        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass
        self._apply_updates(dev, updates)

    def _should_reclassify_as_button(self, dev):
        """Guard for the auto-reclassify-to-button path. A non-button device should
        only be deleted + recreated as a button if it has NO primary output
        capability. A legitimate combo device — a dimmer, cover or switch that ALSO
        publishes scene 'action's on the same MQTT topic — must never be destroyed:
        that would lose all on/off/brightness/colour/position control and orphan
        every trigger, link and control-page reference to its device id.

        Re-check the device's CURRENT Z2M exposes (self.bridge_devices): reclassify
        only when there is no brightness, no position, no writable on/off state and
        no light/cover/switch composite. If the exposes can't be found, fall back to
        the conservative rule that only the catch-all sensor/repeater types may
        auto-convert (a relay keeps its relay device — recreate manually if needed).
        """
        if dev.deviceTypeId in ("z2mLight", "z2mCover"):
            return False
        props = dev.pluginProps
        ieee  = (props.get("ieee_address") or "").strip()
        fname = (props.get("friendly_name") or "").strip()
        data  = None
        for d in (self.bridge_devices or {}).values():
            if ((ieee and (d.get("ieee_address") or "").strip() == ieee)
                    or (fname and (d.get("friendly_name") or "").strip() == fname)):
                data = d
                break
        exposes = ((data or {}).get("definition") or {}).get("exposes") or []
        if not exposes:
            # No exposes to re-check — only the no-output catch-all types may convert.
            return dev.deviceTypeId in ("z2mSensor", "z2mRepeater")
        for entry in exposes:
            if entry.get("type") in ("light", "cover", "switch"):
                return False
        for feat in _iter_features(exposes):
            name = feat.get("name")
            if name in ("brightness", "position"):
                return False
            if (name == "state" and feat.get("type") == "binary"
                    and (feat.get("access", 0) & 2)):  # bit 1 = writable
                return False
        return True

    def _reclassify_as_button(self, dev, payload):
        """Delete a misclassified device and recreate it as z2mButton.

        Called when an action payload arrives on a non-button device —
        typically a TuYa/Ikea button that zigbee2mqtt fingerprinted as relay.
        After recreation the action is processed immediately on the new device.
        """
        action_val    = str(payload.get("action", ""))
        old_id        = dev.id
        dev_name      = dev.name
        folder_id     = dev.folderId
        friendly_name = dev.pluginProps.get("friendly_name", "")
        ieee_address  = dev.pluginProps.get("ieee_address", "")
        vendor        = dev.pluginProps.get("vendor", "")
        model         = dev.pluginProps.get("model", "")
        mqtt_prefix   = dev.pluginProps.get("mqtt_prefix", self._topic_prefix())

        log(f"Auto-reclassify: '{dev_name}' received action='{action_val}' "
            f"but is type '{dev.deviceTypeId}'. Recreating as Z2M Button...", level="WARNING")

        try:
            indigo.device.delete(dev)
        except Exception as e:
            log(f"Reclassify: could not delete '{dev_name}': {e}", level="ERROR")
            return

        # Remove stale mapping
        self.friendly_name_map = {
            k: v for k, v in self.friendly_name_map.items() if v != old_id
        }

        new_props = {
            "friendly_name":      friendly_name,
            "ieee_address":       ieee_address,
            "vendor":             vendor,
            "model":              model,
            "has_battery":        False,
            "capabilities_display": "button actions",
            "mqtt_prefix":        mqtt_prefix,
        }

        try:
            # Bug fix v1.9.9: _ensure_device_folder() requires the folder name —
            # was called with no argument here, crashing every reclassify of a
            # device that lived at the root level (folderId=0). Match the other
            # three call sites (discover_create_devices, create_coordinator_devices,
            # _process_bridge_devices) — all pass DEVICE_FOLDER_NAME.
            folder_id_to_use = folder_id if folder_id else self._ensure_device_folder(DEVICE_FOLDER_NAME)
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=dev_name,
                pluginId=self.pluginId,
                deviceTypeId="z2mButton",
                folder=folder_id_to_use,
                props=new_props,
            )
            self.friendly_name_map[friendly_name] = new_dev.id
            log(f"Reclassify complete: '{dev_name}' is now Z2M Button (id={new_dev.id})")
            self._process_button_state(new_dev, payload)
        except Exception as e:
            log(f"Reclassify: could not create button device '{dev_name}': {e}", level="ERROR")

    def _process_button_state(self, dev, payload):
        """Update z2mButton device states from MQTT action payload.

        action payloads are stateless events (e.g. {"action": "1_single"}).
        pressCount always increments so Indigo triggers fire even on repeated
        presses of the same button (lastAction alone would not change value).
        """
        updates = []

        if "action" in payload and payload["action"] not in (None, ""):
            action = str(payload["action"])

            # Extract button number: "1_single" → 1, "2_double" → 2, "on" → 0
            btn = 0
            try:
                btn = int(action.split("_")[0])
            except (ValueError, IndexError):
                pass

            # lastAction is a List enumeration (v1.9.12) — write the normalised
            # camelCase token so Indigo's auto-generated lastAction.<value>
            # boolean sub-states fire. The button index lives in lastButton.
            norm_action = self._normalise_action(action)

            current_count = dev.states.get("pressCount", 0)
            new_count = (int(current_count) % 9999) + 1

            updates.append(("lastAction",  norm_action, norm_action))
            updates.append(("lastButton",  btn,         str(btn)))
            updates.append(("pressCount",  new_count,   str(new_count)))
            updates.append(("onOffState",  True,        "Pressed"))

            if self.debug:
                log(f"{dev.name}: action={action!r} -> {norm_action!r} "
                    f"button={btn} count={new_count}")

        if "battery" in payload:
            try:
                batt = int(float(payload["battery"]))
                updates.append(("battery", batt, f"{batt}%"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_cover_state(self, dev, payload):
        """Update z2mCover device states from MQTT payload."""
        updates = []

        if "state" in payload:
            state_str = str(payload["state"]).upper()
            updates.append(("coverState", state_str.lower(), state_str.capitalize()))
            if state_str == "OPEN":
                updates.append(("onOffState", True, "Open"))
            elif state_str in ("CLOSE", "CLOSED"):
                updates.append(("onOffState", False, "Closed"))
            # STOP: leave onOffState unchanged

        if "position" in payload:
            try:
                pos = int(payload["position"])
                pos = max(0, min(100, pos))
                updates.append(("brightnessLevel", pos))
                # Sync onOffState with position if no explicit state key in this payload
                if "state" not in payload:
                    is_open = pos > 0
                    updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))
            except (ValueError, TypeError):
                pass

        if "tilt" in payload:
            try:
                tilt = int(payload["tilt"])
                updates.append(("tiltAngle", tilt, f"{tilt}%"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _apply_updates(self, dev, updates):
        """
        Apply a list of state update tuples to an Indigo device.
        Each tuple is (key, value) or (key, value, uiValue).
        Errors on individual states are caught and logged at debug level.
        """
        for item in updates:
            key, value = item[0], item[1]
            ui_value   = item[2] if len(item) > 2 else None
            try:
                if ui_value is not None:
                    dev.updateStateOnServer(key, value, uiValue=ui_value)
                else:
                    dev.updateStateOnServer(key, value)
            except Exception as e:
                if self.debug:
                    log(f"{dev.name}: could not update '{key}': {e}", level="WARNING")
        if self.debug and updates:
            log(f"{dev.name}: updated {[u[0] for u in updates]}")

    # ── Auto-create helpers ───────────────────────────────────────────────────

    def _ensure_device_folder(self, name):
        """Return id of named device folder, creating it if absent."""
        for folder in indigo.devices.folders:
            if folder.name == name:
                return folder.id
        new_folder = indigo.devices.folder.create(name)
        log(f"Created device folder: '{name}'")
        return new_folder.id

    def _build_plugin_props(self, device_type_id, device_data, definition, exposes):
        """Build the pluginProps dict for a new auto-created device."""
        props = {
            "friendly_name":         device_data.get("friendly_name", ""),
            "ieee_address":          device_data.get("ieee_address", ""),
            "vendor":                definition.get("vendor", ""),
            "model":                 definition.get("model", ""),
        }

        if device_type_id == "z2mLight":
            caps = _detect_light_capabilities(exposes)
            props.update(caps)
            props["SupportsColor"]            = caps["has_color"]
            props["SupportsWhiteTemperature"] = caps["has_color_temp"]
            props["SupportsRGB"]              = caps["has_color"]

        elif device_type_id == "z2mContactSensor":
            caps = _detect_contact_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mOccupancySensor":
            caps = _detect_occupancy_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mWaterLeakSensor":
            caps = _detect_water_leak_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mTemperatureSensor":
            caps = _detect_temperature_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mSensor":
            caps = _detect_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mRelay":
            caps = _detect_relay_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mRepeater":
            caps = {}  # no sensor capabilities — availability + linkQuality only

        elif device_type_id == "z2mCover":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_tilt": "tilt" in names}
            props.update(caps)

        elif device_type_id == "z2mButton":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_battery": "battery" in names}
            props.update(caps)

        else:
            caps = {}

        props["capabilities_display"] = _build_capabilities_display(device_type_id, props)
        return props

    # ── Light capability helpers ──────────────────────────────────────────────

    def exception_handler(self, exc, log_failing_statement=False, context=""):
        """Log an exception with full traceback. When log_failing_statement is
        True, also extract the actual source line that raised from the deepest
        traceback frame — invaluable when one device out of dozens triggers a
        failure and the bare message doesn't say which line in which method
        blew up. Modelled on autolog's exception_handler pattern.
        """
        import traceback
        tb = exc.__traceback__
        last_frame = None
        while tb is not None:
            last_frame = tb
            tb = tb.tb_next
        prefix = f"{context}: " if context else ""
        log(f"{prefix}{type(exc).__name__}: {exc}", level="ERROR")
        if log_failing_statement and last_frame is not None:
            fname    = last_frame.tb_frame.f_code.co_filename
            lineno   = last_frame.tb_lineno
            funcname = last_frame.tb_frame.f_code.co_name
            try:
                # encoding="utf-8" — Indigo's open() defaults to ASCII and
                # plugin source contains em-dashes (CLAUDE.md gotcha)
                with open(fname, encoding="utf-8") as f:
                    src_line = f.readlines()[lineno - 1].strip()
            except Exception:
                src_line = "(source unavailable)"
            short = fname.rsplit("/", 1)[-1]
            log(f"  at {short}:{lineno} in {funcname}() -> {src_line}", level="ERROR")
        log(traceback.format_exc(), level="ERROR")

    def _apply_indigo_subtype(self, dev):
        """Set dev.subType so Indigo, HomeKitLink-Siri and control pages get the
        right semantic class (icon + accessory kind). Dynamic for lights (colour
        capability) and for z2mSensor catch-all (inferred from capability flags).
        Static for everything else. Skips devices without a clean SDK match
        (z2mWaterLeakSensor, z2mRepeater, z2mButton, and mixed-capability z2mSensor).
        """
        target = None
        type_id = dev.deviceTypeId

        if type_id == "z2mLight":
            has_col = dev.pluginProps.get("has_color", False)
            target = (indigo.kDimmerDeviceSubType.ColorDimmer if has_col
                      else indigo.kDimmerDeviceSubType.Dimmer)
        elif type_id == "z2mRelay":
            target = indigo.kRelayDeviceSubType.Outlet
        elif type_id == "z2mContactSensor":
            target = indigo.kSensorDeviceSubType.DoorWindow
        elif type_id == "z2mOccupancySensor":
            target = indigo.kSensorDeviceSubType.Motion
        elif type_id == "z2mTemperatureSensor":
            target = indigo.kSensorDeviceSubType.Temperature
        elif type_id == "z2mCover":
            target = indigo.kDimmerDeviceSubType.Blind
        elif type_id == "z2mSensor":
            # Backfill: devices created before the specific sensor types existed
            # are still on the catch-all but their capability flags reveal which
            # specific subType they would have got under the v1.8.0 classifier.
            # Setting subType in place keeps the deviceId intact (no trigger /
            # control page breakage) while giving HomeKitLink-Siri the right
            # accessory routing. Mixed-capability sensors get no subType.
            props        = dev.pluginProps
            has_contact  = props.get("has_contact",    False)
            has_occ      = props.get("has_occupancy",  False)
            has_leak     = props.get("has_water_leak", False)
            has_env      = (props.get("has_temperature", False)
                            or props.get("has_humidity",    False)
                            or props.get("has_pressure",    False)
                            or props.get("has_illuminance", False))
            if has_contact and not has_occ and not has_leak:
                target = indigo.kSensorDeviceSubType.DoorWindow
            elif has_occ and not has_contact and not has_leak:
                target = indigo.kSensorDeviceSubType.Motion
            elif has_env and not has_contact and not has_occ and not has_leak:
                target = indigo.kSensorDeviceSubType.Temperature

        if target is not None and dev.subType != target:
            dev.subType = target
            dev.replaceOnServer()

    @staticmethod
    def _compute_light_native_flags(has_color, has_color_temp):
        # SupportsColor must be True for any lamp with colour OR CT — it's the
        # top-level prerequisite for both SupportsRGB and SupportsWhiteTemperature.
        # A CT-only bulb still needs SupportsColor=True or Indigo silently ignores
        # SupportsWhiteTemperature.
        return {
            "SupportsColor":            has_color or has_color_temp,
            "SupportsRGB":              has_color,
            "SupportsWhite":            has_color_temp,
            "SupportsWhiteTemperature": has_color_temp,
        }

    def _apply_light_capabilities(self, dev):
        """Set Indigo color capability flags from stored pluginProps (z2mLight only)."""
        props   = dev.pluginProps
        has_col = props.get("has_color",      False)
        has_ct  = props.get("has_color_temp", False)

        # If both flags are absent pluginProps is likely empty/unreadable — skip to
        # avoid clobbering existing capability flags with False values.
        if not has_col and not has_ct:
            return

        new_props = dict(props)
        new_props.update(self._compute_light_native_flags(has_col, has_ct))

        # Always call replacePluginPropsOnServer when capability data is present.
        # Indigo only propagates native attributes to the device via this call.
        dev.replacePluginPropsOnServer(new_props)
