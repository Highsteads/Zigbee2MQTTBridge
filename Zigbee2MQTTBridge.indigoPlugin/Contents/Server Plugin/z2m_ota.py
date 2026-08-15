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

import time

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

    # dev id (or name) -> when completion was last announced, so the two
    # routes that both notice an update ending cannot say so twice.
    _update_announced = {}

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

        # Leaving `updating` is how an update ENDS, and the device itself is the
        # one saying so — which makes this more reliable than the bridge's reply,
        # since that can be missed while the device reboots into its new image.
        #
        # Note that progress reaching 100 is NOT the end: that only means the
        # image has transferred. The device then writes it and restarts, and it
        # is the state leaving `updating` that says it came back.
        if previous == STATE_UPDATING and state != STATE_UPDATING:
            now_version = update.get("installed_version")
            if state == STATE_IDLE:
                self._announce_update_finished(
                    dev.name, self._format_firmware_version(now_version),
                    dev_id=dev.id)
                self._fire_event("otaUpdateFinished", self._device_prefix(dev),
                                 dev.name)
            else:
                # Back to `available` means the device is still on the old
                # image: the update did not take.
                log(f"{dev.name}: firmware update did not complete — the device "
                    f"is still on version {now_version if now_version is not None else 'unknown'}",
                    level="WARNING")
                self._fire_event("otaUpdateFailed", self._device_prefix(dev),
                                 dev.name)

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
        log("  To install one: Plugins -> Zigbee2MQTT Bridge -> Update Device "
            "Firmware... and pick it from the list. Do it when the device can "
            "be busy for a few minutes — an interrupted update can leave it "
            "unusable.")

    # ── Starting an update, only ever on request ─────────────────────────────

    def action_update_firmware(self, action, dev=None, callerWaitingForResult=None):
        """Action: start an OTA update for one device (for use in a trigger,
        schedule or action group). The menu item below is the easier route for
        a one-off; both go through the same guards."""
        if dev is None:
            log("Update Device Firmware: no device given", level="ERROR")
            return
        self._start_firmware_update(dev)

    def list_devices_with_updates(self, filter="", valuesDict=None, typeId="",
                                  targetId=0):
        """Devices with an update genuinely waiting, for the menu picker.

        Only `available` devices are listed. Offering the whole estate and
        refusing most of it afterwards would be a worse dialog than one that
        simply shows what can be done.
        """
        rows = []
        for dev in indigo.devices.iter(self.pluginId):
            if dev.states.get("updateState") != STATE_AVAILABLE:
                continue
            installed = dev.states.get("updateInstalledVersion") or "?"
            latest    = dev.states.get("updateLatestVersion") or "?"
            rows.append((str(dev.id), f"{dev.name}  ({installed} -> {latest})"))
        if not rows:
            # A menu with no options looks broken. Say why it is empty, and the
            # callback refuses this value.
            return [("", "-- no updates waiting --")]
        return sorted(rows, key=lambda r: r[1])

    def menu_update_firmware(self, valuesDict=None, typeId=None):
        """Menu: pick a device with an update waiting and start it.

        Menu ConfigUIs are never validated by Indigo — the validation stubs are
        commented out in plugin_base.py — so everything is checked here rather
        than relying on the dialog to have done it.
        """
        chosen = str((valuesDict or {}).get("targetDevice") or "").strip()
        if not chosen:
            log("No device chosen — nothing to update.", level="WARNING")
            return True
        try:
            dev = indigo.devices[int(chosen)]
        except (ValueError, KeyError):
            log(f"Could not find the chosen device ({chosen!r}).", level="ERROR")
            return True
        self._start_firmware_update(dev)
        return True

    def _start_firmware_update(self, dev):
        """The one guarded path to starting an update, shared by both routes.

        Guarded rather than trusting the caller: an update fired at a device
        that cannot take one is the expensive mistake here.
        """
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
                f"not power it off. Watch its Update Progress state.")


    @staticmethod
    def _format_firmware_version(value):
        """Render a firmware version readably, whatever shape it arrives in.

        zigbee2mqtt sends the `to` field of an update reply as a DICT —
        {'date_code': '20260514', 'file_version': 16788992,
         'software_build_id': '1.163.1'} — and printing that raw put a Python
        dict in the middle of a sentence in the event log. The build id is the
        part a person recognises ("1.163.1"); the file version is the opaque
        integer the rest of the plugin compares on.
        """
        if value is None:
            return ""
        if not isinstance(value, dict):
            return str(value)
        build = value.get("software_build_id")
        file_version = value.get("file_version")
        date_code = str(value.get("date_code") or "")
        parts = []
        if build:
            parts.append(str(build))
        if file_version is not None:
            parts.append(f"build {file_version}" if build else str(file_version))
        if len(date_code) == 8 and date_code.isdigit():
            months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            try:
                parts.append(f"{int(date_code[6:8])} "
                             f"{months[int(date_code[4:6]) - 1]} {date_code[0:4]}")
            except (ValueError, IndexError):
                pass
        return f"{parts[0]} ({', '.join(parts[1:])})" if len(parts) > 1 else \
            (parts[0] if parts else "")

    def _announce_update_finished(self, name, version_text, dev_id=None):
        """Say an update finished — ONCE.

        Both routes reach this: the bridge's reply, which carries the readable
        version, and the device leaving `updating`, which is the reliable
        signal but knows only the opaque file version. They arrive seconds
        apart, so without this the log would carry two "finished" lines for one
        update, saying the same thing differently.

        First one through wins, which is the right way round: the reply usually
        lands first and has the better text, and if it never comes the state
        change still announces it.
        """
        key = dev_id if dev_id is not None else name
        now = time.time()
        last = self._update_announced.get(key, 0)
        self._update_announced[key] = now
        if now - last < 300:
            return False
        on_version = f" — now running {version_text}" if version_text else ""
        log(f"{name}: firmware update finished{on_version}")
        return True

    # ── Replies from zigbee2mqtt ─────────────────────────────────────────────

    # Ordinary outcomes of asking a Zigbee mesh about firmware, NOT faults.
    # A battery sensor spends nearly all its life asleep and simply will not
    # answer; some devices advertise OTA support they cannot actually perform;
    # and asking twice while one check is still running is harmless. Logging
    # these at ERROR turned a routine check across 19 devices into eight red
    # lines, which is how a log stops being worth reading.
    _EXPECTED_OTA_FAILURES = (
        "didn't respond",
        "did not respond",
        "no endpoint found",
        "already in progress",
        "timeout",
    )

    def _process_ota_response(self, action, payload, prefix):
        """Handle bridge/response/device/ota_update/{check,update}."""
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "").lower()
        data = payload.get("data") or {}

        # On an ERROR reply zigbee2mqtt sends `data: {}` — there is no id to
        # look up, which is why this used to announce a device called "?".
        # The error text names the device itself, so say nothing rather than
        # inventing a name for it.
        who = data.get("id")
        name = ""
        dev_id = None
        if who:
            with self.maps_lock:
                dev_id = self.ieee_map.get(who)
            name = who
            if dev_id is not None:
                try:
                    name = indigo.devices[dev_id].name
                except KeyError:
                    pass

        if status == "error":
            reason = payload.get("error") or "no reason given"
            # The demotion applies to a CHECK only. Asking a sleeping sensor
            # whether it has an update and getting no answer is routine; an
            # UPDATE you deliberately started failing is not, whatever the
            # reason given.
            expected = action == "check" and any(
                token in str(reason).lower() for token in self._EXPECTED_OTA_FAILURES)
            prefix_text = f"{name}: " if name else ""
            log(f"{prefix_text}firmware {action} did not complete — {reason}",
                level="INFO" if expected else "ERROR")
            if action == "update":
                self._fire_event("otaUpdateFailed", prefix, name or "unknown")
            return
        if action == "check":
            updated = data.get("updateAvailable")
            if updated is None:
                log(f"{name}: firmware check completed")
            else:
                log(f"{name}: firmware check completed — "
                    f"{'an update is available' if updated else 'already current'}")
        else:
            # Keyed on the device id, the SAME key the state-change route
            # uses. Keying one on the id and the other on the name meant the
            # two never matched and both spoke — which is the whole thing this
            # was meant to prevent.
            self._announce_update_finished(
                name or "A device", self._format_firmware_version(data.get("to")),
                dev_id=dev_id)
