#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_ota.py
# Description: Firmware updates — surfacing what zigbee2mqtt already knows about
#              each device's firmware, asking it to check, and starting an
#              update when the user explicitly asks for one.
#
#              NOTHING HERE UPDATES A DEVICE ON ITS OWN, and that is deliberate.
#              A Zigbee OTA takes many minutes, runs over a battery-powered
#              radio link, and a failed one can leave a device unusable. It is
#              a decision for a person who knows the device is reachable and
#              can afford it to be busy — never a side effect of a poll.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import z2m_helpers

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


# zigbee2mqtt publishes an `update` object inside the device's own state topic:
#   {"update": {"state": "idle"|"available"|"updating",
#               "installed_version": N, "latest_version": N,
#               "progress": N, "remaining": N,
#               "latest_release_notes": "...", "latest_source": "..."}}
#
# `update_available` is a separate top-level field that z2m 2.x leaves as null —
# measured on this estate — so `update.state` is the authoritative signal and
# the old field is deliberately ignored.
STATE_IDLE      = "idle"
STATE_AVAILABLE = "available"
STATE_UPDATING  = "updating"


class OtaMixin:
    """Firmware update reporting and explicit, user-driven updates."""

    # ── Reading what z2m already tells us ────────────────────────────────────

    def _process_update_object(self, dev, update):
        """Turn a device's `update` object into states, and raise the event.

        Version numbers are opaque integers chosen by the manufacturer, so
        `installed != latest` is NOT a reliable "update available" test — some
        devices report a latest that equals installed while still saying idle,
        and others number their builds in ways that do not compare. z2m has
        already done this work, so trust `state` and use the versions for
        display only.
        """
        if not isinstance(update, dict):
            return
        state = str(update.get("state") or "").strip().lower()
        if not state:
            return

        previous = dev.states.get("updateState")
        updates = [
            ("updateState", state),
            ("updateAvailable", state == STATE_AVAILABLE),
        ]
        for key, prop in (("updateInstalledVersion", "installed_version"),
                          ("updateLatestVersion", "latest_version")):
            value = update.get(prop)
            if value is not None:
                updates.append((key, str(value)))
        if state == STATE_UPDATING:
            progress = update.get("progress")
            if progress is not None:
                try:
                    updates.append(("updateProgress", float(progress)))
                except (TypeError, ValueError):
                    pass
        self._apply_updates(dev, updates)

        # Fire on the RISING EDGE only. This object rides along with ordinary
        # state payloads, so a device with an update pending republishes
        # "available" every few minutes — firing each time would turn one
        # pending update into a trigger storm.
        if state == STATE_AVAILABLE and previous != STATE_AVAILABLE:
            log(f"{dev.name}: a firmware update is available "
                f"(installed {update.get('installed_version')}, "
                f"latest {update.get('latest_version')})")
            self._fire_event("otaUpdateAvailable", self._device_prefix(dev), dev.name)

    # ── Asking zigbee2mqtt to look ───────────────────────────────────────────

    def _ota_supported(self, dev):
        """True only when zigbee2mqtt says this device's definition supports OTA."""
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        entry = self.bridge_devices.get(ieee) if ieee else None
        definition = (entry or {}).get("definition") or {}
        return bool(definition.get("supports_ota"))

    def check_firmware_updates(self, valuesDict=None, typeId=None):
        """Menu: ask each bridge to check every OTA-capable device it owns.

        Checking is read-only — it asks the device what version it holds and
        compares against the online index. It does not install anything.
        """
        checked = skipped = 0
        for dev in indigo.devices.iter(self.pluginId):
            if dev.deviceTypeId == "z2mCoordinator":
                continue
            ieee = (dev.ownerProps.get("ieee_address") or "").strip()
            if not ieee:
                continue
            if not self._ota_supported(dev):
                skipped += 1
                continue
            prefix = self._device_prefix(dev)
            if self._publish(f"{prefix}/bridge/request/device/ota_update/check",
                             {"id": ieee}):
                checked += 1
        if not checked:
            log(f"No firmware checks sent — {skipped} device(s) do not support "
                f"over-the-air updates and none that do were reachable.",
                level="WARNING")
            return
        log(f"Asked zigbee2mqtt to check {checked} device(s) for firmware "
            f"updates ({skipped} do not support it). Replies arrive over the "
            f"next few minutes and land on each device's update states — "
            f"battery devices answer only when they next wake.")

    def report_firmware_status(self, valuesDict=None, typeId=None):
        """Menu: what the plugin currently knows about each device's firmware."""
        rows = []
        for dev in indigo.devices.iter(self.pluginId):
            if dev.deviceTypeId == "z2mCoordinator":
                continue
            if not self._ota_supported(dev):
                continue
            rows.append((dev.states.get("updateState") or "unknown", dev.name,
                         dev.states.get("updateInstalledVersion") or "?",
                         dev.states.get("updateLatestVersion") or "?"))
        if not rows:
            log("No devices report over-the-air update support.", level="WARNING")
            return
        pending = [r for r in rows if r[0] == STATE_AVAILABLE]
        log(f"Firmware: {len(rows)} device(s) support updates, "
            f"{len(pending)} with one available")
        for state, name, installed, latest in sorted(rows):
            level = "WARNING" if state == STATE_AVAILABLE else "INFO"
            log(f"  {name}: {state} (installed {installed}, latest {latest})",
                level=level)
        if not pending:
            return
        log("  To install one: right-click the device, Zigbee2MQTT Bridge -> "
            "Update Device Firmware. Do it when the device can be busy for a "
            "few minutes — an interrupted update can leave it unusable.")

    # ── Starting an update, only ever on request ─────────────────────────────

    def action_update_firmware(self, action, dev=None, callerWaitingForResult=None):
        """Action: start an OTA update for one device.

        Guarded rather than trusting the caller: an update fired at a device
        that cannot take one is the expensive mistake here.
        """
        if dev is None:
            log("Update Device Firmware: no device given", level="ERROR")
            return
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        if not ieee:
            log(f"{dev.name}: no IEEE address stored — cannot start a firmware "
                f"update", level="ERROR")
            return
        if not self._ota_supported(dev):
            log(f"{dev.name}: zigbee2mqtt reports this device does not support "
                f"over-the-air updates — nothing sent", level="ERROR")
            return
        state = dev.states.get("updateState")
        if state == STATE_UPDATING:
            log(f"{dev.name}: an update is already running — leaving it alone",
                level="WARNING")
            return
        if state != STATE_AVAILABLE:
            log(f"{dev.name}: no update is available (state is {state or 'unknown'}) "
                f"— run Check for Firmware Updates first", level="WARNING")
            return
        prefix = self._device_prefix(dev)
        if self._publish(f"{prefix}/bridge/request/device/ota_update/update",
                         {"id": ieee}):
            log(f"{dev.name}: firmware update started. It can take several "
                f"minutes and the device will be unresponsive meanwhile — do "
                f"not power it off.", level="WARNING")

    # ── Replies from zigbee2mqtt ─────────────────────────────────────────────

    def _process_ota_response(self, action, payload, prefix):
        """Handle bridge/response/device/ota_update/{check,update}."""
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "").lower()
        data = payload.get("data") or {}
        who = data.get("id") or "?"
        with self.maps_lock:
            dev_id = self.ieee_map.get(who)
        name = who
        if dev_id is not None:
            try:
                name = indigo.devices[dev_id].name
            except KeyError:
                pass
        if status == "error":
            log(f"{name}: firmware {action} failed — "
                f"{payload.get('error') or 'no reason given'}", level="ERROR")
            return
        if action == "check":
            updated = data.get("updateAvailable")
            if updated is None:
                log(f"{name}: firmware check completed")
            else:
                log(f"{name}: firmware check completed — "
                    f"{'an update is available' if updated else 'already current'}")
        else:
            log(f"{name}: firmware update finished — now on version "
                f"{data.get('to') or '?'}")
