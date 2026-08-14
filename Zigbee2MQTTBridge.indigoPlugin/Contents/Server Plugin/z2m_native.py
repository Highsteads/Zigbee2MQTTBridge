#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_native.py
# Description: Mirrors into Indigo's native battery and energy-meter attributes, and the
#              one-time state-list refresh that registers states added to
#              Devices.xml after a device was created.
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


class NativeAttributesMixin:
    """See the file header above."""

    # ── Native Indigo attribute mirrors (v2.1.0) ─────────────────────────────
    # Indigo carries first-class battery and energy-meter attributes that are
    # entirely separate from any custom state, and a device only gets them when
    # the matching Supports* property is True — the same conditional
    # inheritance that governs sensorValue and onOffState.  Until v2.1.0 this
    # plugin set neither, so every battery-powered Zigbee device was invisible
    # to Indigo's own low-battery reporting (and to anything reading
    # dev.batteryLevel), while metering plugs never reached the Energy UI.
    #
    # The custom `battery` / `power` / `energy` states are KEPT — other plugins
    # read them — and both the custom state and the native attribute are
    # written from the SAME call, so each fact still has exactly one writer.

    @staticmethod
    def _coerce_battery_percent(raw):
        """Return an int 0-100, or None when the payload holds no usable reading.

        None must never become 0.  A flat battery and an absent reading are
        different facts, and reporting the absent one as 0 would raise a false
        low-battery alert on a device that simply hasn't said yet.  Booleans
        are rejected for the same reason — True would otherwise coerce to 1%.
        """
        if raw is None or isinstance(raw, bool):
            return None
        try:
            pct = int(round(float(raw)))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, pct))

    @staticmethod
    def _coerce_meter_value(raw):
        """Return a float for a power/energy reading, or None if unusable.

        zigbee2mqtt publishes a null for these fields after a restart, which is
        an absent reading rather than a genuine zero.
        """
        if raw is None or isinstance(raw, bool):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _enable_native_prop(self, dev, prop_name):
        """Turn a native Supports* property on once.

        Returns True only when this call was the one that set it, so the caller
        can tell a first-time enable (where the native state may not exist yet)
        from steady state.
        """
        if dev.pluginProps.get(prop_name, False):
            return False
        with self.props_lock:   # atomic RMW vs the other props writers
            new_props = dict(dev.pluginProps)
            new_props[prop_name] = True
            dev.replacePluginPropsOnServer(new_props)
        try:
            dev.refreshFromServer()
        except Exception:
            pass   # stale local copy only — the next payload picks it up
        return True

    def _write_native_state(self, dev, key, value, ui_value, just_enabled):
        """Write a native attribute, tolerating the first write after enabling.

        Indigo materialises the native state as a side effect of the property
        change, so the very first write can land before it exists.  That one is
        expected and is not worth a warning; anything after it is real and is
        surfaced once per (device, key).
        """
        try:
            dev.updateStateOnServer(key, value, uiValue=ui_value)
            return True
        except Exception as e:
            if just_enabled:
                if self.debug:
                    log(f"{dev.name}: native '{key}' not ready on first write "
                        f"({e}) — the next payload will carry it")
                return False
            warn_key = (dev.id, f"native:{key}")
            if warn_key not in self._state_write_warned:
                self._state_write_warned.add(warn_key)
                log(f"{dev.name}: could not update native '{key}': {e}",
                    level="WARNING")
            return False

    def _mirror_native_battery(self, dev, raw):
        """Mirror a battery percentage into Indigo's native batteryLevel."""
        pct = self._coerce_battery_percent(raw)
        if pct is None:
            return
        just_enabled = self._enable_native_prop(dev, "SupportsBatteryLevel")
        if just_enabled:
            log(f"{dev.name}: native battery reporting enabled — this device "
                f"now appears in Indigo's own low-battery list")
        self._write_native_state(dev, "batteryLevel", pct, f"{pct}%", just_enabled)

    def _mirror_native_energy(self, dev, power_w=None, energy_kwh=None):
        """Mirror power/energy into Indigo's native energy-meter attributes.

        `curEnergyLevel` is instantaneous watts and maps straight across.
        `accumEnergyTotal` is Indigo's own accumulator, which the user can
        reset — but zigbee2mqtt reports a counter held on the device, which
        this plugin cannot reset.  The gap is bridged by storing the raw
        reading taken at the moment of the last reset in `energyResetOffset`
        and reporting the difference.  Without that, an Energy Reset action
        would appear to work and then be undone by the very next payload.
        """
        watts = self._coerce_meter_value(power_w)
        kwh   = self._coerce_meter_value(energy_kwh)
        if watts is None and kwh is None:
            return

        just_enabled = False
        if watts is not None:
            just_enabled |= self._enable_native_prop(dev, "SupportsEnergyMeterCurPower")
        if kwh is not None:
            just_enabled |= self._enable_native_prop(dev, "SupportsEnergyMeter")
        if just_enabled:
            log(f"{dev.name}: native energy metering enabled — this device now "
                f"reports into Indigo's Energy UI")

        if watts is not None:
            self._write_native_state(dev, "curEnergyLevel", round(watts, 1),
                                     f"{watts:.1f} W", just_enabled)
        if kwh is not None:
            offset = self._coerce_meter_value(
                dev.pluginProps.get("energyResetOffset")) or 0.0
            if kwh < offset:
                # The device's own counter has gone backwards — a factory reset
                # or firmware reflash.  Holding the old offset would report a
                # negative total for ever, so drop it and start again from here.
                log(f"{dev.name}: zigbee2mqtt energy counter went backwards "
                    f"({kwh} < stored offset {offset}) — the device's own "
                    f"counter was reset, so the Indigo accumulator baseline "
                    f"has been cleared")
                self._set_energy_offset(dev, 0.0)
                offset = 0.0
            total = max(0.0, kwh - offset)
            self._write_native_state(dev, "accumEnergyTotal", round(total, 3),
                                     f"{total:.3f} kWh", just_enabled)

    # States added to Devices.xml after a device was created do NOT appear on
    # that device until its cached state list is refreshed.  Indigo rejects the
    # write SERVER-side and logs "state key <k> not defined (ignoring update
    # request)" — it does not raise, so a try/except around the write sees
    # nothing and the state silently never populates.  Live-hit on the v2.1.0
    # health states: 20 devices logged three errors each and the coordinator
    # populated nothing at all (its updater filters on `k in dev.states`, so it
    # dropped them without even that).
    _V210_HEALTH_STATES = ("messagesPerSec", "leaveCount", "networkAddressChanges")
    _V210_COORDINATOR_STATES = ("healthOsMemoryPercent", "healthLastUpdate",
                                "lastEvent")

    def _refresh_state_list_if_missing(self, dev, required_keys):
        """Re-register the device's state list when a declared state is absent.

        Returns the device to keep using — refreshed if the list was rebuilt,
        since the local copy is stale immediately afterwards.
        """
        missing = [k for k in required_keys if k not in dev.states]
        if not missing:
            return dev
        try:
            dev.stateListOrDisplayStateIdChanged()
            dev.refreshFromServer()
            log(f"{dev.name}: registered {len(missing)} new state(s) added in "
                f"this version ({', '.join(missing)})")
        except Exception as e:
            log(f"{dev.name}: could not refresh the state list for "
                f"{', '.join(missing)}: {e}", level="WARNING")
        return dev

    def _backfill_native_attributes(self, dev):
        """Seed the native attributes at deviceStartComm from stored states.

        Battery devices report every few hours, so without this an existing
        install would populate only as each device happened to speak up.

        A stored battery of exactly 0 is SKIPPED.  _ensure_device_states seeds
        the custom `battery` state to 0, so 0 cannot be told apart from a
        device that has never reported — and of the two ways to be wrong,
        announcing a false flat battery is much the worse.  A genuinely flat
        device corrects itself on its next payload.
        """
        try:
            battery = self._coerce_battery_percent(dev.states.get("battery"))
            if battery:
                self._mirror_native_battery(dev, battery)
            elif battery == 0 and self.debug:
                log(f"{dev.name}: stored battery is 0 — skipping the native "
                    f"backfill, since a never-reported battery reads the same")

            power  = self._coerce_meter_value(dev.states.get("power"))
            energy = self._coerce_meter_value(dev.states.get("energy"))
            if power is not None or energy is not None:
                self._mirror_native_energy(dev, power, energy)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"native backfill for '{dev.name}'")

    def _set_energy_offset(self, dev, value):
        """Store the raw zigbee2mqtt energy reading that means 'zero' from now on."""
        with self.props_lock:
            new_props = dict(dev.pluginProps)
            new_props["energyResetOffset"] = float(value)
            dev.replacePluginPropsOnServer(new_props)
        try:
            dev.refreshFromServer()
        except Exception:
            pass
