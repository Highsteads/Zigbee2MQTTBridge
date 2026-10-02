#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_secondary.py
# Description: Secondary devices — splitting a reading out of a multi-capability
#              device into its own Indigo device, grouped with its parent.
#
#              A presence sensor that also measures temperature, humidity and
#              light reports all of it into one device, where the readings sit
#              as custom states: no sensor subtype, nothing HomeKit can see,
#              and no obvious place on a control page. Nineteen devices on this
#              estate hide temperature, humidity and illuminance that way.
#
#              THIS IS ADDITIVE AND THAT IS THE POINT. The parent keeps its id,
#              its states and every trigger, script and control page pointing
#              at it. Nothing existing breaks, which is what makes this safe to
#              offer where delete-and-recreate never was.
# Author:      CliveS & Claude Opus 5
# Date:        15-08-2026
# Version:     1.0

from datetime import datetime

import z2m_helpers
from z2m_detection import _switch_layout

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


# Prefix for the per-reading opt-in stored on the PARENT device.
SECONDARY_PREFIX = "z2msec_"

# reading -> (device type id, human label, decimal places, ui suffix)
SECONDARY_TYPES = {
    "temperature": ("z2mTemperatureSecondary", "Temperature", 1, " °C"),
    "humidity":    ("z2mHumiditySecondary",    "Humidity",    1, "%"),
    "illuminance": ("z2mIlluminanceSecondary", "Illuminance", 0, " lx"),
    "pressure":    ("z2mPressureSecondary",    "Pressure",    1, " hPa"),
}

# A further channel of a multi-channel switch (2.12.0). Its "reading" is
# CHANNEL_PREFIX + the channel's endpoint name, e.g. "channel_l2".
CHANNEL_TYPE_ID = "z2mRelayChannel"
CHANNEL_PREFIX  = "channel_"

# The secondary device type ids, for "is this itself a secondary?" checks.
SECONDARY_TYPE_IDS = ({t for t, _l, _d, _s in SECONDARY_TYPES.values()}
                      | {CHANNEL_TYPE_ID})


def channel_label(endpoint):
    """How a channel is named to a person: l2 -> "L2", right -> "Right"."""
    text = str(endpoint)
    return text.upper() if len(text) <= 2 else text.title()


def secondary_label(reading):
    """The human label for a reading or a channel."""
    if reading.startswith(CHANNEL_PREFIX):
        return f"Channel {channel_label(reading[len(CHANNEL_PREFIX):])}"
    return SECONDARY_TYPES[reading][1]


def is_secondary(dev):
    """True for a secondary device.

    A secondary CARRIES its parent's friendly_name, ieee_address and
    mqtt_prefix, copied at creation, but it is not a radio. Anything that
    indexes, addresses or counts radios must skip it: registering it under
    those identities took the parent's MQTT routing over (2.11.0).
    """
    return getattr(dev, "deviceTypeId", None) in SECONDARY_TYPE_IDS

# Marker left on a secondary that has been switched off. It is renamed rather
# than deleted — see _remove_secondary.
UNGROUPED_MARKER = "[UNUSED"


class SecondaryDevicesMixin:
    """Secondary devices — see the file header above."""

    # ── What a parent can offer ──────────────────────────────────────────────

    def _offered_secondaries(self, dev):
        """Readings this device genuinely reports, in a stable order.

        Driven by the device's own `exposes`, NOT by whether a state currently
        holds a value. A state seeded to 0 looks like a reading and is not one —
        several sensors here show temperature 0.0 having never measured any —
        so offering by value would invite the user to split out a reading that
        will never arrive.
        """
        if dev.deviceTypeId in SECONDARY_TYPE_IDS or dev.deviceTypeId == "z2mCoordinator":
            return []
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        entry = self.bridge_devices.get(ieee) if ieee else None
        if not entry:
            return []
        reported = set()

        def walk(items):
            for feature in items or []:
                if feature.get("features"):
                    walk(feature["features"])
                    continue
                prop = feature.get("property")
                if prop in SECONDARY_TYPES and (feature.get("access", 0) or 0) & 1:
                    reported.add(prop)

        exposes = ((entry.get("definition") or {}).get("exposes")) or []
        walk(exposes)
        offered = [r for r in SECONDARY_TYPES if r in reported]
        if dev.deviceTypeId == "z2mRelay":
            offered += [CHANNEL_PREFIX + ep for ep in _switch_layout(exposes)[1]]
        return offered

    def _relay_state_key(self, dev):
        """The payload key this relay's own on/off lives under.

        "state" for an ordinary switch; "state_l1" (its first channel) for a
        multi-channel switch with no plain state (2.12.0). Read from the live
        bridge cache, so it is "state" until zigbee2mqtt's device list has
        arrived — which is also what was sent before 2.12.0.
        """
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        entry = self.bridge_devices.get(ieee) if ieee else None
        exposes = (((entry or {}).get("definition") or {}).get("exposes")) or []
        return _switch_layout(exposes)[0]

    @staticmethod
    def _secondary_key(reading):
        return SECONDARY_PREFIX + reading

    def _secondary_dev_id(self, dev, reading):
        """The id of the secondary for this reading, or None."""
        try:
            return int(dev.ownerProps.get(self._secondary_key(reading) + "_id") or 0) or None
        except (TypeError, ValueError):
            return None

    # ── Creating, grouping, retiring ─────────────────────────────────────────

    def _sync_secondaries(self, dev, values):
        """Make the secondaries match what the parent's dialog now says."""
        offered = self._offered_secondaries(dev)
        if not offered:
            return
        for reading in offered:
            wanted = str(values.get(self._secondary_key(reading)) or "").lower() \
                in ("true", "1", "yes", "on")
            existing = self._secondary_dev_id(dev, reading)
            if wanted and not existing:
                self._create_secondary(dev, reading)
            elif existing and not wanted:
                self._remove_secondary(dev, reading, existing)

    def _create_secondary(self, dev, reading):
        """Create the secondary device and group it with its parent."""
        label = secondary_label(reading)
        name = f"{dev.name} [{label}]"
        # Indigo refuses a duplicate name, and a clash here is entirely
        # plausible — the user may already have a device called this.
        existing_names = {d.name for d in indigo.devices}
        candidate, n = name, 2
        while candidate in existing_names:
            candidate = f"{name} {n}"
            n += 1
        props = {
            "primary_device_id": str(dev.id),
            "friendly_name": dev.ownerProps.get("friendly_name", ""),
            "ieee_address": dev.ownerProps.get("ieee_address", ""),
            "mqtt_prefix": dev.ownerProps.get("mqtt_prefix", ""),
            "secondary_reading": reading,
        }
        if reading.startswith(CHANNEL_PREFIX):
            type_id = CHANNEL_TYPE_ID
            props["channel_endpoint"] = reading[len(CHANNEL_PREFIX):]
        else:
            type_id = SECONDARY_TYPES[reading][0]
            # A native sensor only HAS sensorValue while this is True.
            # Without it every write is silently dropped and the device
            # shows nothing at all — the trap that left ShellyDirect's
            # sensor values dead for months.
            props["SupportsSensorValue"] = True
            props["SupportsOnState"] = False
        try:
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=candidate,
                deviceTypeId=type_id,
                folder=dev.folderId,
                props=props,
            )
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"creating {label} secondary for '{dev.name}'")
            return

        # Group it with the parent.
        #
        # Simon's controlled experiment (indigo-matter ADR-0009) found the root
        # of a group is its OLDEST member regardless of argument order, which
        # would make the parent the root here since a secondary is always
        # created after it. That is EXPECTED BUT UNVERIFIED on this server: the
        # obvious check — is the root the lowest device id? — turned out to be
        # meaningless, because Indigo ids are not sequential (69786879 sits
        # beside 1484056336), so "lowest id" says nothing about age. Root
        # matched the lowest id in 8 of 15 existing groups, which neither
        # confirms nor refutes it.
        #
        # It is not worth chasing, because the consequence either way is
        # cosmetic: if the parent is not the root, the group simply shows a
        # different member at the top of the device list. Nothing functional
        # depends on it, and grouping is best-effort below regardless.
        try:
            indigo.device.groupWithDevice(new_dev.id, dev.id)
        except Exception as e:
            log(f"{candidate} was created but could not be grouped with "
                f"{dev.name}: {e}. It still works; it just will not sit with "
                f"its parent in the device list.", level="WARNING")

        with self.props_lock:
            props = dict(dev.pluginProps)
            props[self._secondary_key(reading)] = True
            props[self._secondary_key(reading) + "_id"] = str(new_dev.id)
            dev.replacePluginPropsOnServer(props)
        log(f"{dev.name}: split {reading} out into '{candidate}'")

    def _remove_secondary(self, dev, reading, secondary_id):
        """Retire a secondary — ungroup and rename, NEVER delete.

        The user may have pointed a trigger, script or control page at it, and
        deleting it would break those silently. Renaming makes it obvious and
        leaves the decision where it belongs.
        """
        try:
            secondary = indigo.devices[secondary_id]
        except KeyError:
            secondary = None
        if secondary is not None:
            try:
                indigo.device.ungroupDevice(secondary)
                secondary.refreshFromServer()
            except Exception as e:
                log(f"Could not ungroup '{secondary.name}': {e}", level="WARNING")
            try:
                if UNGROUPED_MARKER not in secondary.name:
                    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    secondary.name = f"{secondary.name} {UNGROUPED_MARKER} {stamp}]"
                    secondary.replaceOnServer()
            except Exception as e:
                log(f"Could not rename the retired secondary: {e}", level="WARNING")
            log(f"{dev.name}: no longer splitting out {reading}. "
                f"'{secondary.name}' has been left in place rather than deleted, "
                f"in case something points at it — delete it yourself once you "
                f"are sure.", level="WARNING")

        with self.props_lock:
            props = dict(dev.pluginProps)
            props[self._secondary_key(reading)] = False
            props.pop(self._secondary_key(reading) + "_id", None)
            dev.replacePluginPropsOnServer(props)

    # ── Feeding them ─────────────────────────────────────────────────────────

    def _live_secondary(self, dev, reading):
        """The secondary device for this reading, or None.

        One deleted behind our back is forgotten rather than warned about for
        ever.
        """
        secondary_id = self._secondary_dev_id(dev, reading)
        if not secondary_id:
            return None
        try:
            return indigo.devices[secondary_id]
        except KeyError:
            with self.props_lock:
                props = dict(dev.pluginProps)
                props.pop(self._secondary_key(reading) + "_id", None)
                props[self._secondary_key(reading)] = False
                dev.replacePluginPropsOnServer(props)
            return None

    def _route_to_secondaries(self, dev, payload):
        """Copy a parent's readings out to whichever secondaries exist."""
        if not isinstance(payload, dict):
            return
        # Switch channels: state_<channel> -> that channel's own device (2.12.0).
        for key, raw in payload.items():
            if not (isinstance(key, str) and key.startswith("state_")) or raw is None:
                continue
            channel = self._live_secondary(dev, CHANNEL_PREFIX + key[len("state_"):])
            if channel is None:
                continue
            on = str(raw).upper() == "ON"
            self._apply_updates(channel, [
                ("onOffState", on, "on" if on else "off"),
                ("lastUpdate", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ])
        for reading, (_type_id, label, dp, suffix) in SECONDARY_TYPES.items():
            if reading not in payload:
                continue
            raw = payload.get(reading)
            if raw is None:
                continue          # null is no reading, not a zero
            secondary = self._live_secondary(dev, reading)
            if secondary is None:
                continue
            try:
                value = round(float(raw), dp) if dp else int(round(float(raw)))
            except (TypeError, ValueError):
                continue
            ui = f"{value}{suffix}"
            self._apply_updates(secondary, [
                (reading, value),
                ("lastUpdate", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ])
            try:
                secondary.updateStateOnServer("sensorValue", value, uiValue=ui,
                                              clearErrorState=False)
            except Exception as e:
                warn_key = (secondary.id, "sensorValue")
                if warn_key not in self._state_write_warned:
                    self._state_write_warned.add(warn_key)
                    log(f"{secondary.name}: could not write the sensor value "
                        f"({e}) — SupportsSensorValue may not be set",
                        level="WARNING")

    # ── Dialog ───────────────────────────────────────────────────────────────

    def getDeviceConfigUiXml(self, typeId, devId):
        base = super().getDeviceConfigUiXml(typeId, devId)
        try:
            dev = indigo.devices[devId]
            offered = self._offered_secondaries(dev)
            if not offered or "</ConfigUI>" not in (base or ""):
                return base
            from xml.sax.saxutils import escape
            parts = [
                '\n    <Field id="z2mSecSep" type="separator"/>',
                '    <Field id="z2mSecLabel" type="label" fontColor="darkgray">',
                '        <Label>Separate Devices — this device also has the '
                'readings or switch channels below. Tick one to give it its own '
                'Indigo device, grouped with this one, so it appears as a proper '
                'sensor or switch. This device keeps everything it already '
                'has.</Label>',
                '    </Field>',
            ]
            for reading in offered:
                label = secondary_label(reading)
                parts.append(f'    <Field id="{self._secondary_key(reading)}" '
                             f'type="checkbox" defaultValue="false">')
                parts.append(f'        <Label>{escape(label)}:</Label>')
                parts.append(f'        <Description>Give {escape(label.lower())} '
                             f'its own device</Description>')
                parts.append('    </Field>')
            return base.replace("</ConfigUI>", "\n".join(parts) + "\n</ConfigUI>", 1)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context="secondary-device ConfigUI")
            return base

    def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
        super().closedDeviceConfigUi(valuesDict, userCancelled, typeId, devId)
        if userCancelled:
            return
        try:
            dev = indigo.devices[devId]
        except Exception:
            return
        try:
            self._sync_secondaries(dev, valuesDict)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"syncing secondaries for '{dev.name}'")

