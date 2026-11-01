#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_availability_config.py
# Description: Say so when zigbee2mqtt's availability tracking is turned off.
#
#              The plugin learns a device is dead ONLY from zigbee2mqtt's
#              <prefix>/<device>/availability messages (_process_availability
#              sets the Indigo "offline" error from them). If availability is
#              off in zigbee2mqtt, those never arrive: a leak sensor with a
#              flat battery stays green for ever and nothing says why.
#
#              Two sources of evidence, per bridge prefix:
#                * bridge/info carries zigbee2mqtt's settings under "config".
#                  Its "availability" entry is read tolerantly — a bool in
#                  zigbee2mqtt 1.x, or an object (with "enabled" in 2.x, and
#                  "passive": {"timeout": minutes} for battery devices).
#                  Anything else reads as UNKNOWN, never as a guess.
#                * Any availability message at all proves it is working.
#              When the settings say off, warn at once. When they say nothing,
#              warn if no availability message has arrived AVAILABILITY_WAIT
#              seconds after connecting, while the bridge is online and has
#              devices — zigbee2mqtt retains availability, so with it on the
#              replay arrives within seconds of subscribing.
#
#              The coordinator shows the verdict (availabilityTracking) and how
#              long a battery device may be silent before it counts as offline
#              (batteryOfflineAfter), and Test MQTT Connection lists it.
#
#              A mixin on Plugin; `self` is the Plugin instance throughout.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import time

import z2m_helpers
from z2m_constants import AVAILABILITY_WAIT
from z2m_helpers import _payload_bool


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


def log_activity(*args, **kwargs):
    return z2m_helpers.log_activity(*args, **kwargs)


HOW_TO_TURN_ON = ("Turn it on in zigbee2mqtt (Settings -> Availability, or "
                  "'availability: enabled: true' in configuration.yaml) and "
                  "restart zigbee2mqtt.")


def read_availability_config(info):
    """(enabled, battery_timeout_minutes) from a bridge/info payload.

    Either value is None when the payload does not say. Never guesses: an
    unrecognised shape is "unknown", because a wrong "on" would hide the very
    problem this exists to report, and a wrong "off" would cry wolf.
    """
    if not isinstance(info, dict):
        return None, None
    config = info.get("config")
    if not isinstance(config, dict) or "availability" not in config:
        return None, None
    entry = config["availability"]
    if isinstance(entry, bool):
        return entry, None
    if not isinstance(entry, dict):
        return None, None
    # zigbee2mqtt 1.x: an availability OBJECT meant on (it had no "enabled").
    enabled = _payload_bool(entry["enabled"]) if "enabled" in entry else True
    minutes = None
    passive = entry.get("passive")
    if isinstance(passive, dict) and passive.get("timeout") is not None:
        try:
            minutes = int(float(passive["timeout"]))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None and minutes <= 0:
            minutes = None
    return enabled, minutes


def format_minutes(minutes):
    """1500 -> '25 h', 90 -> '1.5 h', 45 -> '45 min', None -> ''."""
    if minutes is None:
        return ""
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes / 60:g} h"


class AvailabilityConfigMixin:
    """See the file header above."""

    _V219_COORDINATOR_STATES = ("availabilityTracking", "batteryOfflineAfter")

    def _init_availability_config(self):
        """Called from Plugin.__init__."""
        self._avail_config    = {}     # type: dict[str, bool | None]
        self._avail_battery   = {}     # type: dict[str, int | None]
        self._avail_seen      = set()  # type: set[str]
        self._avail_wait_from = {}     # type: dict[str, float]
        self._avail_warned    = set()  # type: set[str]
        self._avail_shown     = {}     # type: dict[str, tuple]

    # ── inputs ───────────────────────────────────────────────────────────────

    def _note_availability_config(self, prefix, info):
        """From _process_bridge_info."""
        enabled, minutes = read_availability_config(info)
        changed = (self._avail_config.get(prefix), self._avail_battery.get(prefix)) \
            != (enabled, minutes) or prefix not in self._avail_config
        self._avail_config[prefix]  = enabled
        self._avail_battery[prefix] = minutes
        if not changed:
            self._show_availability_on_coordinator(prefix)
            return
        if enabled is False and prefix not in self._avail_seen \
                and prefix not in self._avail_warned:
            self._avail_warned.add(prefix)
            log(f"zigbee2mqtt on '{prefix}' has availability turned off, so a "
                f"device that stops responding (a leak sensor with a flat "
                f"battery, say) is never reported offline and never shows an "
                f"error in Indigo. {HOW_TO_TURN_ON}", level="WARNING")
        elif enabled:
            after = format_minutes(minutes)
            log_activity(self,
                         f"zigbee2mqtt on '{prefix}' tracks availability"
                         + (f"; a battery device counts as offline after "
                            f"{after} without a message" if after else ""))
        self._show_availability_on_coordinator(prefix)

    def _note_availability_seen(self, prefix):
        """From the availability route in _process_message — any device."""
        if prefix in self._avail_seen:
            return
        self._avail_seen.add(prefix)
        if prefix in self._avail_warned:
            self._avail_warned.discard(prefix)
            log(f"Availability reports are arriving from zigbee2mqtt on "
                f"'{prefix}' after all — dead devices will be reported")
        self._show_availability_on_coordinator(prefix)

    def _start_availability_wait(self, prefixes):
        """From __connected__: the retained replay is due now."""
        now = time.time()
        for prefix in prefixes:
            self._avail_wait_from[prefix] = now

    # ── the periodic check (runConcurrentThread, via _drain_queue) ───────────

    def _check_availability_reports(self, now=None):
        now = time.time() if now is None else now
        with self.maps_lock:
            routed = {p for (p, _f) in self.friendly_name_map}
        for prefix, since in list(self._avail_wait_from.items()):
            if prefix in self._avail_seen or prefix in self._avail_warned:
                continue
            if self._avail_config.get(prefix) is not None:
                continue   # the settings already answered (off was warned)
            if now - since < AVAILABILITY_WAIT:
                continue
            if not self.mqtt_connected \
                    or self._bridge_state_cache.get(prefix) != "online" \
                    or prefix not in routed:
                continue   # nothing could have arrived; not evidence
            self._avail_warned.add(prefix)
            log(f"No availability reports have arrived from zigbee2mqtt on "
                f"'{prefix}' in {AVAILABILITY_WAIT // 60} minutes, so "
                f"availability is probably turned off. Without it a device "
                f"that stops responding is never reported offline and never "
                f"shows an error in Indigo. {HOW_TO_TURN_ON}", level="WARNING")
            self._show_availability_on_coordinator(prefix)

    # ── outputs ──────────────────────────────────────────────────────────────

    def _availability_verdict(self, prefix):
        """'enabled', 'some devices', 'disabled', 'probably off' or 'unknown'."""
        config = self._avail_config.get(prefix)
        seen   = prefix in self._avail_seen
        if seen and config is False:
            return "some devices"   # off globally, on per device in zigbee2mqtt
        if seen or config is True:
            return "enabled"
        if config is False:
            return "disabled"
        if prefix in self._avail_warned:
            return "probably off"
        return "unknown"

    def _availability_problem(self, prefix):
        """A line for Test MQTT Connection, or ''."""
        verdict = self._availability_verdict(prefix)
        if verdict in ("disabled", "probably off"):
            return (f"availability is {verdict} in zigbee2mqtt on '{prefix}' — "
                    f"dead devices will not be reported")
        return ""

    def _show_availability_on_coordinator(self, prefix):
        verdict = self._availability_verdict(prefix)
        after   = format_minutes(self._avail_battery.get(prefix))
        shown   = (verdict, after)
        if self._avail_shown.get(prefix) == shown:
            return
        self._avail_shown[prefix] = shown
        self._update_coordinator(prefix, availabilityTracking=verdict,
                                 batteryOfflineAfter=after)
