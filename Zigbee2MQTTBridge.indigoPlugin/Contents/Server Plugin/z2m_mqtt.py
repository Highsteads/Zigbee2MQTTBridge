#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_mqtt.py
# Description: The MQTT client itself: broker resolution, connect/disconnect lifecycle,
#              the application-level liveness backstop that catches a wedged
#              half-open socket, publishing, and the paho callbacks.
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

import json
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from z2m_constants import (
    MQTT_SILENCE_LIMIT, MQTT_WATCHDOG_EVERY, RECONNECT_DELAY,
)
import z2m_secrets

# The credentials are read through the MODULE, not imported by name, for the
# same late-binding reason as log(): `from z2m_secrets import MQTT_PORT` would
# freeze the value at import, so a test (or a future reload path) patching
# z2m_secrets would have no effect here and the mismatch would be silent.


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


class MqttMixin:
    """See the file header above."""

    # ── MQTT internals ────────────────────────────────────────────────────────

    def _effective_broker(self):
        # IndigoSecrets first, PluginConfig fallback, "" if neither set.
        return z2m_secrets.MQTT_BROKER or self.pluginPrefs.get("mqtt_broker", "").strip()

    def _effective_port(self):
        if z2m_secrets.MQTT_PORT:
            # IndigoSecrets may hold the port as a string ("1883") — paho.connect
            # needs an int, so coerce it here too rather than trusting the type.
            try:
                return int(z2m_secrets.MQTT_PORT)
            except (TypeError, ValueError):
                log(f"Invalid MQTT_PORT in IndigoSecrets ({z2m_secrets.MQTT_PORT!r}) — using 1883",
                    level="WARNING")
                return 1883
        raw = self.pluginPrefs.get("mqtt_port", "1883") or 1883
        try:
            return int(raw)
        except (TypeError, ValueError):
            log(f"Invalid Broker Port in plugin config ({raw!r}) — using 1883",
                level="WARNING")
            return 1883

    def _topic_prefix(self):
        return self.pluginPrefs.get("mqtt_topic_prefix", "zigbee2mqtt").strip()

    def _garage_prefix(self):
        """Return the optional garage Z2M topic prefix, or None if not configured."""
        p = self.pluginPrefs.get("mqtt_garage_topic_prefix", "").strip()
        return p if p else None

    def _device_prefix(self, dev):
        """Return the MQTT topic prefix for a device (stored per-device, falls back to primary)."""
        return dev.pluginProps.get("mqtt_prefix", self._topic_prefix())

    def _start_mqtt(self):
        with self.mqtt_lock:
            self._start_mqtt_locked()

    def _start_mqtt_locked(self):
        """Body of _start_mqtt — the caller MUST already hold self.mqtt_lock."""
        if mqtt is None:
            log("paho-mqtt not available — cannot connect. Check requirements.txt installation.", level="ERROR")
            return

        # Defensive: a mispaired call while a client is already live would
        # orphan its running network thread (every message then delivered
        # twice). Tear the old one down first (v1.9.23).
        if self.mqtt_client is not None:
            log("MQTT start requested while a client is already running — "
                "stopping the old client first", level="WARNING")
            self._stop_mqtt_locked()

        broker   = self._effective_broker()
        port     = self._effective_port()
        username = z2m_secrets.MQTT_USERNAME or self.pluginPrefs.get("mqtt_username", "").strip()
        password = z2m_secrets.MQTT_PASSWORD or self.pluginPrefs.get("mqtt_password", "")

        if not broker:
            # First-run awaiting configuration is EXPECTED — not red (INFO per
            # the estate convention; v1.9.23).
            log("MQTT broker not configured yet. Set MQTT_BROKER in IndigoSecrets.py OR "
                "fill Broker Host in Plugins -> Zigbee2MQTT Bridge -> Configure.")
            return

        # Snapshot the topic prefixes as plain strings for the paho-thread
        # callbacks — _on_mqtt_connect must not read self.pluginPrefs (an
        # indigo.Dict) off the Indigo main thread (v1.9.23).
        self._subscribed_prefixes = tuple(
            p for p in (self._topic_prefix(), self._garage_prefix()) if p)

        try:
            # paho 2.x (v2.0.0): callback_api_version is a REQUIRED first
            # positional — without it 2.x raises ValueError and the bridge
            # never connects. VERSION2 callbacks carry ReasonCode objects.
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id=f"indigo_z2mbridge_{int(time.time())}")
            if username:
                client.username_pw_set(username, password)
            client.on_connect      = self._on_mqtt_connect
            client.on_disconnect   = self._on_mqtt_disconnect
            client.on_message      = self._on_mqtt_message
            # v1.10.0: an unreachable broker used to be completely silent —
            # paho retries connect_async forever without ever reporting.
            client.on_connect_fail = self._on_mqtt_connect_fail
            client.reconnect_delay_set(min_delay=5, max_delay=RECONNECT_DELAY)
            client.connect_async(broker, port, keepalive=60)
            client.loop_start()
            self.mqtt_client = client
            log(f"MQTT connecting to {broker}:{port}")
        except Exception as e:
            log(f"MQTT connect error: {e}", level="ERROR")

    def _stop_mqtt(self):
        with self.mqtt_lock:
            self._stop_mqtt_locked()

    def _stop_mqtt_locked(self):
        """Body of _stop_mqtt — the caller MUST already hold self.mqtt_lock."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client    = None
            self.mqtt_connected = False

    def _rebuild_mqtt(self):
        """Atomically tear down and rebuild the MQTT client under a SINGLE lock
        acquisition, so no other thread can slip a _start_mqtt between the stop and
        the start. Two threads run this sequence — the liveness watchdog (on
        runConcurrentThread) and closedPrefsConfigUi (Indigo's config thread) — and
        if they interleave a bare _stop_mqtt() + _start_mqtt() pair, both _start
        calls run, the second self.mqtt_client store orphans the first client's
        still-running network thread, and every message is then delivered twice.
        Both callers MUST use this, never a separate stop-then-start."""
        with self.mqtt_lock:
            self._stop_mqtt_locked()
            self.last_rx_ts = time.time()   # give the rebuild a full fresh window
            self._start_mqtt_locked()

    def _mqtt_liveness_check(self):
        """Self-heal backstop: paho's loop_start auto-reconnect can wedge on a
        half-open socket after a network blip without firing on_disconnect (this is
        what left Jane Lamp dead on 29-05-2026 — "sent" logged into a dead socket,
        zero inbound, mqtt_connected still True). If no MQTT message has arrived for
        MQTT_SILENCE_LIMIT seconds, tear the client down and rebuild it from scratch,
        regardless of what mqtt_connected reports."""
        now = time.time()
        if now - self._last_mqtt_check < MQTT_WATCHDOG_EVERY:
            return
        self._last_mqtt_check = now
        if self.mqtt_client is None:
            return  # not started, or deliberately stopped
        silent = now - self.last_rx_ts
        limit  = self._silence_limit()
        if silent <= limit:
            self._probe_sent_ts = 0.0   # traffic flowing — clear any stale probe
            return

        # v1.9.22: silence alone can't distinguish a wedged socket from a
        # legitimately QUIET network (keepalive PINGRESPs don't fire on_message
        # — a sparse install with a few battery sensors would rebuild every
        # cycle forever). Two-stage check: first PROBE — request the device
        # list, whose response arrives on the existing prefix/# subscription
        # and stamps last_rx_ts. Only if a probe is still unanswered by the
        # NEXT watchdog tick is the socket declared wedged and rebuilt.
        if self._probe_sent_ts and self.last_rx_ts < self._probe_sent_ts:
            log(f"MQTT silent for {silent:.0f}s (limit {limit}s) and liveness "
                f"probe unanswered — rebuilding connection (paho loop assumed "
                f"wedged)", level="WARNING")
            self._probe_sent_ts = 0.0
            self._rebuild_mqtt()
            return
        prefix = self._topic_prefix()
        if self._publish(f"{prefix}/bridge/request/devices", {}):
            self._probe_sent_ts = now
            if self.debug:
                log(f"MQTT silent for {silent:.0f}s — sent liveness probe "
                    f"(bridge/request/devices), will rebuild if unanswered")
        else:
            # Client says it isn't even connected — no point probing.
            log(f"MQTT silent for {silent:.0f}s (limit {limit}s) and client "
                f"reports not connected — rebuilding", level="WARNING")
            self._probe_sent_ts = 0.0
            self._rebuild_mqtt()

    def _silence_limit(self):
        """Watchdog silence limit in seconds — configurable for sparse/quiet
        installs (pref mqtt_silence_limit), guarded coercion, floor of 60s."""
        try:
            return max(60, int(self.pluginPrefs.get("mqtt_silence_limit",
                                                    MQTT_SILENCE_LIMIT)))
        except (TypeError, ValueError):
            return MQTT_SILENCE_LIMIT

    def _publish(self, topic, payload):
        """Publish a JSON payload to an MQTT topic.

        Returns True only when the message was accepted by a live client with a
        success rc — False when not connected, on a non-zero publish rc, or on
        exception. Callers that report 'sent ...' to the user MUST check this
        (v1.9.22): before, a command dropped on a disconnected/wedged client
        still logged as sent."""
        with self.mqtt_lock:
            if not self.mqtt_connected or not self.mqtt_client:
                log(f"MQTT not connected — cannot publish to {topic}", level="WARNING")
                return False
            try:
                info = self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
                rc = getattr(info, "rc", 0)
                if rc != 0:
                    log(f"MQTT publish rc={rc} on {topic} — message not queued",
                        level="WARNING")
                    return False
                if self.debug:
                    log(f"MQTT publish -> {topic}: {payload}")
                return True
            except Exception as e:
                log(f"MQTT publish error on {topic}: {e}", level="ERROR")
                return False

    def _publish_cmd(self, topic, payload, dev, verb):
        """Publish a device command and log honestly: 'sent ...' only when the
        publish was actually handed to a live client, an ERROR naming the
        device otherwise (the _publish WARNING alone doesn't say WHICH device's
        command was lost)."""
        if self._publish(topic, payload):
            log(f'sent "{dev.name}" {verb}')
            return True
        log(f'FAILED to send "{dev.name}" {verb} — command not delivered',
            level="ERROR")
        return False

    def _request_state(self, friendly_name, device_type_id="z2mSensor", prefix=None,
                       dev_props=None):
        """Ask zigbee2mqtt to publish the current state for a device.

        When dev_props is supplied, the z2mLight /get payload only asks for the
        colour fields the bulb actually supports — requesting color/color_temp
        from a plain dimmable bulb makes z2m log an error per request (v1.9.23).

        Quietly a no-op while disconnected (v2.0.0): these are best-effort
        refreshes — retained payloads reseed every device on reconnect, and a
        broker outage at startup used to spray one WARNING per device from the
        settle-delay timers."""
        if not self.mqtt_connected:
            if self.debug:
                log(f"skipping state request for '{friendly_name}' — MQTT not connected")
            return
        if prefix is None:
            prefix = self._topic_prefix()
        if device_type_id == "z2mThermostat":
            self._publish(f"{prefix}/{friendly_name}/get",
                          {"local_temperature": "",
                           "current_heating_setpoint": "",
                           "system_mode": ""})
            return
        if device_type_id == "z2mLight" and dev_props is not None:
            payload = {"state": "", "brightness": ""}
            if dev_props.get("has_color_temp"):
                payload["color_temp"] = ""
            if dev_props.get("has_color"):
                payload["color"] = ""
            if dev_props.get("has_color_temp") or dev_props.get("has_color"):
                payload["color_mode"] = ""
            self._publish(f"{prefix}/{friendly_name}/get", payload)
            return
        if device_type_id == "z2mLight":
            payload = {"state": "", "brightness": "", "color_temp": "", "color": "", "color_mode": ""}
        else:
            payload = {"state": ""}
        self._publish(f"{prefix}/{friendly_name}/get", payload)

    # ── paho callbacks (run on paho thread — queue only, no Indigo calls) ─────

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        # paho 2.x VERSION2 signature (v2.0.0): reason_code is a ReasonCode
        # object (is_failure/str), properties is None on MQTT 3.1.1, flags is a
        # ConnectFlags dataclass (unused here).
        if not reason_code.is_failure:
            self.mqtt_connected = True
            self.last_rx_ts     = time.time()   # fresh connection — reset the liveness clock
            # A successful connect re-arms the once-per-outage failure reporting.
            self._connect_fail_reported = False
            self._last_connect_fail_msg = None
            # Prefixes were snapshotted as plain strings at client-build time —
            # no self.pluginPrefs (indigo.Dict) reads on the paho thread.
            subscribed = []
            for prefix in getattr(self, "_subscribed_prefixes", ()) or ("zigbee2mqtt",):
                client.subscribe(f"{prefix}/#", qos=1)
                subscribed.append(f"{prefix}/#")
            # No log() here — this runs on the paho thread ("queue only, no
            # Indigo calls"); the __connected__ handler logs it on the main thread.
            self.msg_queue.put(("__connected__", {"subscribed": subscribed}))
        else:
            # str(ReasonCode) is already human-readable ("Not authorized",
            # "Bad user name or password", ...). Under VERSION2 even a 3.1.1
            # broker's CONNACK errors arrive as MQTT-v5 reason codes, so the
            # old 1-5 int label table could never match again — deleted (v2.0.0).
            msg = f"MQTT connect failed: {reason_code}"
            # paho retries forever — a wrong password used to produce this
            # ERROR on EVERY reconnect attempt. Report each distinct reason
            # once per outage (v1.10.0); a successful connect re-arms.
            if msg != self._last_connect_fail_msg:
                self._last_connect_fail_msg = msg
                self.msg_queue.put(("__error__", {
                    "msg": f"{msg} — will keep retrying quietly"}))

    def _on_mqtt_connect_fail(self, client, userdata):
        """paho callback (paho thread): the async connect attempt failed at the
        network level (broker unreachable/refused). Without this, an
        unreachable broker is completely silent (v1.10.0). Reported once per
        outage — paho retries forever."""
        if not self._connect_fail_reported:
            self._connect_fail_reported = True
            self.msg_queue.put(("__error__", {
                "msg": "MQTT broker unreachable — check host/port and that the "
                       "broker is running (will keep retrying quietly)"}))

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags,
                            reason_code, properties=None):
        # paho 2.x VERSION2 signature (v2.0.0). Normalise at the boundary so
        # the main-thread __disconnected__ route keeps its int semantics
        # (0 = clean); carry the readable reason for the log line.
        self.mqtt_connected = False
        try:
            rc_val = int(reason_code.value)
        except (AttributeError, TypeError, ValueError):
            rc_val = 0 if reason_code in (0, None) else 1
        self.msg_queue.put(("__disconnected__",
                            {"rc": rc_val, "reason": str(reason_code)}))

    def _on_mqtt_message(self, client, userdata, msg):
        self.last_rx_ts = time.time()   # liveness: any inbound message proves the link is alive
        try:
            raw = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return  # binary payload
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Older Z2M publishes bare strings like `online` on bridge/state.
            # Pass the raw decoded string through so handlers can deal with it.
            payload = raw
        self.msg_queue.put((msg.topic, payload))
