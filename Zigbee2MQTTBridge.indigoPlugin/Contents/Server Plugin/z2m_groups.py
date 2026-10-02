#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_groups.py
# Description: zigbee2mqtt groups as Indigo devices (v2.14.0).
#
#              A zigbee2mqtt group switches all its members with ONE Zigbee
#              broadcast, so the lights in it change together instead of one
#              after another, and to Indigo it is just another light or
#              switch. Autolog's plugin, Home Assistant, Homey, homebridge-z2m,
#              ioBroker and Node-RED all offer this; we did not.
#
#              Facts it rests on, read from zigbee2mqtt 2.14.2's source:
#              * `<prefix>/bridge/groups` is retained: a list of {id,
#                friendly_name, description, scenes, members: [{ieee_address,
#                endpoint}]} (bridge.ts publishGroups).
#              * Commands go to `<prefix>/<group name>/set`, exactly as for a
#                device, and the group's state arrives on `<prefix>/<group
#                name>` — so the existing light and relay code drives a group
#                once it is in friendly_name_map.
#              * zigbee2mqtt publishes a group's state when a MEMBER changes:
#                on when any member is on, off only when all are (groups.ts,
#                off_state "all_members_off"). A group has no state of its own
#                to ask for, so it is never sent /get; after a restart it is
#                worked out from its members' Indigo states until zigbee2mqtt
#                next publishes one.
#              * A group is available while any member is (availability.ts).
#              * "default_bind_group" (id 901) is zigbee2mqtt's own, used for
#                binding remotes — never a device.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import z2m_helpers
from z2m_constants import DEVICE_FOLDER_NAME
from z2m_detection import _detect_device_type, _detect_light_capabilities

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


def log_activity(*args, **kwargs):
    return z2m_helpers.log_activity(*args, **kwargs)


GROUP_LIGHT = "z2mGroupLight"
GROUP_RELAY = "z2mGroupRelay"
GROUP_TYPE_IDS = (GROUP_LIGHT, GROUP_RELAY)
DEFAULT_BIND_GROUP = "default_bind_group"


def is_group(dev):
    return getattr(dev, "deviceTypeId", None) in GROUP_TYPE_IDS


class GroupsMixin:
    """See the file header above."""

    # ── What a group is ──────────────────────────────────────────────────────

    def _group_members(self, entry, prefix):
        """[(ieee, bridge cache entry or None)] for a group's members, each
        device once even when several of its endpoints are members."""
        seen, out = set(), []
        for member in entry.get("members") or []:
            ieee = str((member or {}).get("ieee_address") or "")
            if not ieee or ieee in seen:
                continue
            seen.add(ieee)
            data = self.bridge_devices.get(ieee)
            if data is not None and data.get("_mqtt_prefix") != prefix:
                data = None
            out.append((ieee, data))
        return out

    def _group_kind(self, entry, prefix):
        """(device type, light capabilities) for a group, or (None, {}).

        A light group if any member is a light, a switch group if any member
        is a switch, otherwise nothing: a group of sensors or blinds is no
        light or switch, and zigbee2mqtt's own default_bind_group is never a
        device. Colour and white temperature are offered when ANY member has
        them; a member that cannot simply ignores the command.
        """
        if not isinstance(entry, dict) or entry.get("friendly_name") == DEFAULT_BIND_GROUP:
            return None, {}
        lights, relays = [], False
        for _ieee, data in self._group_members(entry, prefix):
            definition = (data or {}).get("definition") or {}
            exposes = definition.get("exposes") or []
            kind = _detect_device_type(exposes, model=definition.get("model", ""))
            if kind == "z2mLight":
                lights.append(exposes)
            elif kind == "z2mRelay":
                relays = True
        if lights:
            caps = {"has_brightness": True, "has_color": False, "has_color_temp": False}
            for exposes in lights:
                found = _detect_light_capabilities(exposes)
                caps["has_color"] = caps["has_color"] or found["has_color"]
                caps["has_color_temp"] = caps["has_color_temp"] or found["has_color_temp"]
            return GROUP_LIGHT, caps
        if relays:
            return GROUP_RELAY, {}
        return None, {}

    def _group_devices(self, prefix=None):
        """{(prefix, group id): Indigo device} for our group devices."""
        out = {}
        for dev in indigo.devices.iter(self.pluginId):
            if not is_group(dev):
                continue
            props = dev.ownerProps
            dev_prefix = props.get("mqtt_prefix") or self._topic_prefix()
            if prefix is not None and dev_prefix != prefix:
                continue
            try:
                out[(dev_prefix, int(props.get("group_id")))] = dev
            except (TypeError, ValueError):
                continue
        return out

    # ── bridge/groups ────────────────────────────────────────────────────────

    def _process_bridge_groups(self, payload, prefix):
        """Cache the group list, keep group devices current, create new ones.

        A group is new when it was not in the last list for this bridge, or
        had no members then — zigbee2mqtt's web page makes an empty group
        first and adds members after, publishing the list each time. The first
        list for a bridge after the plugin starts is the baseline and creates
        nothing, the same rule as for devices.
        """
        if not isinstance(payload, list):
            return
        previous = self.bridge_groups.get(prefix)
        current = {}
        for entry in payload:
            if isinstance(entry, dict) and isinstance(entry.get("id"), int):
                current[entry["id"]] = entry
        self.bridge_groups[prefix] = current
        self._refresh_group_devices(prefix)
        if previous is None:
            return
        fresh = [entry for gid, entry in current.items()
                 if entry.get("members")
                 and not (previous.get(gid) or {}).get("members")]
        if not fresh:
            return
        existing = self._group_devices(prefix)
        folder_id = None
        for entry in fresh:
            if (prefix, entry["id"]) in existing:
                continue
            if folder_id is None:
                folder_id = self._ensure_device_folder(DEVICE_FOLDER_NAME)
            self._create_group_device(entry, prefix, folder_id)

    def _create_group_device(self, entry, prefix, folder_id):
        """Make the Indigo device for one group. Returns 'created', 'skipped'
        or 'error'."""
        kind, caps = self._group_kind(entry, prefix)
        if kind is None:
            return "skipped"
        fname = str(entry.get("friendly_name") or f"Group {entry['id']}")
        name, n = fname, 2
        while name in indigo.devices:
            name = f"{fname} (group)" if n == 2 else f"{fname} (group {n})"
            n += 1
        props = {"friendly_name": fname, "mqtt_prefix": prefix,
                 "group_id": str(entry["id"])}
        if kind == GROUP_LIGHT:
            props.update(caps)
            props.update(self._compute_light_native_flags(caps["has_color"],
                                                          caps["has_color_temp"]))
        try:
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=name,
                pluginId=self.pluginId,
                deviceTypeId=kind,
                folder=folder_id,
                props=props,
            )
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"creating a device for group '{fname}'")
            return "error"
        what = "light" if kind == GROUP_LIGHT else "switch"
        log(f"  created group {what}: '{new_dev.name}' with "
            f"{len(self._group_members(entry, prefix))} member(s)")
        return "created"

    def create_group_devices(self, folder_id):
        """Discover & Create: a device for every group that has none yet."""
        counts = {"created": 0, "skipped": 0, "error": 0, "exists": 0}
        existing = self._group_devices()
        for prefix, groups in self.bridge_groups.items():
            for gid, entry in groups.items():
                if (prefix, gid) in existing:
                    counts["exists"] += 1
                    continue
                if not entry.get("members"):
                    counts["skipped"] += 1
                    continue
                counts[self._create_group_device(entry, prefix, folder_id)] += 1
        return counts

    def _refresh_group_devices(self, prefix):
        """Bring every group device on this bridge up to date: its name if
        the group was renamed in zigbee2mqtt, its members, and for a light
        group the colour abilities of its members."""
        groups = self.bridge_groups.get(prefix) or {}
        for (dev_prefix, gid), dev in self._group_devices(prefix).items():
            entry = groups.get(gid)
            if entry is None:
                continue          # gone from zigbee2mqtt — Report Orphaned Devices says so
            try:
                self._refresh_group_device(dev, entry, prefix)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"group device '{dev.name}'")

    def _refresh_group_device(self, dev, entry, prefix):
        old_fname = dev.ownerProps.get("friendly_name", "")
        new_fname = str(entry.get("friendly_name") or old_fname)
        kind, caps = self._group_kind(entry, prefix)
        changes = {}
        if new_fname != old_fname:
            changes["friendly_name"] = new_fname
        if dev.deviceTypeId == GROUP_LIGHT and kind == GROUP_LIGHT:
            for key in ("has_color", "has_color_temp"):
                if bool(dev.ownerProps.get(key)) != caps[key]:
                    changes[key] = caps[key]
        if changes:
            with self.props_lock:
                props = dict(indigo.devices[dev.id].pluginProps)
                props.update(changes)
                if "has_color" in changes or "has_color_temp" in changes:
                    props.update(self._compute_light_native_flags(
                        bool(props.get("has_color")), bool(props.get("has_color_temp"))))
                dev.replacePluginPropsOnServer(props)
            dev = indigo.devices[dev.id]
        if "friendly_name" in changes:
            with self.maps_lock:
                self.friendly_name_map.pop((prefix, old_fname), None)
                self.friendly_name_map[(prefix, new_fname)] = dev.id
            log(f"Group renamed in zigbee2mqtt: '{old_fname}' -> '{new_fname}'")
            if dev.name == old_fname and new_fname not in indigo.devices:
                try:
                    dev.name = new_fname
                    dev.replaceOnServer()
                except Exception as e:
                    log(f"Could not rename '{old_fname}' to '{new_fname}' in Indigo "
                        f"({e}); it still follows the group", level="WARNING")
        names = self._group_member_names(entry, prefix)
        self._apply_updates(dev, [("memberCount", len(names), str(len(names))),
                                  ("members", ", ".join(names))])

    def _group_member_names(self, entry, prefix):
        names = []
        for ieee, data in self._group_members(entry, prefix):
            with self.maps_lock:
                dev_id = self.ieee_map.get(ieee)
            name = None
            if dev_id is not None:
                try:
                    name = indigo.devices[dev_id].name
                except KeyError:
                    name = None
            names.append(name or (data or {}).get("friendly_name") or ieee)
        return sorted(names, key=str.lower)

    # ── Running a group device ───────────────────────────────────────────────

    def _start_group(self, dev):
        """deviceStartComm for a group: route its topic to it, and show a state.

        It is never sent /get (a group has no state of its own to report), so
        it starts from its members until zigbee2mqtt next publishes one.
        """
        fname = (dev.ownerProps.get("friendly_name") or "").strip()
        if not fname:
            log(f"Group device '{dev.name}' has no friendly_name — skipping",
                level="WARNING")
            return
        with self.maps_lock:
            self.friendly_name_map[(self._device_prefix(dev), fname)] = dev.id
        self._apply_indigo_subtype(dev)
        if dev.deviceTypeId == GROUP_LIGHT:
            self._apply_light_capabilities(dev)
        self._ensure_device_states(dev)
        self._keep_churn_out_of_sql_logger(dev)
        self._seed_group_state(dev)

    def _seed_group_state(self, dev, announce=False):
        """On when any member is on — zigbee2mqtt's own rule — from the
        members' Indigo devices. Says nothing when no member is known yet."""
        prefix = self._device_prefix(dev)
        try:
            entry = (self.bridge_groups.get(prefix) or {}).get(int(dev.ownerProps.get("group_id")))
        except (TypeError, ValueError):
            entry = None
        states = []
        for ieee, _data in self._group_members(entry or {}, prefix):
            with self.maps_lock:
                dev_id = self.ieee_map.get(ieee)
            try:
                states.append(bool(indigo.devices[dev_id].onState))
            except (KeyError, TypeError, AttributeError):
                continue
        if not states:
            if announce:
                log(f"{dev.name}: its members are not known yet, so its state "
                    f"cannot be worked out — it follows zigbee2mqtt from the next "
                    f"change.")
            return
        on = any(states)
        self._apply_updates(dev, [("onOffState", on, "on" if on else "off")])
        if announce:
            log_activity(self, f'"{dev.name}": a group has no state of its own to '
                               f'ask for, so it was worked out from its members: '
                               f'{"on" if on else "off"}')
