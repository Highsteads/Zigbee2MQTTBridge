#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_link_health.py
# Description: Say so when the plugin can no longer hear zigbee2mqtt, instead of
#              letting every device go on showing its last state as if live.
#
#              Two ways the link can be down, per bridge prefix:
#                * the MQTT broker connection is lost (affects every prefix);
#                * zigbee2mqtt itself reports bridge/state "offline" (one prefix).
#
#              What it does:
#                * The coordinator device's `mqttConnected` state follows the
#                  broker connection at once.
#                * Once a prefix has been down for LINK_DOWN_GRACE seconds,
#                  every device routed through it is put in the Indigo error
#                  state LINK_ERROR ("bridge down"), so DeviceHealthMonitor,
#                  WaterLeakMonitor and the red device list all see it. The
#                  grace stops a watchdog rebuild or a zigbee2mqtt restart
#                  turning the whole house red.
#                * When the link returns, only the errors set HERE are lifted.
#                  A device zigbee2mqtt had already called offline goes back to
#                  "offline", not to healthy; the retained availability replay
#                  then settles every device to zigbee2mqtt's own verdict.
#
#              Rules kept from v2.10.0: the plugin never sets an error on a
#              coordinator (its routine writes would clear one), and a device
#              already in the "offline" error keeps that more specific error.
#
#              A mixin on Plugin; `self` is the Plugin instance throughout.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import z2m_helpers

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None

import time

from z2m_constants import LINK_CHECK_EVERY, LINK_DOWN_GRACE

LINK_ERROR      = "bridge down"   # the Indigo error text this module owns
OFFLINE_ERROR   = "offline"       # owned by _process_availability
PREF_MARK_DOWN  = "markDevicesWhenBridgeDown"


# Late-bound delegate, for the same reason as every other mixin: z2m_helpers
# stays the single owner of logging and the single place a test patches it.
def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


class LinkHealthMixin:
    """See the file header above."""

    def _init_link_health(self):
        """Called from Plugin.__init__."""
        self._broker_down_since   = None   # type: float | None
        self._bridge_down_since   = {}     # type: dict[str, float]
        self._link_marked         = {}     # type: dict[int, str]   dev id -> prefix
        self._link_down_announced = set()  # type: set[str]
        self._coord_mqtt_shown    = {}     # type: dict[str, bool]
        self._last_link_check     = 0.0

    # ── inputs ───────────────────────────────────────────────────────────────

    def _note_bridge_state(self, prefix, state):
        """From _process_bridge_state: start or stop this prefix's down clock."""
        if state == "online":
            self._bridge_down_since.pop(prefix, None)
        elif prefix not in self._bridge_down_since:
            self._bridge_down_since[prefix] = time.time()

    def _restart_link_clocks(self):
        """After Mac wake: time spent asleep is not an outage. Without this the
        pre-sleep timestamp would make the grace look long expired and turn
        every device red for the second before the reconnect lands."""
        now = time.time()
        if self._broker_down_since is not None:
            self._broker_down_since = now
        for prefix in list(self._bridge_down_since):
            self._bridge_down_since[prefix] = now

    def _mark_devices_enabled(self):
        raw = self.pluginPrefs.get(PREF_MARK_DOWN, True)
        return str(raw).strip().lower() not in ("false", "0", "no", "off", "")

    # ── the periodic check (runConcurrentThread, via _drain_queue) ───────────

    def _check_link_health(self, now=None):
        now = time.time() if now is None else now
        if now - self._last_link_check < LINK_CHECK_EVERY:
            return
        self._last_link_check = now

        connected = bool(self.mqtt_connected) and self.mqtt_client is not None
        if connected:
            self._broker_down_since = None
        elif self._broker_down_since is None:
            self._broker_down_since = now

        self._show_mqtt_on_coordinators(connected)

        with self.maps_lock:
            routed = list(self.friendly_name_map.items())
        prefixes = {p for (p, _f), _d in routed}
        prefixes.update(p for p in (self._topic_prefix(), self._garage_prefix()) if p)

        for prefix in sorted(prefixes):
            reason = self._link_down_reason(prefix, now)
            if reason and self._mark_devices_enabled():
                dev_ids = [d for (p, _f), d in routed if p == prefix]
                self._mark_link_down(prefix, reason, dev_ids)
            else:
                self._clear_link_down(prefix)

    def _link_down_reason(self, prefix, now):
        """Why `prefix` has been unreachable for longer than the grace, or ""."""
        if self._broker_down_since is not None \
                and now - self._broker_down_since >= LINK_DOWN_GRACE:
            return "the MQTT broker connection is lost"
        since = self._bridge_down_since.get(prefix)
        if since is not None and now - since >= LINK_DOWN_GRACE:
            return "zigbee2mqtt reports the bridge offline"
        return ""

    def _show_mqtt_on_coordinators(self, connected):
        with self.maps_lock:
            prefixes = list(self.coordinator_map)
        for prefix in prefixes:
            if self._coord_mqtt_shown.get(prefix) is connected:
                continue
            self._coord_mqtt_shown[prefix] = connected
            self._update_coordinator(prefix, mqttConnected=connected)

    # ── marking and clearing ─────────────────────────────────────────────────

    def _mark_link_down(self, prefix, reason, dev_ids):
        newly = 0
        for dev_id in dev_ids:
            if dev_id in self._link_marked:
                continue
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            if dev.errorState == OFFLINE_ERROR:
                continue   # zigbee2mqtt's own verdict is the more specific one
            try:
                dev.setErrorStateOnServer(LINK_ERROR)
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"bridge-down error for '{dev.name}'")
                continue
            self._link_marked[dev_id] = prefix
            newly += 1
        if prefix not in self._link_down_announced:
            self._link_down_announced.add(prefix)
            log(f"Cannot hear zigbee2mqtt on '{prefix}': {reason} for over "
                f"{LINK_DOWN_GRACE // 60} minutes. {newly} device(s) marked "
                f"'{LINK_ERROR}' — their states are the last ones heard, not "
                f"live — until it returns.", level="WARNING")

    def _clear_link_down(self, prefix):
        mine = [d for d, p in self._link_marked.items() if p == prefix]
        restored = 0
        for dev_id in mine:
            self._link_marked.pop(dev_id, None)
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            if dev.errorState != LINK_ERROR:
                continue   # availability has already given its own verdict
            try:
                if dev.states.get("availability") == OFFLINE_ERROR:
                    dev.setErrorStateOnServer(OFFLINE_ERROR)
                else:
                    dev.setErrorStateOnServer(None)
                restored += 1
            except Exception as e:
                self.exception_handler(e, log_failing_statement=True,
                                       context=f"clearing bridge-down on '{dev.name}'")
        if prefix in self._link_down_announced:
            self._link_down_announced.discard(prefix)
            log(f"zigbee2mqtt on '{prefix}' is reachable again — "
                f"'{LINK_ERROR}' lifted from {restored} device(s)")

    def _forget_link_mark(self, dev):
        """deviceStopComm: a stopped device is no longer ours to clear."""
        self._link_marked.pop(dev.id, None)

    # ── finding 1: refresh after a reconnect ─────────────────────────────────

    # Types that are always mains powered in practice, for devices whose
    # power_source zigbee2mqtt has not reported yet.
    _REFRESH_TYPES_WITHOUT_POWER_SOURCE = ("z2mLight", "z2mRelay", "z2mCover")

    def _refresh_after_connect(self, prefixes):
        """Ask every started mains device on these prefixes for its state.

        zigbee2mqtt does not retain device state by default, so after the
        broker link drops nothing tells us what changed meanwhile. Battery
        devices are skipped: they are asleep, cannot answer a /get, and
        zigbee2mqtt logs an error for each one asked. Groups are skipped too:
        their state follows from their members' answers.

        Returns how many devices were asked.
        """
        wanted = set(prefixes)
        with self.maps_lock:
            routed = [(p, f, d) for (p, f), d in self.friendly_name_map.items()
                      if p in wanted]
        asked = 0
        for prefix, fname, dev_id in routed:
            try:
                dev = indigo.devices[dev_id]
            except KeyError:
                continue
            type_id = dev.deviceTypeId
            if type_id in ("z2mGroupLight", "z2mGroupRelay"):
                continue
            props = dev.pluginProps
            if props.get("power_source"):
                if not self._is_mains_powered(props):
                    continue
            elif type_id not in self._REFRESH_TYPES_WITHOUT_POWER_SOURCE:
                continue
            self._schedule_state_request(dev_id, fname, type_id, prefix,
                                         dev_props=dict(props))
            asked += 1
        return asked
