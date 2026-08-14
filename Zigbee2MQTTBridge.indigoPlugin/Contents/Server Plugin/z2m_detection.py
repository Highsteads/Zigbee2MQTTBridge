#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_detection.py
# Description: Device-type classification and capability detection, driven entirely
#              by a device's zigbee2mqtt `exposes` definition. This is the layer
#              the device zoo tests exercise against real captured payloads.
#              Extracted from plugin.py in v2.2.0 — it had reached 5,238 lines
#              and every new feature made it worse. Behaviour is unchanged; the
#              names are re-exported from plugin.py so existing imports and the
#              test suite keep working.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

from z2m_helpers import _iter_features

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

    # Drop malformed (non-dict) entries once, so the direct top-level loops
    # below can't crash on a junk element (v1.9.22 — _iter_features already
    # skips them, but `for entry in exposes` does not).
    exposes = [e for e in exposes if isinstance(e, dict)]
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

    # Check for Thermostat/TRV (composite type "climate") — v1.10.0. Checked
    # BEFORE cover so a TRV's valve-position leaf can never reach the cover
    # rule, and before lock/button/relay so climate always wins.
    for entry in exposes:
        if entry.get("type") == "climate":
            return "z2mThermostat"

    # Check for Lock (composite type "lock") — v1.10.0. Before the button and
    # relay checks: a lock's writable binary state (LOCK/UNLOCK) would
    # otherwise classify as z2mRelay and be sent ON/OFF.
    for entry in exposes:
        if entry.get("type") == "lock":
            return "z2mLock"

    # Check for Cover (composite type "cover", or a WRITABLE flat "position"
    # feature outside a climate composite). The writability + no-climate gates
    # (v1.9.21) stop TRVs being created as blinds: Tuya/Moes TRVs expose a
    # read-only valve-position percentage, and treating that as a cover sends
    # OPEN/CLOSE commands at a radiator valve. A genuine flat-expose cover's
    # position is writable (access bit 1).
    for entry in exposes:
        if entry.get("type") == "cover":
            return "z2mCover"
    if not any(entry.get("type") == "climate" for entry in exposes):
        for feat in _iter_features(exposes):
            if feat.get("name") == "position" and (feat.get("access", 0) & 2):
                return "z2mCover"

    # Check for Button/Scene controller (has "action" enum feature — TuYa TS0042, Ikea remotes etc.)
    # TWO gates before we accept the button classification:
    # 1. Not when the device reports presence/occupancy/motion/pir: on such
    #    sensors the `action` enum carries region/presence events (enter/leave/
    #    occupied), not scene-controller presses — the sensor is the primary
    #    type. Without this the Aqara FP1 (RTCZCGQ11LM: presence + action) was
    #    mis-classified as a button and lost its presence semantics (v1.9.17).
    # 2. Not when the device has an output capability (switch composite or
    #    writable binary state): a decoupled-mode wall switch or scene-capable
    #    relay must be created as z2mRelay or its load can never be switched
    #    from Indigo (v1.9.21 — mirrors _should_reclassify_as_button, which
    #    already refused to CONVERT such a device but couldn't undo a wrong
    #    creation). Its scene presses surface via the dynamic `action` state.
    _btn_names = {feat.get("name") for feat in _iter_features(exposes)}
    if not (_btn_names & {"presence", "occupancy", "motion", "pir"}):
        _has_output = any(entry.get("type") == "switch" for entry in exposes) or any(
            feat.get("name") == "state" and feat.get("type") == "binary"
            and (feat.get("access", 0) & 2)
            for feat in _iter_features(exposes)
        )
        if not _has_output:
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
        "has_smoke":        "smoke"        in names,
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
