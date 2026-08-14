#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_actions.py
# Description: Every Indigo action callback — the actionControlXxx family (each device
#              class has its OWN action attribute) plus the Actions.xml handlers.
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

import json

from z2m_helpers import _brightness_100_to_255, _kelvin_to_mireds


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


class ActionsMixin:
    """See the file header above."""

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

        # Repeaters take no commands — their onOffState mirrors availability.
        # Publishing a /set used to log apparent success at a device that
        # ignores it (v1.9.23). Status requests are still allowed.
        if (dev.deviceTypeId == "z2mRepeater"
                and cmd != indigo.kDeviceAction.RequestStatus):
            log(f"{dev.name} is a repeater — it takes no on/off commands "
                f"(its state mirrors availability)", level="WARNING")
            return

        # Locks speak LOCK/UNLOCK, not ON/OFF (v1.10.0). Indigo's lock/unlock
        # UI arrives here as TurnOn/TurnOff on the relay class.
        if dev.deviceTypeId == "z2mLock":
            if cmd == indigo.kDeviceAction.TurnOn:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "LOCK"},
                                  dev, "lock")
            elif cmd == indigo.kDeviceAction.TurnOff:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "UNLOCK"},
                                  dev, "unlock")
            elif cmd == indigo.kDeviceAction.Toggle:
                new_state = "UNLOCK" if dev.onState else "LOCK"
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state},
                                  dev, new_state.lower())
            elif cmd == indigo.kDeviceAction.RequestStatus:
                self._request_state(fname, dev.deviceTypeId, prefix,
                                    dev_props=dict(dev.pluginProps))
                log(f'sent "{dev.name}" status request')
            else:
                log(f"Unhandled lock action {cmd} for {dev.name}", level="WARNING")
            return

        if cmd == indigo.kDeviceAction.TurnOn:
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": "ON"}, dev, "on")
        elif cmd == indigo.kDeviceAction.TurnOff:
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OFF"}, dev, "off")
        elif cmd == indigo.kDeviceAction.Toggle:
            new_state = "OFF" if dev.onState else "ON"
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state}, dev,
                              f"toggle -> {new_state.lower()}")
        elif cmd == indigo.kDeviceAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
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
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OPEN"}, dev, "open")
            else:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "ON"}, dev, "on")

        elif cmd == indigo.kDimmerRelayAction.TurnOff:
            if is_cover:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "CLOSE"}, dev, "close")
            else:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OFF"}, dev, "off")

        elif cmd == indigo.kDimmerRelayAction.Toggle:
            if is_cover:
                new_state = "CLOSE" if dev.onState else "OPEN"
            else:
                new_state = "OFF" if dev.onState else "ON"
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state}, dev,
                              f"toggle -> {new_state.lower()}")

        elif cmd == indigo.kDimmerRelayAction.SetBrightness:
            level = action.actionValue  # 0-100
            if is_cover:
                self._publish_cmd(f"{prefix}/{fname}/set", {"position": level}, dev,
                                  f"set position to {level}%")
            else:
                brightness = _brightness_100_to_255(level)
                payload = {"brightness": brightness, "state": "ON" if level > 0 else "OFF"}
                self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                                  f"set brightness to {level}%")

        elif cmd in (indigo.kDimmerRelayAction.BrightenBy, indigo.kDimmerRelayAction.DimBy):
            current = dev.brightness
            delta   = action.actionValue
            if cmd == indigo.kDimmerRelayAction.BrightenBy:
                new_level = min(100, current + delta)
            else:
                new_level = max(0, current - delta)
            if is_cover:
                verb = "open" if cmd == indigo.kDimmerRelayAction.BrightenBy else "close"
                self._publish_cmd(f"{prefix}/{fname}/set", {"position": new_level}, dev,
                                  f"{verb} by {delta}% -> {new_level}%")
            else:
                brightness = _brightness_100_to_255(new_level)
                payload = {"brightness": brightness, "state": "ON" if new_level > 0 else "OFF"}
                verb = "brighten" if cmd == indigo.kDimmerRelayAction.BrightenBy else "dim"
                self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                                  f"{verb} by {delta}% -> {new_level}%")

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
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"color_temp": mireds, "state": "ON"}, dev,
                                  f"set color temp to {kelvin}K")
            elif all(k in color_vals for k in ("redLevel", "greenLevel", "blueLevel")):
                r = int(round(float(color_vals["redLevel"])   / 100.0 * 255))
                g = int(round(float(color_vals["greenLevel"]) / 100.0 * 255))
                b = int(round(float(color_vals["blueLevel"])  / 100.0 * 255))
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"color": {"r": r, "g": g, "b": b}, "state": "ON"}, dev,
                                  f"set color RGB ({r}, {g}, {b})")
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
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
        elif cmd == indigo.kUniversalAction.EnergyUpdate:
            # Re-poll rather than invent a value — z2m answers on the state topic.
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
        elif cmd == indigo.kUniversalAction.EnergyReset:
            # The kWh counter lives on the Zigbee device and cannot be reset
            # from here, so rebase Indigo's accumulator against the current
            # raw reading instead.  Writing accumEnergyTotal to 0.0 on its own
            # would be undone by the next payload.
            raw = self._coerce_meter_value(dev.states.get("energy"))
            if raw is None:
                log(f"{dev.name}: cannot reset the energy total — no energy "
                    f"reading has arrived from zigbee2mqtt yet", level="WARNING")
                return
            self._set_energy_offset(dev, raw)
            self._write_native_state(dev, "accumEnergyTotal", 0.0, "0.000 kWh",
                                     just_enabled=False)
            log(f"{dev.name}: energy total reset — Indigo now counts from the "
                f"device's current {raw:.3f} kWh reading")
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
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled sensor action {cmd} for {dev.name} "
                f"(sensors are read-only)", level="WARNING")

    def actionControlThermostat(self, action, dev):
        """Handle thermostat-class device actions for z2mThermostat (v1.10.0).

        NOTE: thermostat actions arrive via action.thermostatAction (each device
        class has its OWN action attribute — .deviceAction raises here).
        Setpoints publish the z2m key stored in the device's setpoint_key prop
        (current_heating_setpoint by default; some TRVs use occupied_).
        """
        cmd    = action.thermostatAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        sp_key = dev.pluginProps.get("setpoint_key", "current_heating_setpoint")

        def _current_setpoint():
            try:
                return float(dev.states.get("setpointHeat", 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        if cmd == indigo.kThermostatAction.SetHeatSetpoint:
            try:
                sp = round(float(action.actionValue), 1)
            except (TypeError, ValueError):
                log(f"{dev.name}: invalid heat setpoint value", level="ERROR")
                return
            self._publish_cmd(f"{prefix}/{fname}/set", {sp_key: sp}, dev,
                              f"set heat setpoint to {sp}")
        elif cmd in (indigo.kThermostatAction.IncreaseHeatSetpoint,
                     indigo.kThermostatAction.DecreaseHeatSetpoint):
            try:
                delta = float(action.actionValue)
            except (TypeError, ValueError):
                delta = 1.0
            if cmd == indigo.kThermostatAction.DecreaseHeatSetpoint:
                delta = -delta
            sp = round(_current_setpoint() + delta, 1)
            self._publish_cmd(f"{prefix}/{fname}/set", {sp_key: sp}, dev,
                              f"set heat setpoint to {sp}")
        elif cmd == indigo.kThermostatAction.SetHvacMode:
            mode_map = {}
            try:
                mode_map = {indigo.kHvacMode.Heat:     "heat",
                            indigo.kHvacMode.HeatCool: "auto",
                            indigo.kHvacMode.Off:      "off"}
            except Exception:
                pass
            z2m_mode = mode_map.get(action.actionMode)
            if z2m_mode:
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"system_mode": z2m_mode}, dev,
                                  f"set mode {z2m_mode}")
            else:
                log(f"{dev.name}: HVAC mode {action.actionMode} not supported "
                    f"(heat/auto/off only)", level="WARNING")
        elif cmd in (indigo.kThermostatAction.RequestStatusAll,
                     indigo.kThermostatAction.RequestTemperatures,
                     indigo.kThermostatAction.RequestSetpoints,
                     indigo.kThermostatAction.RequestMode):
            self._request_state(fname, dev.deviceTypeId, prefix,
                                dev_props=dict(dev.pluginProps))
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled thermostat action {cmd} for {dev.name} "
                f"(cooling is not supported on z2m TRVs)", level="WARNING")

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
        self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))

    def action_publish_custom(self, action, dev=None, callerWaitingForResult=None):
        """Action: publish a user-supplied JSON payload to this device's /set
        topic (v1.10.0) — the escape hatch for device options the typed actions
        don't cover (sensitivity, LED modes, calibration, child lock...). Uses
        z2m's snake_case property names, e.g. {"motion_sensitivity": "high"}."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        raw = (action.props.get("json_payload") or "").strip()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except (ValueError, TypeError) as e:
            log(f"{dev.name}: custom payload is not valid JSON ({e}): {raw!r}",
                level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                          f"custom payload {payload}")

    def validateActionConfigUi(self, valuesDict, typeId, deviceId):
        """Validate action dialogs at save time (v1.10.0 — the custom-publish
        JSON gets checked here instead of failing at run time)."""
        errors = indigo.Dict()
        if typeId == "publishCustom":
            raw = (valuesDict.get("json_payload") or "").strip()
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("must be a JSON object, e.g. {\"key\": \"value\"}")
            except (ValueError, TypeError) as e:
                errors["json_payload"] = f"Not a valid JSON object: {e}"
        return (len(errors) == 0), valuesDict, errors
