#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_state_processing.py
# Description: Per-device-type payload handlers. One method per Indigo device type, each
#              turning a zigbee2mqtt state payload into Indigo state writes, plus
#              availability and the button reclassification guard.
#
#              A mixin on Plugin, extracted in v2.2.0 when plugin.py had grown
#              past 5,000 lines. `self` is the Plugin instance throughout, so
#              class attributes and the other mixins' methods resolve through
#              the MRO exactly as they did before the split.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import z2m_helpers

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None

from z2m_constants import DEVICE_FOLDER_NAME
from z2m_helpers import (
    _brightness_255_to_100, _hs_to_rgb, _iter_features, _mireds_to_kelvin,
    _payload_bool, _xy_to_rgb,
)


# `log` is a LATE-BOUND delegate, deliberately not `from z2m_helpers import log`.
# A direct import binds the function object once at import time, so patching it
# in one module would leave every other module still calling the original — the
# split's first attempt broke 15 tests on exactly that. Resolving the attribute
# on each call keeps z2m_helpers as the single owner of logging, and therefore
# the single place to patch.
def log(*args, **kwargs):
    # Transparent pass-through: forward EXACTLY what the caller passed. Naming
    # the parameters here would turn `log(msg)` into a two-positional call,
    # which silently breaks anything that patches log with a narrower
    # signature — and a patched logger that raises TypeError is a confusing
    # way to discover a refactor changed a call shape.
    return z2m_helpers.log(*args, **kwargs)


class StateProcessingMixin:
    """See the file header above."""

    def _process_availability(self, friendly_name, payload, prefix=None):
        """Handle availability message — update the 'availability' state.
        Lookup is prefix-qualified (v1.9.22) so a name shared across the two
        bridges resolves to the right device."""
        if prefix is None:
            prefix = self._topic_prefix()
        dev_id = self.friendly_name_map.get((prefix, friendly_name))
        if dev_id is None:
            return
        try:
            dev   = indigo.devices[dev_id]
            state = payload.get("state", "offline") if isinstance(payload, dict) else str(payload)
            dev.updateStateOnServer("availability", state, uiValue=state.capitalize())

            is_online = (state == "online")

            # For z2mRepeater devices mirror availability into onOffState so the
            # device list shows Online/Offline instead of the relay default On/Off.
            if dev.deviceTypeId == "z2mRepeater":
                dev.updateStateOnServer(
                    "onOffState", is_online,
                    uiValue="Online" if is_online else "Offline"
                )

            # Mirror offline into Indigo's own error state (v2.1.0), which turns
            # the device red in the UI and is what DeviceHealthMonitor judges
            # health by.  Until now an offline Zigbee device looked perfectly
            # healthy to every other plugin on the server.
            #
            # This is zigbee2mqtt's own verdict after its configured timeout,
            # not our guess, so it is a real fault and not a quiet battery
            # device.  It is set LAST because updateStateOnServer clears the
            # error state by default — and that default is right: a device
            # that publishes anything is, by definition, not offline.
            try:
                if is_online:
                    if dev.errorState:
                        dev.setErrorStateOnServer(None)
                        log(f"{dev.name}: back online")
                elif dev.errorState != "offline":
                    dev.setErrorStateOnServer("offline")
                    log(f"{dev.name}: zigbee2mqtt reports this device offline",
                        level="WARNING")
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"error state for '{dev.name}'")

            if self.debug:
                log(f"{dev.name}: availability = {state}")
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"availability update for '{friendly_name}'")

    def _process_device_state(self, friendly_name, payload, prefix=None):
        """Dispatch a device state payload to the type-specific handler.
        Lookup is prefix-qualified (v1.9.22) so a name shared across the two
        bridges routes each bridge's payloads to its own device."""
        if prefix is None:
            prefix = self._topic_prefix()
        dev_id = self.friendly_name_map.get((prefix, friendly_name))
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
        # the wrong device and recreate it as z2mButton automatically. Require a
        # NAMED action (one carrying a letter) — a bare button index like "2" or
        # other junk carries no button semantics and must not drive a destructive
        # delete+recreate (the exposes guard below is the primary protection).
        action_val = payload.get("action")
        if (action_val not in (None, "") and any(c.isalpha() for c in str(action_val))
                and dev.deviceTypeId != "z2mButton"
                and self._should_reclassify_as_button(dev)):
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
        elif type_id == "z2mLock":
            self._process_lock_state(dev, payload)
        elif type_id == "z2mThermostat":
            self._process_thermostat_state(dev, payload)

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
                # Keep the two native states consistent: a dimmer at 0 brightness is
                # OFF in Indigo's model. Some bulbs briefly publish {"state":"ON",
                # "brightness":0} during a fade-to-off, which would otherwise leave
                # onOffState ON while the level reads 0. This append wins over the
                # state-derived onOffState above (updates apply in order).
                if level == 0:
                    updates.append(("onOffState", False))
            except (ValueError, TypeError):
                pass

        if has_ct and "color_temp" in payload and payload["color_temp"] is not None:
            try:
                kelvin = _mireds_to_kelvin(int(payload["color_temp"]))
                updates.append(("whiteTemperature", kelvin))
                updates.append(("colorTemp", kelvin, f"{kelvin} K"))
            except (ValueError, TypeError):
                pass

        # colorMode only means something on a bulb with CT or colour — writing
        # it unconditionally surfaced the state on plain dimmers, which the
        # capability gate in _ensure_device_states deliberately hides (v1.9.23).
        if "color_mode" in payload and (has_col or has_ct):
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
            val = _payload_bool(payload["contact"])   # "false"/"OFF" tokens safe
            if val is not None:
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
                val = _payload_bool(payload[key])   # string tokens safe
                if val is not None:
                    store[key] = val
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
            with self.props_lock:   # atomic RMW vs menu-thread refresh
                new_props = dict(dev.ownerProps)   # re-read under the lock
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
            leak = _payload_bool(payload["water_leak"])   # string tokens safe
            if leak is not None:
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
        smoke      = None
        water_leak = None
        occupancy  = None
        contact    = None

        if "smoke" in payload:
            # Life-safety: smoke detectors classify as the generic sensor type,
            # so the alarm is surfaced here (declared `smoke` state + top
            # onOffState priority). _payload_bool handles the string tokens
            # ("false"/"OFF") a non-conforming device might publish — a raw
            # bool() would read those as True.
            val = _payload_bool(payload["smoke"])
            if val is not None:
                smoke = val
                updates.append(("smoke", val, "Smoke!" if val else "OK"))

        if "water_leak" in payload:
            val = _payload_bool(payload["water_leak"])   # string tokens safe
            if val is not None:
                water_leak = val
                updates.append(("waterLeak", val))

        # Handle motion/occupancy/presence — different sensors use different key names:
        #   "motion"     — Aqara FP300 and similar (fires on movement, clears quickly)
        #   "occupancy"  — PIR sensors (fast trigger, clears after timeout)
        #   "presence"   — mmWave/radar sensors (slower trigger, stays True while stationary)
        #   "pir"        — some combo sensors expose the raw PIR channel under this name
        # Track the last-known value of every motion key in self._motion_states
        # (same store pattern as _process_occupancy_sensor_state) so a PARTIAL
        # payload (only one key changing) ORs against the others rather than
        # clearing them. Without the store a mixed PIR+mmWave device that lands on
        # this catch-all type drops a still-present person whenever one component
        # key updates on its own. Only clears when ALL known keys are False.
        store = self._motion_states.setdefault(dev.id, {})
        motion_updated = False
        for key in ("motion", "occupancy", "presence", "pir"):
            if key in payload:
                val = _payload_bool(payload[key])   # string tokens safe
                if val is not None:
                    store[key] = val
                    motion_updated = True
        if motion_updated:
            combined = any(store.values())
            occupancy = combined
            updates.append(("motion", combined))

        if "contact" in payload:
            # contact=True means closed (sensor active), contact=False means open
            val = _payload_bool(payload["contact"])   # string tokens safe
            if val is not None:
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

        # Assign onOffState: priority smoke > waterLeak > occupancy/presence > contact
        if smoke is not None:
            updates.append(("onOffState", smoke, "Smoke!" if smoke else "OK"))
        elif water_leak is not None:
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
        only when there is no presence/occupancy, no brightness, no position, no
        writable on/off state and no light/cover/switch composite. If the exposes
        can't be found, fall back to the conservative rule that only the catch-all
        sensor/repeater types may auto-convert (a relay keeps its relay device —
        recreate manually if needed).
        """
        if dev.deviceTypeId in ("z2mLight", "z2mCover", "z2mLock", "z2mThermostat"):
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
        exposes = [e for e in exposes if isinstance(e, dict)]
        if not exposes:
            # No exposes to re-check — only the no-output catch-all types may convert.
            return dev.deviceTypeId in ("z2mSensor", "z2mRepeater")
        # A presence/occupancy sensor must NEVER be reclassified as a button: on
        # such a device the `action` enum carries region/presence events
        # (enter/leave/occupied), not scene-controller presses. This mirrors the
        # same gate in _detect_device_type (added v1.9.17). Without it,
        # _reclassify_as_button DELETES the live occupancy device and recreates it
        # as a button — orphaning its id and every trigger/link referencing it.
        # The Aqara FP1 (RTCZCGQ11LM) emits region `action` events and hit exactly
        # this path. The detection-time gate alone was not enough — the runtime
        # reclassify guard had drifted out of sync with it.
        # motion/pir included since v1.9.21: a motion sensor with a named action
        # channel is a motion sensor first, same as presence/occupancy devices.
        feat_names = {feat.get("name") for feat in _iter_features(exposes)}
        if feat_names & {"presence", "occupancy", "motion", "pir"}:
            return False
        for entry in exposes:
            if entry.get("type") in ("light", "cover", "switch", "lock", "climate"):
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

        # Remove stale mappings — BOTH friendly_name_map and ieee_map point at the
        # now-deleted old_id; leaving ieee_map stale makes rename detection resolve
        # the deleted device id. Under maps_lock: the comprehension rebuild iterates
        # the dict, so a concurrent deviceStopComm pop would otherwise RuntimeError.
        with self.maps_lock:
            self.friendly_name_map = {
                k: v for k, v in self.friendly_name_map.items() if v != old_id
            }
            self.ieee_map = {
                k: v for k, v in self.ieee_map.items() if v != old_id
            }

        # Derive has_battery from the device's CURRENT exposes instead of
        # hardcoding False (v1.9.23): buttons are battery devices almost by
        # definition, and the flag never healed afterwards (buttons have no
        # capability detector, so Refresh Device Capabilities skips them).
        has_battery = False
        for d in (self.bridge_devices or {}).values():
            if ((ieee_address and (d.get("ieee_address") or "").strip() == ieee_address)
                    or (friendly_name and (d.get("friendly_name") or "").strip() == friendly_name)):
                exp = ((d.get("definition") or {}).get("exposes")) or []
                has_battery = any(f.get("name") == "battery"
                                  for f in _iter_features(exp))
                break

        new_props = {
            "friendly_name":      friendly_name,
            "ieee_address":       ieee_address,
            "vendor":             vendor,
            "model":              model,
            "has_battery":        has_battery,
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
            with self.maps_lock:
                self.friendly_name_map[(mqtt_prefix, friendly_name)] = new_dev.id
                if ieee_address:
                    self.ieee_map[ieee_address] = new_dev.id
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

    def _process_lock_state(self, dev, payload):
        """Update z2mLock device states from MQTT payload (v1.10.0).

        z2m locks report `state` ("LOCK"/"UNLOCK") and the richer `lock_state`
        enum (locked / unlocked / not_fully_locked). onOffState follows the
        Indigo convention: ON = locked. lock_state wins over state when both
        are present — it reflects the bolt, not the last command.
        """
        updates = []
        locked = None

        if "state" in payload:
            token = str(payload["state"]).strip().upper()
            if token in ("LOCK", "LOCKED", "ON"):
                locked = True
            elif token in ("UNLOCK", "UNLOCKED", "OFF"):
                locked = False

        if "lock_state" in payload:
            ls = str(payload["lock_state"]).strip().lower()
            updates.append(("lockState", ls))
            if ls == "locked":
                locked = True
            elif ls in ("unlocked", "not_fully_locked"):
                locked = False

        if locked is not None:
            updates.append(("onOffState", locked,
                            "Locked" if locked else "Unlocked"))

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

    def _process_thermostat_state(self, dev, payload):
        """Update z2mThermostat (TRV) device states from MQTT payload (v1.10.0).

        Maps z2m climate fields to Indigo's native thermostat states:
        local_temperature -> temperatureInput1, current/occupied_heating_setpoint
        -> setpointHeat, system_mode -> hvacOperationMode. running_state and the
        (read-only) valve `position` land in custom states.
        """
        updates = []

        if "local_temperature" in payload:
            try:
                temp = round(float(payload["local_temperature"]), 1)
                updates.append(("temperatureInput1", temp, f"{temp} °C"))
            except (ValueError, TypeError):
                pass

        setpoint_raw = payload.get("current_heating_setpoint",
                                   payload.get("occupied_heating_setpoint"))
        if setpoint_raw is not None:
            try:
                sp = round(float(setpoint_raw), 1)
                updates.append(("setpointHeat", sp, f"{sp} °C"))
            except (ValueError, TypeError):
                pass

        if "system_mode" in payload:
            mode = str(payload["system_mode"]).strip().lower()
            hvac = {"heat": indigo.kHvacMode.Heat,
                    "auto": indigo.kHvacMode.HeatCool,
                    "off":  indigo.kHvacMode.Off}.get(mode)
            if hvac is not None:
                updates.append(("hvacOperationMode", hvac))

        if "running_state" in payload:
            updates.append(("runningState",
                            str(payload["running_state"]).strip().lower()))

        if "position" in payload:
            try:
                pos = int(payload["position"])
                updates.append(("valvePosition", pos, f"{pos} %"))
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
                # Always visible (v1.9.23): a swallowed write failure is
                # silent data loss — but only ONCE per (device, key) so a
                # persistently-failing state can't spam the log every payload.
                warn_key = (dev.id, key)
                if warn_key not in self._state_write_warned:
                    self._state_write_warned.add(warn_key)
                    log(f"{dev.name}: could not update state '{key}': {e} "
                        f"(further failures for this state logged at debug "
                        f"only)", level="WARNING")
                elif self.debug:
                    log(f"{dev.name}: could not update '{key}': {e}", level="WARNING")

        # Mirror into Indigo's native attributes from this same write path, so
        # the custom state and the native one can never disagree (v2.1.0).
        by_key = {item[0]: item[1] for item in updates}
        try:
            if "battery" in by_key:
                self._mirror_native_battery(dev, by_key["battery"])
            if "power" in by_key or "energy" in by_key:
                self._mirror_native_energy(dev, by_key.get("power"),
                                           by_key.get("energy"))
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"native mirror for '{dev.name}'")

        if self.debug and updates:
            log(f"{dev.name}: updated {[u[0] for u in updates]}")
