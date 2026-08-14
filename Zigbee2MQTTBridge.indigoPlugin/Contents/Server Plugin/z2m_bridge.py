#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_bridge.py
# Description: Everything arriving under prefix/bridge/: the topic router, the device
#              cache, bridge state and info, the health report, and the events
#              raised from bridge/event plus their trigger lifecycle.
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

from datetime import datetime

from z2m_constants import DEVICE_FOLDER_NAME


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


class BridgeMixin:
    """See the file header above."""

    # ── Message processing (Indigo main thread) ───────────────────────────────

    def _process_message(self, topic, payload):
        """Route an MQTT message to the appropriate handler."""
        # Internal control messages
        if topic == "__connected__":
            log(f"MQTT connected to {self._effective_broker()}:{self._effective_port()}")
            subscribed = payload.get("subscribed")
            if subscribed:
                log(f"MQTT subscribed to: {', '.join(subscribed)}")
            # Actively request bridge/devices from every configured prefix.
            # Retained messages alone are unreliable — the garage Z2M may not have
            # published since broker restart, or retain may be disabled.
            prefix = self._topic_prefix()
            self._publish(f"{prefix}/bridge/request/devices", {})
            garage = self._garage_prefix()
            if garage:
                self._publish(f"{garage}/bridge/request/devices", {})
                log(f"Requested device list from garage bridge: {garage}/bridge/request/devices")
            return
        if topic == "__disconnected__":
            rc = payload.get("rc", "?")
            if rc == 0:
                log("MQTT disconnected cleanly")
            else:
                reason = payload.get("reason", "")
                detail = f"rc={rc}" + (f", {reason}" if reason else "")
                log(f"MQTT disconnected unexpectedly ({detail}) — will "
                    f"auto-reconnect", level="WARNING")
            return
        if topic == "__error__":
            log(payload.get("msg", "MQTT error"), level="ERROR")
            return

        parts  = topic.split("/")
        if not parts or len(parts) < 2:
            return

        # Determine which prefix this message belongs to
        primary = self._topic_prefix()
        garage  = self._garage_prefix()
        if parts[0] == primary:
            effective_prefix = primary
        elif garage and parts[0] == garage:
            effective_prefix = garage
        else:
            return

        # First-message diagnostic for non-primary prefixes
        if effective_prefix != primary and effective_prefix not in self._seen_prefixes:
            self._seen_prefixes.add(effective_prefix)
            log(f"First MQTT message received from prefix '{effective_prefix}' — "
                f"topic: {topic}")

        # Bridge topics: prefix/bridge/...
        if parts[1] == "bridge":
            if len(parts) >= 3:
                bt = parts[2]
                if bt == "devices":
                    self._process_bridge_devices(payload, effective_prefix)
                elif bt == "state":
                    self._process_bridge_state(payload, effective_prefix)
                elif bt == "info":
                    self._process_bridge_info(payload, effective_prefix)
                elif bt == "health":
                    self._process_bridge_health(payload, effective_prefix)
                elif bt == "event":
                    self._process_bridge_event(payload, effective_prefix)
            return

        # Availability: last path component is "availability"
        # Handles friendly names with embedded slashes correctly
        if parts[-1] == "availability":
            fname = "/".join(parts[1:-1])
            self._process_availability(fname, payload, prefix=effective_prefix)
            return

        # Device state: everything after prefix is the friendly_name
        fname = "/".join(parts[1:])
        self._process_device_state(fname, payload, prefix=effective_prefix)

    def _process_bridge_devices(self, payload, prefix=None):
        """Cache ALL non-coordinator, non-disabled zigbee2mqtt devices.

        After updating the cache, auto-creates any device that is genuinely new
        (i.e. its IEEE address was not present for this prefix before this update).
        The startup flood is avoided by only acting when the cache already held
        entries for this prefix — meaning we have a baseline to compare against.
        """
        if not isinstance(payload, list):
            log(f"Ignoring bridge/devices payload of unexpected type "
                f"{type(payload).__name__} from prefix '{prefix or self._topic_prefix()}'",
                level="WARNING")
            return
        if prefix is None:
            prefix = self._topic_prefix()

        # Snapshot IEEE addresses known for this prefix before the update
        old_ieee = {ieee for ieee, d in self.bridge_devices.items()
                    if d.get("_mqtt_prefix") == prefix}

        old_count = len(self.bridge_devices)
        # Preserve entries from the other prefix; replace only entries for this prefix
        new_cache = {ieee: d for ieee, d in self.bridge_devices.items()
                     if d.get("_mqtt_prefix") != prefix}
        for d in payload:
            ieee = d.get("ieee_address", "")
            if not ieee or d.get("disabled", False):
                continue
            if d.get("type") == "Coordinator":
                # Remember the radio's own ieee — the orphan report must not
                # flag its repeater tile just because the cache excludes it.
                self._coordinator_ieees.add(ieee)
                continue
            entry = dict(d)
            entry["_mqtt_prefix"] = prefix
            new_cache[ieee] = entry
        self.bridge_devices = new_cache
        count = len(self.bridge_devices)
        if self.debug or count != old_count:
            label = f" [{prefix}]" if prefix != self._topic_prefix() else ""
            log(f"Bridge device cache updated{label}: {count} device(s) total")

        # Detect friendly_name renames and prefix migrations for existing devices.
        # Uses ieee_map for O(1) lookup — no full Indigo device iteration needed.
        for ieee, data in new_cache.items():
            if data.get("_mqtt_prefix") != prefix:
                continue
            dev_id = self.ieee_map.get(ieee)
            if dev_id is None:
                continue
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            new_fname      = data.get("friendly_name", "")
            old_fname      = dev.pluginProps.get("friendly_name", "")
            stored_prefix  = dev.pluginProps.get("mqtt_prefix", self._topic_prefix())
            prefix_changed = stored_prefix != prefix
            name_changed   = new_fname and old_fname and new_fname != old_fname

            if prefix_changed or name_changed:
                try:
                    new_props = dict(dev.pluginProps)
                    if prefix_changed:
                        new_props["mqtt_prefix"] = prefix
                    if name_changed:
                        new_props["friendly_name"] = new_fname
                    dev.replacePluginPropsOnServer(new_props)
                    # Repoint the prefix-qualified map on EITHER change — a
                    # prefix migration moves the key even when the name is
                    # unchanged (v1.9.22).
                    with self.maps_lock:
                        self.friendly_name_map.pop((stored_prefix, old_fname), None)
                        self.friendly_name_map[
                            (prefix, new_fname if name_changed else old_fname)] = dev.id
                    if name_changed:
                        try:
                            dev.name = new_fname
                            dev.replaceOnServer()
                        except Exception as e:
                            # A duplicate Indigo name aborts the rename — keep
                            # the old Indigo name but leave props/map (already
                            # updated) on the new friendly_name so MQTT routing
                            # still follows z2m (v1.9.23).
                            log(f"Could not rename Indigo device '{old_fname}' "
                                f"to '{new_fname}' ({e}) — keeping the Indigo "
                                f"name; MQTT routing follows the new "
                                f"friendly_name", level="WARNING")
                    if prefix_changed and name_changed:
                        log(f"Device moved+renamed: '{old_fname}' -> '{new_fname}' "
                            f"(prefix: {stored_prefix} -> {prefix})")
                    elif prefix_changed:
                        log(f"Device moved: '{new_fname}' "
                            f"(prefix: {stored_prefix} -> {prefix})")
                    else:
                        log(f"Device renamed: '{old_fname}' -> '{new_fname}'")
                except Exception as e:
                    log(f"Error updating device '{old_fname}': {e}", level="ERROR")

        # Auto-create devices that are brand new to this prefix.
        # Guard: old_ieee must be non-empty so we skip the initial startup load.
        if old_ieee:
            new_ieee = {ieee for ieee in new_cache
                        if new_cache[ieee].get("_mqtt_prefix") == prefix
                        and ieee not in old_ieee}
            if new_ieee:
                folder_id      = self._ensure_device_folder(DEVICE_FOLDER_NAME)
                existing_names = self._get_existing_friendly_names()
                for ieee in new_ieee:
                    self._try_create_device(new_cache[ieee], folder_id, existing_names)

        # Backfill power_source onto devices created before v2.2.0 stored it.
        # Done HERE rather than in deviceStartComm because the cache is empty at
        # that point — devices start before MQTT connects — so this is the first
        # moment the answer actually exists.
        self._backfill_power_source(prefix)

        # Update the coordinator's deviceCount + lastUpdate (if one exists for this prefix)
        self._update_coordinator(prefix, deviceCount=sum(
            1 for d in self.bridge_devices.values()
            if d.get("_mqtt_prefix") == prefix))

    def _backfill_power_source(self, prefix):
        """Store zigbee2mqtt's power_source on any device still missing it.

        One-time per device: once the prop is set the loop skips it, so this
        costs a dictionary lookup per device on subsequent cache updates.
        Only a value zigbee2mqtt actually reported is written — an empty string
        would look like a considered 'unknown' rather than an absent field.
        """
        for dev in indigo.devices.iter(self.pluginId):
            if dev.deviceTypeId == "z2mCoordinator":
                continue
            props = dev.ownerProps
            if props.get("power_source"):
                continue
            ieee = (props.get("ieee_address") or "").strip()
            entry = self.bridge_devices.get(ieee) if ieee else None
            if not entry or entry.get("_mqtt_prefix") != prefix:
                continue
            source = entry.get("power_source")
            if not source:
                continue
            try:
                with self.props_lock:
                    new_props = dict(dev.pluginProps)
                    new_props["power_source"] = source
                    dev.replacePluginPropsOnServer(new_props)
                dev.refreshFromServer()
                if self._is_mains_powered({"power_source": source}) \
                        and "battery" in dev.states:
                    # Existing mains device carrying a seeded 0 — label it, as
                    # the state itself cannot be removed once it exists.
                    dev.updateStateOnServer("battery", 0, uiValue="Mains")
                    log(f"{dev.name}: mains powered — its battery reading was a "
                        f"seeded 0 and is now labelled accordingly")
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"power_source backfill for '{dev.name}'")

    def _process_bridge_state(self, payload, prefix):
        """Handle prefix/bridge/state.  Payload is either a JSON dict
        {"state": "online"} (newer Z2M) or a bare string "online" (older)."""
        if isinstance(payload, dict):
            state = payload.get("state", "")
        elif isinstance(payload, str):
            state = payload.strip().strip('"')
        else:
            return
        if not state:
            return
        self._bridge_state_cache[prefix] = state
        self._update_coordinator(prefix, status=state)

        # Raise the bridge events on a CHANGE only (v2.1.0).  bridge/state is
        # retained, so it replays on every reconnect — firing on each arrival
        # would announce an outage that never happened.
        previous = self._bridge_status_announced.get(prefix)
        if previous != state:
            self._bridge_status_announced[prefix] = state
            if previous is not None:
                if state == "online":
                    log(f"Zigbee2MQTT bridge '{prefix}' came back online")
                    self._fire_event("bridgeOnline", prefix, prefix)
                else:
                    log(f"Zigbee2MQTT bridge '{prefix}' went {state}",
                        level="WARNING")
                    self._fire_event("bridgeOffline", prefix, prefix)

        if self.debug:
            log(f"Bridge '{prefix}' state: {state}")

    def _process_bridge_info(self, payload, prefix):
        """Handle prefix/bridge/info — comprehensive bridge metadata."""
        if not isinstance(payload, dict):
            log(f"Ignoring bridge/info payload of unexpected type "
                f"{type(payload).__name__} from prefix '{prefix}'", level="WARNING")
            return
        self._bridge_info_cache[prefix] = payload

        kv = {}
        version = payload.get("version", "")
        if version:
            kv["version"] = str(version)
        coord = payload.get("coordinator", {})
        if isinstance(coord, dict):
            ctype = coord.get("type", "")
            if ctype:
                kv["coordinator"] = str(ctype)
        kv["permitJoin"]      = bool(payload.get("permit_join", False))
        permit_end = payload.get("permit_join_end")
        kv["permitJoinEnd"]   = "" if permit_end is None else str(permit_end)
        kv["restartRequired"] = bool(payload.get("restart_required", False))
        log_level = payload.get("log_level", "")
        if log_level:
            kv["logLevel"] = str(log_level)
        net = payload.get("network", {})
        if isinstance(net, dict):
            if "channel" in net:
                try:
                    kv["networkChannel"] = int(net["channel"])
                except (TypeError, ValueError):
                    pass
            if "pan_id" in net:
                try:
                    kv["panId"] = int(net["pan_id"])
                except (TypeError, ValueError):
                    pass
            if "extended_pan_id" in net:
                kv["extendedPanId"] = str(net["extended_pan_id"])

        # Fire the restart-required event on the rising edge only — bridge/info
        # is retained and republished often, and a standing flag is not news.
        was_required = bool(self._bridge_info_previous.get(prefix, False))
        now_required = kv["restartRequired"]
        self._bridge_info_previous[prefix] = now_required
        if now_required and not was_required:
            log(f"Zigbee2MQTT bridge '{prefix}' is asking to be restarted",
                level="WARNING")
            self._fire_event("bridgeRestartRequired", prefix, prefix)

        self._update_coordinator(prefix, **kv)

    def _update_coordinator(self, prefix, **state_kv):
        """Push a batch of state updates to the coordinator device bound to
        this MQTT prefix. Silently no-ops if no coordinator device exists
        for the prefix (user hasn't created one yet)."""
        with self.maps_lock:
            dev_id = self.coordinator_map.get(prefix)
        if dev_id is None:
            return
        try:
            dev = indigo.devices[dev_id]
        except KeyError:
            with self.maps_lock:
                self.coordinator_map.pop(prefix, None)
            return
        state_kv["lastUpdate"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates = [{"key": k, "value": v} for k, v in state_kv.items()
                   if k in dev.states]
        if updates:
            try:
                dev.updateStatesOnServer(updates)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"coordinator '{dev.name}' update")

    # ── bridge/health (v2.1.0) ───────────────────────────────────────────────
    # zigbee2mqtt publishes this every 10 minutes by default and it was being
    # dropped on the floor.  It carries the only estate-wide evidence of a
    # device rejoining or hopping routing parent — leave_count and
    # network_address_changes — which is the answer to "why did that sensor go
    # quiet".  Counters are cumulative since zigbee2mqtt started
    # (reset_on_check defaults to false), so a RISE is the signal, never a
    # non-zero value.

    @staticmethod
    def _format_uptime(seconds):
        """Render an uptime in seconds as a short readable string."""
        try:
            secs = int(float(seconds))
        except (TypeError, ValueError):
            return ""
        if secs < 0:
            return ""
        days, rem   = divmod(secs, 86400)
        hours, rem  = divmod(rem, 3600)
        mins        = rem // 60
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def _process_bridge_health(self, payload, prefix):
        """Update the coordinator and per-device health counters."""
        if not isinstance(payload, dict):
            log(f"bridge/health from '{prefix}' was not a JSON object — ignored",
                level="WARNING")
            return

        os_info   = payload.get("os")      or {}
        proc      = payload.get("process") or {}
        mqtt_info = payload.get("mqtt")    or {}
        devices   = payload.get("devices") or {}

        load = os_info.get("load_average")
        load1 = load[0] if isinstance(load, (list, tuple)) and load else None

        reported = payload.get("response_time")
        try:
            reported_str = datetime.fromtimestamp(
                float(reported) / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            reported_str = ""

        coordinator_states = {
            "healthOsMemoryPercent": os_info.get("memory_percent"),
            "healthOsLoad1":         load1,
            "healthProcessMemoryMb": proc.get("memory_used_mb"),
            "healthProcessUptime":   self._format_uptime(proc.get("uptime_sec")),
            "healthMqttQueued":      mqtt_info.get("queued"),
            "healthMqttPublished":   mqtt_info.get("published"),
            "healthMqttReceived":    mqtt_info.get("received"),
            "healthLastUpdate":      reported_str,
        }
        self._update_coordinator(
            prefix, **{k: v for k, v in coordinator_states.items() if v is not None})

        if isinstance(devices, dict):
            self._process_device_health(devices, prefix)

    def _process_device_health(self, devices, prefix):
        """Write per-device counters and raise events on a genuine rise."""
        previous = self._health_cache.setdefault(prefix, {})
        first_report = not previous

        for ieee, record in devices.items():
            if not isinstance(record, dict):
                continue
            with self.maps_lock:
                dev_id = self.ieee_map.get(ieee)

            leaves  = record.get("leave_count")
            changes = record.get("network_address_changes")
            was     = previous.get(ieee, {})
            previous[ieee] = {"leave_count": leaves,
                              "network_address_changes": changes}

            if dev_id is None:
                continue   # a Zigbee device with no Indigo device — nothing to write
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue

            updates = []
            rate = record.get("messages_per_sec")
            if rate is not None:
                updates.append(("messagesPerSec", round(float(rate), 4)))
            if leaves is not None:
                updates.append(("leaveCount", int(leaves)))
            if changes is not None:
                updates.append(("networkAddressChanges", int(changes)))
            if updates:
                self._apply_updates(dev, updates)

            # On the first sighting of a device there is nothing to compare
            # against, so a non-zero counter is history, not news.  Announcing
            # it would fire every trigger in the house on plugin start.
            #
            # This is belt-and-braces: _counter_rose already returns False when
            # either side is None, which covers the same ground.  Kept because
            # the two guard different things — this one the absence of a prior
            # READING, that one the absence of a VALUE — and a mutation test
            # confirmed each masks the other, so neither alone is pinned.
            if first_report or not was:
                continue
            if self._counter_rose(was.get("leave_count"), leaves):
                log(f"{dev.name}: rejoined the Zigbee network "
                    f"(leave count {was.get('leave_count')} -> {leaves})",
                    level="WARNING")
                self._fire_event("deviceRejoined", prefix, dev.name)
            if self._counter_rose(was.get("network_address_changes"), changes):
                log(f"{dev.name}: changed network address "
                    f"({was.get('network_address_changes')} -> {changes})")
                self._fire_event("deviceAddressChanged", prefix, dev.name)

    @staticmethod
    def _counter_rose(before, after):
        """True only for a real increase between two readings.

        A missing reading on either side means 'unknown', never 'no change' —
        and a counter that went DOWN means zigbee2mqtt restarted, which is not
        a rejoin either.
        """
        if before is None or after is None:
            return False
        try:
            return int(after) > int(before)
        except (TypeError, ValueError):
            return False

    # ── bridge/event (v2.1.0) ────────────────────────────────────────────────
    # Payload shape per the zigbee2mqtt docs:
    #   {"type": "device_joined",    "data": {"friendly_name": .., "ieee_address": ..}}
    #   {"type": "device_announce",  "data": {...}}
    #   {"type": "device_leave",     "data": {...}}
    #   {"type": "device_interview", "data": {..., "status": "started|successful|failed"}}

    _EVENT_TYPE_MAP = {
        "device_joined":   "deviceJoined",
        "device_leave":    "deviceLeft",
        "device_announce": "deviceAnnounced",
    }
    _INTERVIEW_STATUS_MAP = {
        "failed":     "deviceInterviewFailed",
        "successful": "deviceInterviewSuccessful",
    }

    def _process_bridge_event(self, payload, prefix):
        """Turn a bridge/event message into an Indigo trigger event."""
        if not isinstance(payload, dict):
            log(f"bridge/event from '{prefix}' was not a JSON object — ignored",
                level="WARNING")
            return

        etype = payload.get("type")
        data  = payload.get("data") or {}
        name  = (data.get("friendly_name") or data.get("ieee_address") or "unknown")

        event_id = self._EVENT_TYPE_MAP.get(etype)
        if etype == "device_interview":
            status   = str(data.get("status", "")).lower()
            event_id = self._INTERVIEW_STATUS_MAP.get(status)
            if event_id is None:
                if self.debug:
                    log(f"bridge/event interview '{status}' for {name} — "
                        f"no matching Indigo event")
                return
            level = "WARNING" if status == "failed" else "INFO"
            log(f"Zigbee device '{name}' interview {status}", level=level)
        elif event_id is None:
            # An unrecognised event type is worth saying out loud rather than
            # dropping — zigbee2mqtt may add types we don't know about yet.
            log(f"bridge/event: unhandled type '{etype}' for '{name}' on "
                f"'{prefix}'")
            return
        else:
            verb = {"deviceJoined": "joined the network",
                    "deviceLeft":   "left the network",
                    "deviceAnnounced": "announced itself"}[event_id]
            log(f"Zigbee device '{name}' {verb} ({prefix})")

        self._fire_event(event_id, prefix, name)

    def _fire_event(self, event_id, prefix, device_name):
        """Record the event on the coordinator, then execute matching triggers.

        The coordinator states are written FIRST so a trigger's own actions can
        read the device name straight out of them — plugin events carry no
        payload of their own.
        """
        try:
            self._update_coordinator(
                prefix,
                lastEvent=event_id,
                lastEventDevice=device_name,
                lastEventTime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"coordinator event stamp for {event_id}")

        with self.maps_lock:
            triggers = list(self.event_triggers.values())
        for trigger in triggers:
            try:
                if trigger.pluginTypeId != event_id:
                    continue
                indigo.trigger.execute(trigger)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"executing trigger for {event_id}")

    # ── Trigger lifecycle ────────────────────────────────────────────────────
    # Indigo calls these as a trigger of ours is enabled or disabled.  There is
    # no indigo.server.fireEvent and no inherited self.triggerEvent — the only
    # way to raise a plugin event is to hold the trigger objects and call
    # indigo.trigger.execute() on the ones whose pluginTypeId matches.

    def triggerStartProcessing(self, trigger):
        with self.maps_lock:
            self.event_triggers[trigger.id] = trigger
        if self.debug:
            log(f"Watching trigger '{trigger.name}' ({trigger.pluginTypeId})")

    def triggerStopProcessing(self, trigger):
        with self.maps_lock:
            self.event_triggers.pop(trigger.id, None)
        if self.debug:
            log(f"Stopped watching trigger '{trigger.name}'")
