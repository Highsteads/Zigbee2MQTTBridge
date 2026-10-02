#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_bridge_tools.py
# Description: Looking after zigbee2mqtt itself from Indigo (v2.13.0) — back it
#              up to the Mac, restart it, check it for missing routers,
#              re-run a device's setup — plus the Button Pressed trigger and
#              the count of offline devices on each Coordinator.
#
#              These came out of the October 2026 comparison with Home
#              Assistant, Homey, homebridge-z2m and ioBroker. Every request
#              here is one zigbee2mqtt 2.13.0 really has (lib/extension/
#              bridge.ts requestLookup), and each was tried against both live
#              bridges before a line was written: the house bridge takes about
#              21 seconds to answer a backup, so nothing waits for a reply.
#              Requests carry a transaction id and only replies carrying one
#              of ours are acted on — zigbee2mqtt's own web page publishes its
#              backups on the same reply topic.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import base64
import binascii
import io
import os
import re
import time
import zipfile
from datetime import datetime

import z2m_helpers
from z2m_secondary import is_secondary

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


def log_activity(*args, **kwargs):
    return z2m_helpers.log_activity(*args, **kwargs)


# How long to wait for zigbee2mqtt to answer before saying so. A backup of the
# house bridge took 21 s when measured (02-10-2026); give it room.
REPLY_WAIT = {"backup": 180, "coordinator_check": 180, "restart": 60,
              "device/configure": 120}

BACKUP_KEEP_DEFAULT = 10
BACKUP_NAME = "zigbee2mqtt-backup-{prefix}-{stamp}.zip"
ANY_PRESS = "any"


def _safe(text):
    """A prefix as it can appear in a file name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("_") or "zigbee2mqtt"


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


class BridgeToolsMixin:
    """See the file header above."""

    # ── Which bridges ────────────────────────────────────────────────────────

    def _bridge_prefixes(self):
        return [p for p in (self._topic_prefix(), self._garage_prefix()) if p]

    def _chosen_prefixes(self, value):
        """The prefixes a dialog or action asked for; "all" means every one."""
        configured = self._bridge_prefixes()
        value = str(value or "all").strip()
        if value == "all":
            return configured
        return [value] if value in configured else []

    def list_bridge_prefixes(self, filter="", valuesDict=None, typeId="", targetId=0):
        """Dynamic list of configured bridges. filter="all" adds "All bridges"."""
        rows = [(p, p) for p in self._bridge_prefixes()]
        if filter == "all" and len(rows) > 1:
            rows.insert(0, ("all", "All bridges"))
        return rows or [("none", "-- no bridge configured --")]

    def list_radio_devices(self, filter="", valuesDict=None, typeId="", targetId=0):
        """Every Zigbee device of ours that is a radio (no coordinators, no
        split-out devices), for picking one in a menu."""
        rows = [(str(d.id), d.name) for d in indigo.devices.iter(self.pluginId)
                if d.deviceTypeId not in ("z2mCoordinator", "z2mGroupLight", "z2mGroupRelay")
                and not is_secondary(d)]
        return sorted(rows, key=lambda r: r[1].lower()) or [("none", "-- no devices --")]

    # ── Requests and their replies ───────────────────────────────────────────

    def _bridge_request(self, prefix, kind, payload=None, **remember):
        """Publish bridge/request/<kind> with a transaction of ours."""
        self._request_seq += 1
        transaction = f"indigo-{_safe(kind)}-{self._request_seq}-{int(time.time())}"
        body = dict(payload or {})
        body["transaction"] = transaction
        if not self._publish(f"{prefix}/bridge/request/{kind}", body):
            return None
        self._bridge_requests[transaction] = dict(remember, kind=kind, prefix=prefix,
                                                  sent=time.time())
        return transaction

    def _process_bridge_response(self, kind, payload, prefix):
        """bridge/response/<kind>: act only on a reply to one of our requests."""
        if not isinstance(payload, dict):
            return
        request = self._bridge_requests.pop(str(payload.get("transaction") or ""), None)
        if request is None:
            return
        ok = str(payload.get("status") or "").lower() == "ok"
        data = payload.get("data") or {}
        error = payload.get("error") or "no reason given"
        if kind == "backup":
            self._save_backup(prefix, data, ok, error)
        elif kind == "coordinator_check":
            self._report_routers(prefix, data, ok, error)
        elif kind == "restart":
            if ok:
                log(f"zigbee2mqtt on '{prefix}' is restarting. Its devices come "
                    f"back by themselves in about half a minute.")
            else:
                log(f"zigbee2mqtt on '{prefix}' refused to restart: {error}",
                    level="WARNING")
        elif kind == "device/configure":
            name = request.get("name", "The device")
            if ok:
                log(f"{name}: zigbee2mqtt has set it up again.")
            else:
                log(f"{name}: zigbee2mqtt could not set it up again — {error}. "
                    f"A battery device has to be awake: press its button or "
                    f"set off its sensor, then try again.", level="WARNING")

    def _check_bridge_requests(self):
        """Say so, once, when zigbee2mqtt never answered."""
        if not self._bridge_requests:
            return
        now = time.time()
        for transaction, request in list(self._bridge_requests.items()):
            kind = request["kind"]
            if now - request["sent"] < REPLY_WAIT.get(kind, 120):
                continue
            self._bridge_requests.pop(transaction, None)
            what = {"backup": "the backup",
                    "coordinator_check": "the check for missing routers",
                    "restart": "the restart",
                    "device/configure": f"setting up {request.get('name', 'the device')} again",
                    }.get(kind, kind)
            log(f"zigbee2mqtt on '{request['prefix']}' did not answer {what}. "
                f"Check it is running, then try again.", level="WARNING")

    # ── Backup ───────────────────────────────────────────────────────────────

    def _backup_folder(self):
        folder = str(self.pluginPrefs.get("backupFolder", "") or "").strip()
        if folder:
            return os.path.expanduser(folder)
        # Beside the versioned Indigo folder, so it survives an Indigo upgrade
        # and is not under Web Assets, which is served to anyone.
        return os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                            "Zigbee2MQTT Backups")

    def _backup_keep(self):
        try:
            return max(1, int(self.pluginPrefs.get("backupKeep", BACKUP_KEEP_DEFAULT)))
        except (TypeError, ValueError):
            return BACKUP_KEEP_DEFAULT

    def _start_backups(self, prefixes):
        asked = [p for p in prefixes if self._bridge_request(p, "backup")]
        if asked:
            log(f"Asked zigbee2mqtt on {_join(repr(p) for p in asked)} for a backup. "
                f"It takes up to a minute, and the log says where it was saved.")
        return asked

    def menu_backup(self, valuesDict=None, typeId=None):
        prefixes = self._chosen_prefixes((valuesDict or {}).get("bridge"))
        if not prefixes:
            log("No zigbee2mqtt chosen to back up.", level="WARNING")
        else:
            self._start_backups(prefixes)
        return True

    def action_backup(self, action):
        prefixes = self._chosen_prefixes(action.props.get("bridge"))
        if not prefixes:
            log("Back Up zigbee2mqtt: the chosen bridge is no longer configured.",
                level="WARNING")
            return
        self._start_backups(prefixes)

    def _save_backup(self, prefix, data, ok, error):
        """Write a backup reply to the backup folder, then keep only the newest.

        zigbee2mqtt sends its whole data folder as a base64 zip, and that
        holds the network key and the broker password: the file is written
        readable by this user only, its contents are never logged, and the
        default folder is outside Web Assets.
        """
        if not ok:
            log(f"zigbee2mqtt on '{prefix}' could not make a backup: {error}",
                level="WARNING")
            return
        try:
            raw = base64.b64decode(str(data.get("zip") or ""), validate=True)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if not archive.namelist() or archive.testzip() is not None:
                    raise zipfile.BadZipFile("empty or damaged")
        except (binascii.Error, ValueError, zipfile.BadZipFile) as e:
            log(f"zigbee2mqtt on '{prefix}' sent a backup that is not a usable "
                f"zip file ({e}), so nothing was saved.", level="ERROR")
            return
        folder = self._backup_folder()
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = os.path.join(folder, BACKUP_NAME.format(prefix=_safe(prefix), stamp=stamp))
        temp = path + ".part"
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        except OSError as e:
            try:
                os.remove(temp)
            except OSError:
                pass
            log(f"Could not save the zigbee2mqtt backup for '{prefix}' in "
                f"{folder}: {e}", level="ERROR")
            return
        removed = self._prune_backups(folder, prefix)
        size = max(1, round(len(raw) / 1024))
        tail = f", and removed {_plural(removed, 'older one')}" if removed else ""
        log(f"Saved a backup of zigbee2mqtt '{prefix}' ({size} KB) to {path}{tail}.")
        self._update_coordinator(prefix, lastBackup=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _prune_backups(self, folder, prefix):
        """Delete this bridge's oldest backups beyond the number to keep.

        Only files named exactly as this plugin names them are touched.
        """
        pattern = re.compile(r"^zigbee2mqtt-backup-" + re.escape(_safe(prefix))
                             + r"-\d{4}-\d{2}-\d{2}-\d{6}\.zip$")
        try:
            mine = sorted(n for n in os.listdir(folder) if pattern.match(n))
        except OSError:
            return 0
        removed = 0
        for name in mine[:-self._backup_keep()]:
            try:
                os.remove(os.path.join(folder, name))
                removed += 1
            except OSError as e:
                log(f"Could not remove the old backup {name}: {e}", level="WARNING")
        return removed

    # ── Restart ──────────────────────────────────────────────────────────────

    def _one_bridge(self, value):
        """The single bridge a restart names. "All bridges" is never accepted:
        restarting every network at once is not a thing to do by accident."""
        if str(value or "").strip() == "all":
            return None
        prefixes = self._chosen_prefixes(value)
        return prefixes[0] if len(prefixes) == 1 else None

    def _restart_bridge(self, prefix):
        if self._bridge_request(prefix, "restart"):
            log(f"Asked zigbee2mqtt on '{prefix}' to restart.")

    def menu_restart_bridge(self, valuesDict=None, typeId=None):
        prefix = self._one_bridge((valuesDict or {}).get("bridge"))
        if prefix is None:
            log("Choose one zigbee2mqtt to restart.", level="WARNING")
            return True
        self._restart_bridge(prefix)
        return True

    def action_restart_bridge(self, action):
        prefix = self._one_bridge(action.props.get("bridge"))
        if prefix is None:
            log("Restart zigbee2mqtt: choose one zigbee2mqtt that is still "
                "configured.", level="WARNING")
            return
        self._restart_bridge(prefix)

    # ── Missing routers ──────────────────────────────────────────────────────

    def _check_routers(self, prefixes):
        asked = [p for p in prefixes if self._bridge_request(p, "coordinator_check")]
        if asked:
            log(f"Asked zigbee2mqtt on {_join(repr(p) for p in asked)} to check for "
                f"missing routers. It can take a minute or two on a big network.")

    def menu_check_routers(self, valuesDict=None, typeId=None):
        prefixes = self._chosen_prefixes((valuesDict or {}).get("bridge"))
        if not prefixes:
            log("No zigbee2mqtt chosen to check.", level="WARNING")
        else:
            self._check_routers(prefixes)
        return True

    def action_check_routers(self, action):
        self._check_routers(self._chosen_prefixes(action.props.get("bridge")))

    def _report_routers(self, prefix, data, ok, error):
        """A router the coordinator remembers but cannot reach — usually a mains
        device unplugged or switched off at the wall."""
        if not ok:
            log(f"zigbee2mqtt on '{prefix}' could not check for missing routers: "
                f"{error}", level="WARNING")
            return
        missing = [m for m in (data.get("missing_routers") or []) if isinstance(m, dict)]
        names = [str(m.get("friendly_name") or m.get("ieee_address") or "?") for m in missing]
        self._update_coordinator(prefix, missingRouters=len(names),
                                 missingRouterNames=", ".join(names))
        if not names:
            log(f"zigbee2mqtt on '{prefix}': no missing routers. Every router the "
                f"coordinator knows about is answering.")
            return
        verb = "is" if len(names) == 1 else "are"
        log(f"zigbee2mqtt on '{prefix}': {_plural(len(names), 'router')} {verb} "
            f"missing — {_join(names)}. A router is a mains-powered device; one "
            f"that is switched off or unplugged leaves the devices that relied "
            f"on it to find another way.", level="WARNING")

    # ── Setting a device up again ────────────────────────────────────────────

    def _reconfigure_device(self, dev):
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        if dev.deviceTypeId == "z2mCoordinator" or is_secondary(dev) or not ieee:
            log(f"{dev.name} is not a Zigbee device zigbee2mqtt can set up again.",
                level="WARNING")
            return
        prefix = self._device_prefix(dev)
        if self._bridge_request(prefix, "device/configure", {"id": ieee}, name=dev.name):
            log(f"{dev.name}: asked zigbee2mqtt to set it up again.")

    def action_reconfigure_device(self, action, dev=None, callerWaitingForResult=None):
        if dev is None:
            try:
                dev = indigo.devices[action.deviceId]
            except (KeyError, AttributeError):
                log("Set Up Device Again: no device given.", level="WARNING")
                return
        self._reconfigure_device(dev)

    def menu_reconfigure_device(self, valuesDict=None, typeId=None):
        chosen = str((valuesDict or {}).get("targetDevice") or "").strip()
        try:
            dev = indigo.devices[int(chosen)]
        except (KeyError, TypeError, ValueError):
            log("No device chosen to set up again.", level="WARNING")
            return True
        self._reconfigure_device(dev)
        return True

    # ── Button Pressed trigger ───────────────────────────────────────────────

    def _device_action_values(self, dev):
        """The `action` values zigbee2mqtt says this device sends, in order."""
        ieee = (dev.ownerProps.get("ieee_address") or "").strip()
        entry = self.bridge_devices.get(ieee) if ieee else None
        values = []

        def walk(items):
            for feature in items or []:
                if feature.get("features"):
                    walk(feature["features"])
                    continue
                if feature.get("property") == "action" and feature.get("type") == "enum":
                    for value in feature.get("values") or []:
                        if str(value) not in values:
                            values.append(str(value))

        walk((((entry or {}).get("definition") or {}).get("exposes")) or [])
        return values

    def list_action_devices(self, filter="", valuesDict=None, typeId="", targetId=0):
        rows = [(str(d.id), d.name) for d in indigo.devices.iter(self.pluginId)
                if d.deviceTypeId != "z2mCoordinator" and not is_secondary(d)
                and (d.deviceTypeId == "z2mButton" or self._device_action_values(d))]
        return sorted(rows, key=lambda r: r[1].lower()) or [("none", "-- no buttons --")]

    def list_device_actions(self, filter="", valuesDict=None, typeId="", targetId=0):
        rows = [(ANY_PRESS, "Any press")]
        try:
            dev = indigo.devices[int((valuesDict or {}).get("deviceId") or 0)]
        except (KeyError, TypeError, ValueError):
            return rows
        return rows + [(v, v.replace("_", " ")) for v in self._device_action_values(dev)]

    def validateEventConfigUi(self, valuesDict, typeId, eventId):
        errors = indigo.Dict()
        if typeId == "buttonPressed":
            try:
                indigo.devices[int(valuesDict.get("deviceId") or 0)]
            except (KeyError, TypeError, ValueError):
                errors["deviceId"] = "Choose the device whose presses this watches."
        return (len(errors) == 0), valuesDict, errors

    def button_device_chosen(self, valuesDict=None, typeId="", targetId=0):
        """Picking a device reloads the list of its presses."""
        return valuesDict

    def _fire_button_event(self, dev, action):
        """Run every Button Pressed trigger watching this device and press.

        Fires on EVERY press, including the same press twice in a row, which
        a trigger on a state change cannot see. A retained message replayed
        when the plugin reconnects is not a press and fires nothing.
        """
        if self._current_retained:
            return
        with self.maps_lock:
            triggers = list(self.event_triggers.values())
        for trigger in triggers:
            if trigger.pluginTypeId != "buttonPressed":
                continue
            props = trigger.pluginProps
            try:
                if int(props.get("deviceId") or 0) != dev.id:
                    continue
            except (TypeError, ValueError):
                continue
            wanted = str(props.get("action") or ANY_PRESS)
            if wanted not in (ANY_PRESS, action):
                continue
            try:
                indigo.trigger.execute(trigger)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"Button Pressed trigger '{trigger.name}'")

    # ── Offline devices per bridge ───────────────────────────────────────────

    def _note_availability(self, dev, prefix, online):
        """Keep each bridge's set of offline devices, and say when it changes.

        A group is not a device: zigbee2mqtt calls it offline only when every
        member is, and those members are already counted.
        """
        if dev.deviceTypeId in ("z2mGroupLight", "z2mGroupRelay"):
            return
        offline = self._offline_by_prefix.setdefault(prefix, set())
        before = len(offline)
        if online:
            offline.discard(dev.id)
        else:
            offline.add(dev.id)
        if len(offline) != before:
            self._publish_offline_count(prefix)
            if not self._current_retained:
                self._fire_event("offlineCountChanged", prefix, dev.name)

    def _forget_offline(self, dev):
        """A device that has stopped (disabled, deleted) no longer counts."""
        for prefix, offline in self._offline_by_prefix.items():
            if dev.id in offline:
                offline.discard(dev.id)
                self._publish_offline_count(prefix)

    def _publish_offline_count(self, prefix):
        names = []
        for dev_id in sorted(self._offline_by_prefix.get(prefix, ())):
            try:
                names.append(indigo.devices[dev_id].name)
            except KeyError:
                continue
        names.sort(key=str.lower)
        self._update_coordinator(prefix, offlineDevices=len(names),
                                 offlineDeviceNames=", ".join(names))
