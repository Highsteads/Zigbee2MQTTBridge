#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Zigbee2MQTT Bridge — general zigbee2mqtt device integration for Indigo.
#              Auto-discovers all device types (lights, relays, sensors, covers) from
#              the zigbee2mqtt bridge and creates matching Indigo devices in a
#              "Zigbee2MQTT" device folder via Plugins > Discover & Create Devices.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        13-04-2026
# Version:     1.5

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

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from secrets import MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD
except ImportError:
    MQTT_BROKER   = ""
    MQTT_PORT     = 1883
    MQTT_USERNAME = ""
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
PLUGIN_VERSION = "1.6"

RECONNECT_DELAY      = 30   # seconds between MQTT reconnect attempts
STATE_REQUEST_DELAY  = 2    # seconds after deviceStartComm before requesting state
DEVICE_FOLDER_NAME   = "Zigbee2MQTT"


# ── Pure helper functions (no Indigo dependency) ─────────────────────────────

def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", level=level)


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

        self.debug = pluginPrefs.get("showDebugInfo", False)

        # MQTT state
        self.mqtt_client    = None
        self.mqtt_connected = False
        self.mqtt_lock      = threading.Lock()

        # Message queue (paho callback -> main thread via runConcurrentThread)
        self.msg_queue = queue.Queue()

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

        # Per-device motion component states for occupancy sensors.
        # Stores last known bool for each motion-related key the device has ever sent
        # (motion, occupancy, presence, pir, ...).  Partial payloads only update the
        # keys they contain, so the OR across all stored values is always correct.
        self._motion_states = {}  # type: dict[int, dict[str, bool]]

        if log_startup_banner:
            _extras = [
                ("MQTT Broker:", f"{MQTT_BROKER or '(not set)'}:{MQTT_PORT or 1883}"),
                ("Topic Prefix:", pluginPrefs.get("mqtt_topic_prefix", "zigbee2mqtt")),
            ]
            _garage = pluginPrefs.get("mqtt_garage_topic_prefix", "").strip()
            if _garage:
                _extras.append(("Garage Prefix:", _garage))
            log_startup_banner(pluginId, pluginDisplayName, pluginVersion, extras=_extras)
        else:
            indigo.server.log(f"{pluginDisplayName} v{pluginVersion} starting")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def startup(self):
        log(f"{PLUGIN_NAME} starting up")
        self._start_mqtt()

    def shutdown(self):
        log(f"{PLUGIN_NAME} shutting down")
        self._stop_mqtt()

    def runConcurrentThread(self):
        """Drain the MQTT message queue on the Indigo main thread."""
        while True:
            try:
                while not self.msg_queue.empty():
                    topic, payload = self.msg_queue.get_nowait()
                    self._process_message(topic, payload)
            except Exception as e:
                log(f"runConcurrentThread error: {e}", level="ERROR")
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
        props = dev.pluginProps
        fname = props.get("friendly_name", "").strip()
        if not fname:
            log(f"Device '{dev.name}' has no friendly_name — skipping", level="WARNING")
            return

        self.friendly_name_map[fname] = dev.id
        ieee = props.get("ieee_address", "")
        if ieee:
            self.ieee_map[ieee] = dev.id

        # Apply stored color/capability flags to Indigo device
        if dev.deviceTypeId == "z2mLight":
            self._apply_light_capabilities(dev)

        # Ensure all custom states exist — guards against states added to Devices.xml
        # after a device was originally created (avoids "state key not defined" errors)
        self._ensure_device_states(dev)

        if self.debug:
            log(f"Started device: {dev.name} (type={dev.deviceTypeId}, name={fname})")

        # Request current state after brief delay (MQTT needs time to settle)
        prefix = self._device_prefix(dev)
        threading.Timer(STATE_REQUEST_DELAY, self._request_state, args=(fname, dev.deviceTypeId, prefix)).start()

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
    }

    def _ensure_device_states(self, dev):
        """Initialise any custom states that don't yet exist on this device.

        Guards against the 'state key not defined' race that occurs when states are
        added to Devices.xml after a device was originally created.  Called for every
        device at deviceStartComm time so the state slots always exist before any
        MQTT payload arrives.
        """
        defaults = self._DEVICE_STATE_DEFAULTS.get(dev.deviceTypeId)
        if not defaults:
            return  # unknown or native-only type — nothing to do

        existing = set(dev.states.keys())
        missing  = [(k, v) for k, v in defaults if k not in existing]
        if not missing:
            return

        log(f"{dev.name}: initialising {len(missing)} missing state(s): "
            f"{[k for k, _ in missing]}")
        for key, val in missing:
            try:
                dev.updateStateOnServer(key, val)
            except Exception as e:
                log(f"{dev.name}: could not initialise state '{key}': {e}",
                    level="WARNING")

    def deviceStopComm(self, dev):
        fname = dev.pluginProps.get("friendly_name", "")
        self.friendly_name_map.pop(fname, None)
        ieee = dev.pluginProps.get("ieee_address", "")
        self.ieee_map.pop(ieee, None)
        self._motion_states.pop(dev.id, None)
        if self.debug:
            log(f"Stopped device: {dev.name}")

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

    def actionControlUniversalDevices(self, action, dev):
        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kUniversalAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix)
        else:
            log(f"Unhandled universal action {cmd} for {dev.name}", level="WARNING")

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

    def refresh_bridge_devices(self, valuesDict=None, typeId=None):
        """Menu item: republish a get request for bridge/devices."""
        prefix = self._topic_prefix()
        self._publish(f"{prefix}/bridge/request/devices", {})
        garage = self._garage_prefix()
        if garage:
            self._publish(f"{garage}/bridge/request/devices", {})
        log("Requested device list refresh from MQTT bridge"
            + (f" (+ garage: {garage})" if garage else ""))

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
            ]
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion,
                               extras=_extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    # ── MQTT internals ────────────────────────────────────────────────────────

    def _effective_broker(self):
        return MQTT_BROKER or ""

    def _effective_port(self):
        return MQTT_PORT if MQTT_PORT else 1883

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
        username = MQTT_USERNAME
        password = MQTT_PASSWORD

        if not broker:
            log("MQTT broker not configured. Set MQTT_BROKER in secrets.py.", level="ERROR")
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
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return  # ignore non-JSON (e.g. binary bridge messages)
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
            if len(parts) >= 3 and parts[2] == "devices":
                self._process_bridge_devices(payload, effective_prefix)
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
            log(f"Availability update error for '{friendly_name}': {e}", level="ERROR")

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
            if dev.deviceTypeId != "z2mButton":
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

    def _process_light_state(self, dev, payload):
        """Update z2mLight device states from MQTT payload."""
        has_ct  = getattr(dev, "supportsWhiteTemperature", False)
        has_col = getattr(dev, "supportsColor", False)

        updates = []

        if "state" in payload:
            updates.append(("onOffState", str(payload["state"]).upper() == "ON"))

        if "brightness" in payload:
            raw   = payload["brightness"]
            is_on = str(payload.get("state", "ON")).upper() == "ON"
            level = _brightness_255_to_100(int(raw)) if is_on else 0
            updates.append(("brightnessLevel", level))

        if has_ct and "color_temp" in payload and payload["color_temp"] is not None:
            kelvin = _mireds_to_kelvin(int(payload["color_temp"]))
            updates.append(("whiteTemperature", kelvin))
            updates.append(("colorTemp", kelvin, f"{kelvin} K"))

        if "color_mode" in payload:
            cm = payload["color_mode"]
            if cm == "color_temp":
                updates.append(("colorMode", "color_temp", "Color Temp"))
            elif cm in ("xy", "hs"):
                updates.append(("colorMode", "color_rgb", "Color"))

        if has_col:
            color = payload.get("color", {})
            if isinstance(color, dict):
                if "x" in color and "y" in color:
                    r, g, b = _xy_to_rgb(float(color["x"]), float(color["y"]))
                    updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])
                elif "hue" in color and "saturation" in color:
                    r, g, b = _hs_to_rgb(float(color["hue"]), float(color["saturation"]))
                    updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])

        if "linkquality" in payload:
            lq = int(payload["linkquality"])
            updates.append(("linkQuality", lq, f"{lq} / 255"))

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
            lq = int(payload["linkquality"])
            updates.append(("linkQuality", lq, f"{lq} / 255"))

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
            folder_id_to_use = folder_id if folder_id else self._ensure_device_folder()
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

            current_count = dev.states.get("pressCount", 0)
            new_count = (int(current_count) % 9999) + 1

            updates.append(("lastAction",  action,     action))
            updates.append(("lastButton",  btn,        str(btn)))
            updates.append(("pressCount",  new_count,  str(new_count)))
            updates.append(("onOffState",  True,       "Pressed"))

            if self.debug:
                log(f"{dev.name}: action={action} button={btn} count={new_count}")

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
            lq = int(payload["linkquality"])
            updates.append(("linkQuality", lq, f"{lq} / 255"))

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
        # SupportsColor is the top-level flag — required as a prerequisite for both
        # SupportsRGB and SupportsWhite. Must be True for any lamp with colour or CT.
        new_props["SupportsColor"]            = has_col or has_ct
        new_props["SupportsRGB"]              = has_col
        # SupportsWhite must be True for SupportsWhiteTemperature to take effect
        # (Indigo silently ignores SupportsWhiteTemperature if SupportsWhite is False)
        new_props["SupportsWhite"]            = has_ct
        new_props["SupportsWhiteTemperature"] = has_ct

        # Always call replacePluginPropsOnServer when capability data is present.
        # Indigo only propagates native attributes to the device via this call.
        dev.replacePluginPropsOnServer(new_props)
