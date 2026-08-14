#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_menus.py
# Description: Plugins-menu callbacks: discovery, coordinator creation, capability
#              refresh, the orphan and network-health reports, pairing and the
#              diagnostic banner.
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

import os as _os
import sys as _sys
import time

_sys.path.insert(0, _os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None

from z2m_constants import DEVICE_FOLDER_NAME
from z2m_detection import (
    _build_capabilities_display, _detect_contact_sensor_capabilities,
    _detect_device_type, _detect_light_capabilities,
    _detect_occupancy_sensor_capabilities, _detect_relay_capabilities,
    _detect_sensor_capabilities, _detect_temperature_sensor_capabilities,
    _detect_water_leak_sensor_capabilities,
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


class MenusMixin:
    """See the file header above."""

    # ── Menu callbacks ────────────────────────────────────────────────────────

    def _get_existing_friendly_names(self):
        """Return a set of (mqtt_prefix, friendly_name) for all active devices
        owned by this plugin. Prefix-qualified (v1.9.22) so a name reused on the
        other bridge doesn't block that bridge's device from being created."""
        names = set()
        for dev in indigo.devices.iter(self.pluginId):
            fn = dev.pluginProps.get("friendly_name", "")
            if fn:
                names.add((self._device_prefix(dev), fn))
        return names

    def _try_create_device(self, device_data, folder_id, existing_names):
        """Attempt to create a single Indigo device from Z2M device_data.

        Returns one of: 'created', 'exists', 'coordinator', 'no_definition', 'error'.
        existing_names is a set of (prefix, friendly_name) tuples, updated
        in-place when a device is successfully created.
        """
        fname  = device_data.get("friendly_name", "")
        d_type = device_data.get("type", "")
        d_prefix = device_data.get("_mqtt_prefix", self._topic_prefix())

        if d_type == "Coordinator":
            return "coordinator"
        if (d_prefix, fname) in existing_names:
            return "exists"

        definition = device_data.get("definition")
        if definition is None:
            log(f"  skip (not yet interviewed by z2m): {fname}", level="WARNING")
            return "no_definition"

        try:
            # Detection/props-build INSIDE the guard (v1.9.22): a malformed or
            # schema-shifted definition used to raise out of these helpers and
            # abort the WHOLE Discover & Create pass / auto-create batch — one
            # bad device must cost only itself.
            exposes        = definition.get("exposes", [])
            device_type_id = _detect_device_type(exposes, model=definition.get("model", ""))
            plugin_props   = self._build_plugin_props(device_type_id, device_data, definition, exposes)
            plugin_props["mqtt_prefix"] = device_data.get("_mqtt_prefix", self._topic_prefix())
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
            existing_names.add((d_prefix, fname))  # prevent duplicate creation within same pass
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

        # Index bridge cache by both ieee and (prefix, friendly_name) for fast
        # lookup — the fname fallback is prefix-qualified (v1.9.22) so a name
        # shared across the two bridges can't resolve to the wrong entry.
        by_ieee = {}
        by_fname = {}
        for d in self.bridge_devices.values():
            ieee = (d.get("ieee_address") or "").strip()
            fn   = (d.get("friendly_name") or "").strip()
            if ieee:
                by_ieee[ieee] = d
            if fn:
                by_fname[(d.get("_mqtt_prefix", self._topic_prefix()), fn)] = d

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
                data = by_fname.get((self._device_prefix(dev), fname))

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

            # Backfill power_source onto devices created before v2.2.0 stored
            # it. Only when zigbee2mqtt actually reports one — writing an empty
            # string would look like a deliberate "unknown" rather than an
            # absent field, and the mains check reads it either way.
            reported_source = data.get("power_source")
            if reported_source:
                target["power_source"] = reported_source

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
                    # Merge ONLY the diff keys onto a fresh read under the props
                    # lock — the consumer thread may have written seenDynamicKeys
                    # between this loop's earlier read and now, and replacing
                    # with the stale full dict would silently drop that (v1.9.23).
                    with self.props_lock:
                        fresh = dict(indigo.devices[dev.id].pluginProps)
                        for k, _old, new_val in diffs:
                            fresh[k] = new_val
                        dev.replacePluginPropsOnServer(fresh)
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

    def _banner_extras(self):
        """One source of truth for the diagnostic banner lines — used by both
        showPluginInfo and Test MQTT Connection (estate convention)."""
        z2m_count = sum(1 for _ in indigo.devices.iter(self.pluginId))
        rx_age = time.time() - self.last_rx_ts
        extras = [
            ("MQTT Broker:", f"{self._effective_broker()}:{self._effective_port()}"),
            ("Topic Prefix:", self._topic_prefix()),
        ]
        garage = self._garage_prefix()
        if garage:
            extras.append(("Garage Prefix:", garage))
        extras += [
            ("MQTT Status:", "connected" if self.mqtt_connected else "disconnected"),
            ("Last Message:", f"{rx_age:.0f}s ago"),
            ("Queue Depth:", str(self.msg_queue.qsize())),
            ("Silence Limit:", f"{self._silence_limit()}s"),
            ("Bridge Devices Cached:", str(len(self.bridge_devices))),
            ("Z2M Indigo Devices:", str(z2m_count)),
            ("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"),
        ]
        return extras

    def showPluginInfo(self, valuesDict=None, typeId=None):
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion,
                               extras=self._banner_extras())
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    def testMqttConnection(self, valuesDict=None, typeId=None):
        """Menu: full banner + live connection checks in one log dump (estate
        convention — exactly what a user pastes into a forum support post).
        v1.10.0."""
        # Always dump the full banner first so the environment and the test
        # result land together.
        self.showPluginInfo()
        problems = []
        if not self._effective_broker():
            problems.append("no broker configured (IndigoSecrets.MQTT_BROKER "
                            "or the config dialog)")
        if self.mqtt_client is None:
            problems.append("MQTT client not started")
        if not self.mqtt_connected:
            problems.append("not connected to the broker")
        rx_age = time.time() - self.last_rx_ts
        if self.mqtt_connected and rx_age > self._silence_limit():
            problems.append(f"connected but silent for {rx_age:.0f}s "
                            f"(limit {self._silence_limit()}s)")
        for prefix in (p for p in (self._topic_prefix(), self._garage_prefix()) if p):
            state = self._bridge_state_cache.get(prefix)
            if state and state != "online":
                problems.append(f"bridge '{prefix}' reports {state}")
            elif state is None:
                problems.append(f"no bridge/state seen yet from '{prefix}'")
        if problems:
            for p in problems:
                self.logger.error(f"Connection test FAILED — {p}")
        else:
            self.logger.info("Connection test PASSED — broker connected, "
                             "traffic flowing, all bridges online")

    def report_orphaned_devices(self, valuesDict=None, typeId=None):
        """Menu: list Indigo devices this plugin owns whose z2m device no
        longer exists in the bridge cache (removed/re-paired in z2m). Report
        only — never deletes (v1.10.0)."""
        if not self.bridge_devices:
            log("No bridge device data yet — wait for MQTT or run "
                "'Refresh Device List from MQTT' first.", level="WARNING")
            return
        known_ieee  = {ieee for ieee in self.bridge_devices}
        known_fname = {(d.get("_mqtt_prefix", self._topic_prefix()),
                        (d.get("friendly_name") or "").strip())
                       for d in self.bridge_devices.values()}
        orphans = []
        for dev in indigo.devices.iter(self.pluginId):
            if dev.deviceTypeId == "z2mCoordinator":
                continue
            ieee  = (dev.pluginProps.get("ieee_address") or "").strip()
            fname = (dev.pluginProps.get("friendly_name") or "").strip()
            key   = (self._device_prefix(dev), fname)
            if ieee and ieee in known_ieee:
                continue
            if ieee and ieee in self._coordinator_ieees:
                continue   # the bridge's own radio — excluded from the cache by design
            if not ieee and key in known_fname:
                continue
            orphans.append((dev.name, ieee or "-", fname or "-"))
        if not orphans:
            log(f"No orphaned devices — all {sum(1 for _ in indigo.devices.iter(self.pluginId))} "
                f"plugin devices match the bridge cache")
            return
        log(f"{len(orphans)} orphaned device(s) — in Indigo but no longer known "
            f"to zigbee2mqtt (removed/re-paired?). Review and delete manually "
            f"if genuinely gone:", level="WARNING")
        for name, ieee, fname in sorted(orphans):
            log(f"  {name}  (ieee={ieee}, friendly_name={fname})", level="WARNING")

    def report_network_health(self, valuesDict=None, typeId=None):
        """Menu: dump what bridge/health last reported for each bridge (v2.1.0).

        Sorted worst-first on the counters that matter — a device that keeps
        rejoining or hopping network address is the one causing trouble, and
        neither fact is visible anywhere else in Indigo.
        """
        if not self._health_cache:
            log("No health data yet. zigbee2mqtt publishes bridge/health every "
                "10 minutes by default — wait for the next report, or check "
                "'health' is enabled in the zigbee2mqtt configuration.",
                level="WARNING")
            return

        for prefix, devices in sorted(self._health_cache.items()):
            dev_id = self.coordinator_map.get(prefix)
            header = f"Network health for '{prefix}'"
            if dev_id:
                try:
                    coord = indigo.devices[dev_id]
                    header += (f" — z2m up {coord.states.get('healthProcessUptime', '?')}, "
                               f"host memory {coord.states.get('healthOsMemoryPercent', '?')}%, "
                               f"MQTT queue {coord.states.get('healthMqttQueued', '?')} "
                               f"(reported {coord.states.get('healthLastUpdate', '?')})")
                except KeyError:
                    pass
            log(header)

            rows = []
            for ieee, record in devices.items():
                with self.maps_lock:
                    indigo_id = self.ieee_map.get(ieee)
                try:
                    name = indigo.devices[indigo_id].name if indigo_id else f"[{ieee}]"
                except KeyError:
                    name = f"[{ieee}]"
                rows.append((int(record.get("leave_count") or 0),
                             int(record.get("network_address_changes") or 0),
                             name))

            flagged = [r for r in rows if r[0] or r[1]]
            if not flagged:
                log(f"  All {len(rows)} device(s) steady — no rejoins and no "
                    f"network address changes since zigbee2mqtt started")
                continue
            log(f"  {len(flagged)} of {len(rows)} device(s) have rejoined or "
                f"moved since zigbee2mqtt started:", level="WARNING")
            for leaves, changes, name in sorted(rows, reverse=True):
                if not leaves and not changes:
                    continue
                log(f"    {name}: {leaves} rejoin(s), {changes} address change(s)",
                    level="WARNING")

    def permit_join_enable(self, valuesDict=None, typeId=None):
        """Menu: open both bridges for pairing (254s, z2m's maximum window).
        The coordinator tile's permitJoin state confirms it took (v1.10.0)."""
        for prefix in (p for p in (self._topic_prefix(), self._garage_prefix()) if p):
            if self._publish(f"{prefix}/bridge/request/permit_join", {"time": 254}):
                log(f"Permit join ENABLED on '{prefix}' for 254s — new devices "
                    f"can now pair")

    def permit_join_disable(self, valuesDict=None, typeId=None):
        """Menu: close both bridges to pairing immediately (v1.10.0)."""
        for prefix in (p for p in (self._topic_prefix(), self._garage_prefix()) if p):
            if self._publish(f"{prefix}/bridge/request/permit_join", {"time": 0}):
                log(f"Permit join DISABLED on '{prefix}'")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")
