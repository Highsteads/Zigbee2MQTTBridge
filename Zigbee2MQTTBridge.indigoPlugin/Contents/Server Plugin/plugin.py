#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Zigbee2MQTT Bridge — general zigbee2mqtt device integration for Indigo.
#              Auto-discovers all device types (lights, relays, sensors, covers) from
#              the zigbee2mqtt bridge and creates matching Indigo devices in a
#              "Zigbee2MQTT" device folder via Plugins > Discover & Create Devices.
# Author:      CliveS & Claude Opus 4.8
# Date:        21-07-2026
# Version:     2.0.2
#
# v2.0.2 (21-07-2026): shared plugin_utils.py refreshed to v1.3 — the
# estate-wide propagation of the four Appliance Monitor deep-review fixes.
# * install_timestamp_filter() is idempotent — a second call used to stack a
#   second filter, so every log line came out with two timestamps.
# * `import indigo` is soft, so the module imports outside the Indigo host and
#   can be exercised by offline tests.
# * A malformed log call keeps its arguments in the log instead of dropping
#   them, so a %-placeholder mismatch is visible.
# * New shared as_bool() — a pref re-serialised as the string "false" is
#   truthy, which is exactly the wrong answer.
# This bundle's local duplicate-install guard is superseded by the shared one,
# and its child-logger note is folded into the shared comment.
#
# v2.0.0 (16-07-2026): paho-mqtt 1.6.1 -> 2.1.0 migration (the one deliberately
#   deferred structural item from the deep reviews). Isolated change:
#   * mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=...) — the
#     callback_api_version positional is REQUIRED in 2.x (without it the
#     client constructor raises and the bridge never connects).
#   * _on_mqtt_connect(client, userdata, flags, reason_code, properties) —
#     success is `not reason_code.is_failure`; the old int rc_labels dict is
#     DELETED (under VERSION2 even a 3.1.1 broker's CONNACK errors arrive as
#     MQTT-v5 ReasonCodes, e.g. bad credentials = 134 not 4, so the 1-5 keys
#     could never match again; str(ReasonCode) is already human-readable).
#   * _on_mqtt_disconnect(client, userdata, disconnect_flags, reason_code,
#     properties) — normalised at the boundary to {"rc": int, "reason": str}
#     so the main-thread route keeps its int semantics; the unexpected-
#     disconnect WARNING now includes the readable reason.
#   * on_message / on_connect_fail / username_pw_set / reconnect_delay_set /
#     connect_async / loop_start / loop_stop / disconnect: signature-identical
#     in 2.x — unchanged.
#   * The v1.9.14 liveness watchdog + v1.9.19 atomic rebuild carry over
#     UNCHANGED — verified to hold no 1.x assumptions (no flags dict access,
#     no is_connected, no internal-thread poking); 2.x improves some reconnect
#     edge cases but does not guarantee the half-open-socket wedge is gone.
#   * requirements.txt pin 2.1.0 with the migration recorded; tests use a
#     paho-free FakeReasonCode (conftest) so the suite still needs no
#     third-party packages. 4 callback call-sites updated.
# v1.10.0 (16-07-2026): Fable 5 deep-review feature batch (improvement lens).
#   * NEW z2mLock device type (relay class, Lock subtype): lock composites no
#     longer classify as relays sent ON/OFF — locks speak LOCK/UNLOCK, richer
#     lock_state enum in a custom state (not_fully_locked reads as unlocked),
#     onOffState ON = locked.
#   * NEW z2mThermostat device type (thermostat class): climate composites
#     (TRVs) get native temperatureInput1 / setpointHeat / hvacOperationMode
#     with actionControlThermostat (set/raise/lower heat setpoint, HVAC mode
#     heat/auto/off, status request), running_state + read-only valve
#     `position` in custom states, and a setpoint_key prop remembering whether
#     the device speaks current_ or occupied_heating_setpoint.
#   * NEW "Publish Custom Payload" device action — user JSON to /set for the
#     device options no typed action covers (validated at dialog save).
#   * NEW menu items: Test MQTT Connection (banner + live checks in one log
#     dump), Report Orphaned Devices (in Indigo but gone from z2m — report
#     only), Enable/Disable Pairing (permit_join to every configured bridge).
#   * z2m last_seen now surfaces as a readable `lastSeen` dynamic state
#     (handles both ms-epoch and ISO formats) instead of being swallowed.
#   * Connection diagnostics: paho's on_connect_fail is registered (an
#     unreachable broker was completely silent) and CONNACK failures (bad
#     credentials etc.) are reported once per outage instead of every retry.
#   * showPluginInfo gains liveness lines (last message age, queue depth,
#     silence limit) shared with the connection test via _banner_extras.
#   * Tests 597 -> 624 (+2 zoo rows: door_lock, trv reclassified from the
#     v1.9.21 sensor stopgap to z2mThermostat).
#   * NOT implemented (judged net-negative): a dynamic friendly-name menu in
#     device config — devices are auto-created (typing a name is the rare
#     path) and an empty-cache menu would BLOCK manual creation entirely.
# v1.9.23 (16-07-2026): Fable 5 deep-review batch 3 (lows + infos).
#   * wake_up reorders: MQTT reconnect BEFORE super() (device comm) so the
#     settle-delay /get requests no longer race a not-yet-connected client.
#   * stopConcurrentThread override REMOVED — it discarded the base class's
#     pipe-wake, making shutdown wait out the sleep interval.
#   * coordinator_map joins the maps_lock discipline at its last two unlocked
#     sites; new props_lock serialises pluginProps read-modify-write cycles
#     between the consumer thread and menu-thread refresh (deliberately held
#     across replacePluginPropsOnServer — an interleaved RMW silently drops
#     one side's changes); refresh now merges only its diff keys onto a fresh
#     read.
#   * _start_mqtt_locked stops an already-running client instead of orphaning
#     its network thread; on_connect uses a plain-string prefix snapshot (no
#     indigo.Dict reads on the paho thread); 'broker not configured' is INFO
#     not ERROR (estate convention).
#   * validatePrefsConfigUi validates mqtt_port + mqtt_silence_limit at the
#     dialog; _effective_port's prefs fallback logs a WARNING when invalid.
#   * _payload_bool sweep: contact/water_leak/motion-store handlers no longer
#     read string tokens ("false"/"OFF") as True.
#   * _brightness_255_to_100 rounds (readback matches the set level; z2m max
#     254 still reads 100); capability-gated /get (plain bulbs no longer make
#     z2m log errors for color/color_temp requests).
#   * Rename collision: a duplicate Indigo name no longer aborts the z2m
#     rename — props + routing follow z2m, Indigo name kept with a WARNING.
#   * _reclassify_as_button derives has_battery from current exposes (was
#     hardcoded False and never healed); z2mButton gains _DEVICE_STATE_DEFAULTS
#     + battery gate; z2mCover tiltAngle gated on has_tilt.
#   * _apply_updates logs the FIRST write failure per (device, state) at
#     WARNING (was debug-only silent data loss), repeats stay quiet.
#   * getDeviceStateList: dev.states=None at declaration time no longer
#     crashes the token-None fallback; dead _flatten_features removed;
#     colorMode gated on colour capability; repeaters reject on/off commands
#     with a WARNING instead of publishing them.
#   * plugin_utils.install_timestamp_filter gains a duplicate-install guard;
#     master IndigoSecrets template: MQTT_BROKER placeholder now "" (a truthy
#     placeholder beat the config dialog), MQTT section attributed, per-key
#     try/except import pattern documented.
#   * Tests 579 -> 597 (Actions.xml callbacks, not-connected paths, repeater
#     guard, warn-once, prefs validation, string tokens per handler, gated
#     /get); conftest dead code + stale fixture version cleaned; the
#     assertion-free JSON-stringify test now asserts.
# v1.9.22 (16-07-2026): Fable 5 deep-review batch 2 (mediums).
#   * Cross-bridge routing: friendly_name_map is now keyed by
#     (mqtt_prefix, friendly_name) — a name shared between the house and
#     garage bridges used to collide into one entry, bleeding one device's
#     state onto the other and blocking the second from ever being created.
#     All lookups (state routing, availability, creation exists-check,
#     capability-refresh fname fallback, rename/prefix-migration, reclassify)
#     are prefix-qualified; a prefix migration now moves the map key even
#     without a rename.
#   * Honest command logging: _publish returns True only when the message was
#     accepted by a live client (connected + rc==0); new _publish_cmd logs
#     'sent ...' on success and an ERROR naming the device on failure — the
#     action handlers no longer claim 'sent' for commands that died on a
#     disconnected/wedged client.
#   * Watchdog: two-stage liveness check — on silence it first PROBES
#     (bridge/request/devices, whose reply arrives on the existing
#     subscription) and only rebuilds if the probe is still unanswered at the
#     next tick, so a legitimately QUIET network (sparse install) no longer
#     triggers an endless rebuild cycle. Silence limit is now a guarded pref
#     (mqtt_silence_limit, min 60s, default 300).
#   * _hs_to_rgb: saturation divides by 100 not 255 — z2m publishes color_hs
#     saturation 0-100, so reported colours were capped at ~39% saturation.
#   * Discover & Create resilience: detection/props-build moved inside the
#     per-device try; malformed (non-dict) exposes entries skipped in
#     _detect_device_type, _should_reclassify_as_button and _iter_features —
#     one bad definition costs only itself, not the whole pass.
#   * deviceStartComm's settle-delay Timer is tracked per-device, daemonised,
#     and cancelled on deviceStopComm/shutdown (was fire-and-forget).
#   * smoke joined the capability system: has_smoke detection, seeded state
#     with gate (completes v1.9.21's semantic handling for existing devices).
#   * Tests 551 -> 579: cross-bridge collision suite, probe state machine,
#     publish honesty, saturation scale, first-ever coverage for
#     deviceStartComm happy path / didDeviceCommPropertyChange /
#     _ensure_device_states gating / refresh_device_capabilities; stub gained
#     opt-in strict state writes; the v1.9.9 reclassify test's indigo.device
#     replacement is now monkeypatched (no longer leaks) and its assertion
#     can no longer pass vacuously.
# v1.9.21 (16-07-2026): Fable 5 deep-review batch 1 (highs).
#   * HIGH classification: a device with an action enum AND an output capability
#     (switch composite or writable binary state) is now created as z2mRelay,
#     not z2mButton — decoupled-mode wall switches were losing on/off control
#     PERMANENTLY at Discover & Create (reclassify only converts toward button,
#     so nothing could heal it). Detection now mirrors the gates
#     _should_reclassify_as_button already enforced at runtime; the gate also
#     gained motion/pir alongside presence/occupancy (both places).
#   * HIGH data loss: the global _HANDLED_PAYLOAD_KEYS set claimed keys NO
#     handler wrote (smoke/vibration/tamper/voltage/current/battery_low were
#     blocked from dynamic capture yet never written — a smoke alarm produced
#     NO Indigo state change at all) and claimed keys globally that only some
#     types handle (a contact sensor's temperature, a bulb's power — silently
#     dropped). Replaced with per-type _HANDLED_KEYS_BY_TYPE +
#     _ALWAYS_CONSUMED_KEYS; everything a type's handler doesn't own is now
#     dynamically captured as a typed state.
#   * HIGH safety: smoke is handled semantically on z2mSensor — declared bool
#     `smoke` state + onOffState priority smoke > water_leak > occupancy >
#     contact, with _payload_bool guarding string tokens ("false" is False).
#   * Cover gate: a flat `position` feature only classifies as z2mCover when
#     WRITABLE and there is no climate composite — TRVs exposing a read-only
#     valve-position % were being created as blinds.
#   * Tests 474 -> 551: per-type capture, smoke semantics, classification gates,
#     reclassify map-repoint regression (v1.9.18 fix now locked in),
#     bridge/devices rename + prefix-migration + auto-create + flood-guard
#     paths, getDeviceStateList dynamic declarations (stub gained the
#     state-dict builders + an indigo.device create/delete shim), 6 new zoo rows.
#   * Companion: startup_z2m_check.py -> v1.6 (mosquitto alert debounce + storm
#     fix, subprocess timeouts, flock'd overlap guard, plugin-running check,
#     format-drift fallback, pgrep -x, main() wrapper).
# v1.9.20 (27-06-2026): deep-review batch 3 — cleared the entire deferred queue.
#   * #18 concurrency: friendly_name_map / ieee_map / coordinator_map are now
#     guarded by self.maps_lock (RLock) at every mutation site (deviceStartComm,
#     deviceStopComm, reclassify rebuilds, bridge/devices rename), so a
#     comprehension rebuild can't race a concurrent pop into a RuntimeError. Lock
#     held only for pure dict ops, never across an indigo.* call.
#   * #13: a dynamic payload field whose sanitised key collides with a static
#     Devices.xml state (e.g. snake-case `link_quality` -> `linkQuality`) is no
#     longer captured + written with a possibly-mismatched dynamic type
#     (_static_state_ids guard).
#   * #29: orphan dynamicKeyTypes entries are pruned in lock-step with
#     seenDynamicKeys (the two persisted stores no longer drift).
#   * #16: a dimmer reporting brightness 0 now forces onOffState off (some bulbs
#     publish {"state":"ON","brightness":0} during a fade-to-off).
#   * #17: the auto-reclassify-to-button trigger requires a NAMED action (one
#     carrying a letter), so a bare button-index "2" / junk can't drive a
#     destructive delete+recreate.
#   * #30: colour helpers round() instead of int() so a fully-saturated channel
#     reports 100, not 99.
#   * TEST SEAMS: runConcurrentThread's body extracted to _drain_queue with
#     per-message + liveness exception isolation (#23); +26 tests covering the
#     above plus the dispatch table (#8) and deviceStartComm config guards (#24).
#     Suite 448 -> 474. Bundled IndigoSecrets_example.py trimmed to the MQTT keys
#     this plugin actually uses (generic example IP).
# v1.9.19 (26-06-2026): deep-review batch 2 — medium correctness/robustness + polish.
#   * FIX (concurrency): MQTT teardown+rebuild is now atomic under one lock
#     (_rebuild_mqtt). The liveness watchdog and a concurrent config save can no
#     longer interleave a bare stop-then-start into leaking a second live paho
#     client that double-delivers every message.
#   * FIX (robustness): the catch-all z2mSensor handler tracks motion keys in the
#     per-device last-known store (like the occupancy handler) — a partial payload
#     no longer clears a still-present person on a mixed PIR+mmWave sensor.
#   * FIX (correctness): z2mButton lastAction enum expanded to the common
#     multi-function-remote vocabulary, and _normalise_action maps any unmapped
#     token to a declared "other" — actions that previously matched no Option (and
#     so vanished from the display + sub-states) now always surface.
#   * FIX (low): the device CREATE path now uses _compute_light_native_flags too,
#     so a CT-only bulb gets SupportsColor=True at creation (prereq for
#     SupportsWhiteTemperature) instead of only after a manual Refresh Capabilities
#     — v1.9.3 had fixed only the refresh path.
#   * POLISH: Refresh Device State action offered on every stateful device type
#     (was lights/relays/generic-sensor/covers only); dead has_voltage/has_current
#     relay gate entries removed; secrets-template Octopus annotation corrected.
#   * TEST: +20 (watchdog, paho ingress, connect/disconnect routes, atomic rebuild,
#     catch-all motion store, lastAction fallback, hs/port robustness) and the
#     light_ct zoo row now locks in the create-time SupportsColor fix. Suite 428 -> 448.
# v1.9.18 (26-06-2026): deep-review batch 1 — runtime reclassify guard + robustness.
#   * FIX (HIGH, data-loss): _should_reclassify_as_button now mirrors the v1.9.17
#     detection gate — a device exposing presence/occupancy is NEVER reclassified
#     as a button. An Aqara FP1 (RTCZCGQ11LM) emitting region `action` events was
#     being DELETED and recreated as a z2mButton at runtime (new id, every
#     trigger/link/control-page reference orphaned, presence states lost). The
#     detection fix alone never covered the runtime auto-reclassify path.
#   * FIX: _reclassify_as_button now also clears + repoints ieee_map (it was left
#     pointing at the deleted device id, breaking rename detection).
#   * ROBUSTNESS: wake_up resets last_rx_ts (watchdog no longer tears down the
#     just-reconnected client on Mac wake); _mqtt_liveness_check moved inside the
#     runConcurrentThread guard (a rebuild error can't kill the consumer thread);
#     _hs_to_rgb clamps hue/saturation (no negative RGB on a malformed payload);
#     _effective_port coerces a string MQTT_PORT from IndigoSecrets.
#   * TEST: +2 regression tests (presence/occupancy sensor with action must not
#     reclassify). Suite 426 -> 428.
# v1.9.17 (13-06-2026): device-type detection fix + device-zoo test layer.
#   * FIX: a device exposing BOTH `presence`/`occupancy` AND an `action` enum is
#     now classified as an occupancy sensor, not a button. The `action` enum on a
#     presence sensor carries region/presence events (enter/leave/occupied), not
#     scene-controller presses. Without the gate the Aqara FP1 (RTCZCGQ11LM) was
#     mis-detected as a z2mButton on Discover & Create — losing its presence
#     semantics. Real buttons (action, no presence/occupancy) are unaffected.
#     Found by the new device zoo running CliveS's real broker payloads.
#   * TEST: added tests/zoo_manifest.py + tests/test_zoo.py — a declarative
#     "device zoo" mapping each exposes payload to the full translation it must
#     yield (device type + capability props), parametrised, plus cross-cutting
#     invariants (pure-contact-never-motion, presence-never-button, battery never
#     dropped, colour-lesson Supports* set). Real captures live in tests/zoo_real/.
# v1.9.16 (10-06-2026): repo-audit hygiene release (no behaviour change for users).
#   * DEPENDENCY: colormath==3.0.0 removed from requirements.txt — unmaintained
#     since 2018 (SyntaxWarnings on Python 3.13) and pulled numpy (~40 MB) onto
#     every user install, all for one XY→RGB conversion. _xy_to_rgb is now pure
#     Python: same Wide-RGB-D65 matrix the fallback always used, plus
#     chromaticity-preserving peak scaling and the standard sRGB gamma encode so
#     reported colours stay close to what colormath produced. Install is now
#     paho-mqtt only.
#   * DISCIPLINE: _on_mqtt_connect called log() (an indigo.server.log) from the
#     paho thread, contradicting the section's own "queue only, no Indigo calls"
#     rule. The subscribed-topics list now rides the __connected__ queue message
#     and is logged on the main thread.
#   * ROBUSTNESS: bridge/devices and bridge/info payloads of an unexpected JSON
#     type were silently discarded; both now log a WARNING naming the type and
#     prefix so a misbehaving Z2M build is visible instead of just "no devices".
#   * NEW guard-rails: GitHub Actions CI runs the full pytest suite + ruff
#     (errors-only) on every push/PR; ruff.toml added; 4 lint errors fixed.
#
# v2.0.1 (21-07-2026): LOG-LEVEL FIX. indigo.server.log(level=...) wants a Python
# logging INT — a STRING is silently ignored and the line logs as plain Info.
# The log() helper passed its level name straight through, so every WARNING and
# ERROR raised through it had been appearing as an ordinary Info line. Added
# _lvl() to map the name to a real level. Estate-wide sweep (38 files).
#
# v1.9.15 (06-06-2026): deep-review fixes.
#   * HIGH: universal-action handler was named actionControlUniversalDevices — Indigo's
#     callback is actionControlUniversal (confirmed vs all SDK examples), so it was dead
#     code (everyday Send Status Request still worked via the class-specific handlers).
#     Renamed. (Global CLAUDE.md dispatch table corrected — it had the wrong name.)
#   * HIGH (script): startup_z2m_check.py Pushover used executeAction("sendMessage",
#     {title,message}) — wrong id + keys, so the watchdog's restart-failed alert never
#     sent. Fixed to "send" / msgTitle / msgBody / msgPriority / msgSound.
#   * MEDIUM (data-loss): _process_device_state reclassified ANY non-button device that
#     received an 'action' into a button — deleting + recreating it, destroying a real
#     dimmer/cover/switch-with-scenes and orphaning every trigger/link. New
#     _should_reclassify_as_button re-checks the device's CURRENT exposes and only
#     converts when there is no brightness/position/writable-state/light-cover-switch.
#   * MEDIUM: unguarded int()/float() in _process_light_state and the relay/cover
#     linkquality coercions dropped the WHOLE update batch on one malformed field; each
#     numeric block is now try/except-guarded (mirrors the contact/relay power handlers).
#
# v1.9.13 (28-05-2026): Dynamic state-type inference for captured z2m payload
# fields. Each dynamic key is tagged with a type token (bool/onoff/int/real/str)
# persisted in the new dynamicKeyTypes pluginProp, so getDeviceStateList declares
# it with the correct Indigo state type (BoolTrueFalse / BoolOnOff / Integer /
# Real / String) instead of declaring everything as String. The type is inferred
# when the raw value is in hand (in _capture_raw_fields) — getDeviceStateList
# runs at declaration time when dev.states is still None, so it reads the
# persisted token map rather than the (absent) value. Type drift (int then
# float) widens to Real; genuine disagreement falls back to String. Existing
# String states migrate to their proper type on the next payload that includes
# them. dynamicKeyTypes is excluded from didDeviceCommPropertyChange (cosmetic
# healing write, must not cycle comm). Reconciled from the stash that was parked
# alongside the v1.9.12 enum work so the two coexist cleanly.
#
# v1.9.12 (28-05-2026): z2mButton lastAction migrated from a plain String
# state to a List enumeration. Indigo now auto-generates per-value boolean
# sub-states (lastAction.single, lastAction.double, lastAction.hold, ...) so
# users can trigger on a specific action straight from the Triggers UI rather
# than writing an `if action == "double"` string compare. The raw z2m action
# is normalised before writing (the leading "<n>_" button-index prefix — kept
# separately in lastButton — is stripped and remaining underscore tokens are
# camelCased) so the value is a legal enum sub-state suffix: "1_single" ->
# "single", "brightness_move_up" -> "brightnessMoveUp". Existing button devices
# get a one-time stateListOrDisplayStateIdChanged() refresh in deviceStartComm.
#
# v1.9.14 (29-05-2026): Added an application-level MQTT liveness backstop. paho's
# loop_start auto-reconnect can wedge on a half-open socket after a network blip
# WITHOUT firing on_disconnect — leaving the client "connected" but deaf (this is
# what left Jane Lamp dead on 29-05-2026: "sent" published into a dead socket, zero
# inbound, lastSuccessfulComm frozen). runConcurrentThread now stamps last_rx_ts on
# every inbound message and rebuilds the client (_stop_mqtt + _start_mqtt) if nothing
# has arrived for MQTT_SILENCE_LIMIT (300s), independent of paho's own loop. Pairs
# with the estate-wide Device Health Monitor watchdog as defence-in-depth.
#
# v1.9.11 (27-05-2026): Added prepare_to_sleep / wake_up overrides
# harvested from the 27-May plugin_base.py sweep. Mac sleep used to leave
# Mosquitto holding our previous session as a stale ghost client until
# paho's keepalive fired (60s); on wake the bridge would just sit there
# until the Mac re-noticed the broker. Now MQTT disconnects cleanly on
# sleep, reconnects on wake.
#
# v1.9.9 (25-05-2026): Bug fix surfaced by new pytest suite —
# _reclassify_as_button used `self._ensure_device_folder()` with no
# argument, but the method requires `name`. Every reclassify of a
# device sitting at the root level (folderId=0) crashed with
# TypeError, leaving the device deleted but not recreated. Now passes
# DEVICE_FOLDER_NAME to match the other three call sites.
# Adds a ~226-test pytest suite under tests/ (no Indigo runtime needed)
# covering pure helpers, device-type detection, capability flags, state
# sanitiser, action dispatch (Dimmer/Sensor/Universal), state processing
# for every device class, MQTT topic routing, and bug-regression tests.
#
# v1.9.8 (25-05-2026): Added actionControlSensor() — sensor-class devices
# (z2mSensor, z2mContactSensor, z2mOccupancySensor, z2mWaterLeakSensor,
# z2mTemperatureSensor, z2mButton) had no handler, so any "Send Status
# Request" action against them logged
#   "plugin does not define method actionControlSensor"
# in the event log. New method handles indigo.kSensorAction.RequestStatus
# by re-publishing the z2m /get topic; all other sensor actions log a
# WARNING (sensors are read-only — no commands flow back to the network).
#
# v1.9.7 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. Module-level log() helper bumped to ms.
# New "Toggle Timestamps in Log" menu item.
#
# v1.9.5 (22-05-2026):
# - Refactor from code-review pass (no behaviour change):
#   * Extracted `_compute_light_native_flags(has_color, has_color_temp)`
#     @staticmethod — single source of truth for SupportsColor / SupportsRGB /
#     SupportsWhite / SupportsWhiteTemperature. Both _apply_light_capabilities
#     (deviceStartComm path) and refresh_device_capabilities (menu path) now
#     call this helper, eliminating the flip-flop risk noted in v1.9.3.
#   * Unified the two diff-detection loops in refresh_device_capabilities
#     into a single pass over a merged `target` dict.
#   * Moved `_build_capabilities_display` call inside the `if diffs:` guard —
#     skips ~50 string-format calls per menu invocation on no-op refreshes.
#   * Pruned the 14-line contradictory comment above the displayStateId guard
#     in deviceStartComm; investigation history stays in the v1.9.4 changelog.
#
# v1.9.4 (22-05-2026):
# - deviceStartComm now logs a WARNING when an existing device's cached
#   displayStateId disagrees with the current Devices.xml <UiDisplayStateId>.
#   For z2mButton (lastAction) and z2mTemperatureSensor (temperature) the XML
#   value was updated in v1.8.0, but Indigo caches displayStateId on the
#   device record at create time — it is a read-only attribute on existing
#   devices and stateListOrDisplayStateIdChanged() does NOT update it.
#   Confirmed: assignment raises "the attribute \"displayStateId\" is read-only
#   on this instance". The only fix for an existing device is delete +
#   recreate via Plugins -> Discover & Create Devices. The new
#   _EXPECTED_DISPLAY_STATE map drives the per-device check and a clear
#   user-facing warning that names the affected devices.
#
# v1.9.3 (22-05-2026):
# - "Refresh Device Capabilities" now sets SupportsColor / SupportsRGB /
#   SupportsWhite / SupportsWhiteTemperature on z2mLight using the SAME formula
#   as _apply_light_capabilities (SupportsColor = has_color OR has_color_temp,
#   because CT-only bulbs need it as the prereq for SupportsWhiteTemperature).
#   v1.9.2 used create-time logic (SupportsColor = has_color alone) and so
#   downgraded CT-only Hue White Ambiance bulbs on first refresh; the
#   subsequent deviceStartComm would then re-set them, causing a flip-flop.
#
# v1.9.2 (22-05-2026):
# - New menu item "Refresh Device Capabilities" — walks every existing Z2M
#   Indigo device, looks it up in self.bridge_devices by ieee_address (then
#   friendly_name as fallback), re-runs the per-type _detect_*_capabilities()
#   against the live exposes, and merges any has_* / capabilities_display
#   changes via replacePluginPropsOnServer. Then re-applies _apply_indigo_subtype
#   so the catch-all z2mSensor subType backfill runs after the flags update.
#   Logs per-device diffs. Idempotent. Fixes devices created before Z2M had
#   emitted a full exposes definition (e.g. Aqara FP1 presence sensors, contact
#   sensors with empty has_* flags but real state values).
#
# v1.9.1 (22-05-2026):
# - z2mSensor catch-all now gets a backfilled Indigo subType. Devices created
#   before the v1.8.0 specific sensor types existed (z2mContactSensor /
#   z2mOccupancySensor / z2mTemperatureSensor) stayed on z2mSensor and so got
#   no subType — meaning HomeKitLink-Siri, control pages and Indigo's UI all
#   treated them as generic. _apply_indigo_subtype() now infers the correct
#   subType from the device's stored capability flags (has_contact / has_occupancy
#   / has_temperature etc.): pure-contact → DoorWindow, pure-occupancy → Motion,
#   pure-environmental → Temperature. Mixed-capability sensors stay unset
#   (they ARE genuinely generic). Device IDs are preserved — no triggers or
#   control pages break, unlike a delete-and-recreate migration.
#
# v1.9.0 (22-05-2026):
# - New z2mCoordinator custom device representing the Z2M bridge itself
#   (one per MQTT prefix — supports multi-bridge setups like CliveS's
#   zigbee2mqtt + zigbee2mqtt_garage). States: status, version, coordinator,
#   permitJoin, permitJoinEnd, networkChannel, panId, extendedPanId,
#   deviceCount, restartRequired, logLevel, lastUpdate. Populated from
#   prefix/bridge/state and prefix/bridge/info MQTT topics. deviceCount is
#   kept fresh from the existing bridge/devices cache.
# - New menu item "Create Coordinator Devices" — auto-creates one device
#   per configured prefix (primary + garage). Idempotent.
# - _on_mqtt_message now passes bare-string payloads through (older Z2M
#   bridge/state publishes "online" without JSON quotes) instead of dropping.
#
# v1.8.0 (22-05-2026):
# - Indigo device subType applied to every device type (was 0 — confirmed gap
#   vs autolog Zigbee2mqtt Bridge).  Lights, relays, contacts, occupancy,
#   temperature sensors and covers now get the right SDK subType so
#   HomeKitLink-Siri, control pages and Indigo's UI render the right icon /
#   accessory kind.  Set statically in Devices.xml + dynamically in
#   _apply_indigo_subtype() (z2mLight → ColorDimmer vs Dimmer based on
#   has_color; also backfills devices created before 1.8.0).
# - UiDisplayStateId added to z2mTemperatureSensor (temperature) and z2mButton
#   (lastAction) so the device list shows the actually-useful state.
# - exception_handler() helper added — logs traceback PLUS the failing source
#   line and function name extracted from the deepest traceback frame.  Wired
#   into the high-traffic raw-field capture path and availability handler so
#   per-device failures finally name themselves.  Pattern lifted from autolog.
#
# v1.7.2 (13-05-2026):
# - Secrets import split into per-key try/except blocks. Previous single-line
#   `from IndigoSecrets import MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD`
#   would fail entirely if any one key was missing, blanking all four. Now
#   each key falls back independently per CLAUDE.md secrets policy.
#
# v1.7 (10-05-2026):
# - Show only the entities each device actually supports.  Pre-init of default
#   states is now filtered by the device's `has_*` capability flags instead of
#   blindly seeding every state from Devices.xml.  Per the Indigo state-visibility
#   rule (memory: feedback_indigo_state_visibility.md), states that are never
#   written do not appear in the Custom States panel — so unused states are now
#   hidden automatically.
# - Capture ALL Z2M data: any MQTT payload field not handled by the type-
#   specific dispatcher is now imported as a dynamic Indigo state.  First time a
#   field is seen for a device, the state list is refreshed via
#   stateListOrDisplayStateIdChanged() and the device's seen-fields union is
#   persisted in pluginProps so they survive restarts.  getDeviceStateList() is
#   overridden to advertise the dynamic states to Indigo's state machinery.
# - Reserved-state guard: dynamic state names are mangled to avoid colliding
#   with native or reserved Indigo state IDs (batteryLevel, brightnessLevel etc).

import colorsys
import json
import os as _os
import queue
import sys as _sys
import threading
import time
from datetime import datetime

# ── Startup banner + secrets ─────────────────────────────────────────────────
_sys.path.insert(0, _os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
# Per-key try/except so a single missing key doesn't blank all four
# (per CLAUDE.md secrets policy).
try:
    from IndigoSecrets import MQTT_BROKER
except ImportError:
    MQTT_BROKER = ""
try:
    from IndigoSecrets import MQTT_PORT
except ImportError:
    MQTT_PORT = 1883
try:
    from IndigoSecrets import MQTT_USERNAME
except ImportError:
    MQTT_USERNAME = ""
try:
    from IndigoSecrets import MQTT_PASSWORD
except ImportError:
    MQTT_PASSWORD = ""

import indigo  # noqa: E402  (Indigo injects this at runtime)

# ── paho-mqtt (installed by Indigo from requirements.txt) ────────────────────
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# colormath was dropped in v1.9.16 — it was unmaintained (last release 2018,
# SyntaxWarnings on Python 3.13) and pulled numpy (~40 MB) onto every install,
# all for one XY→RGB conversion that _xy_to_rgb now does in pure Python with
# the standard sRGB matrix + gamma encode.

# ── Constants ─────────────────────────────────────────────────────────────────
PLUGIN_ID      = "com.clives.indigoplugin.z2mbridge"
PLUGIN_NAME    = "Zigbee2MQTT Bridge"
# Plugin version is read dynamically from Info.plist via self.pluginVersion;
# do NOT hardcode here — Info.plist is the single source of truth.

RECONNECT_DELAY      = 30   # seconds between MQTT reconnect attempts
# Application-level liveness backstop (paho's own auto-reconnect can wedge silently):
MQTT_SILENCE_LIMIT   = 300  # no inbound MQTT message for this long => rebuild the client
MQTT_WATCHDOG_EVERY  = 30   # seconds between liveness checks in runConcurrentThread
STATE_REQUEST_DELAY  = 2    # seconds after deviceStartComm before requesting state
DEVICE_FOLDER_NAME   = "Zigbee2MQTT"

# Declared lastAction enum Option values (must stay in sync with the z2mButton
# <State id="lastAction"> <List> in Devices.xml). _normalise_action maps any token
# NOT in this set to "other", so a multi-function remote's action always lands on a
# real Option (and fires its auto-generated lastAction.<value> bool sub-state)
# instead of writing a token the enum can't display — which silently vanished.
_BUTTON_ACTION_VALUES = frozenset({
    "single", "double", "triple", "quadruple", "hold", "release", "press",
    "on", "off", "toggle",
    "brightnessMoveUp", "brightnessMoveDown", "brightnessStop",
    "brightnessStepUp", "brightnessStepDown",
    "arrowLeftClick", "arrowRightClick", "arrowLeftHold", "arrowRightHold",
    "arrowLeftRelease", "arrowRightRelease",
    "colorTemperatureMoveUp", "colorTemperatureMoveDown",
    "moveUp", "moveDown", "upPress", "downPress", "upHold", "downHold",
    "other",
})

# MQTT payload keys consumed for EVERY device type (mesh/meta fields that either
# every handler writes semantically, or the plugin deliberately swallows).
# last_seen left this set in v1.10.0 — _capture_raw_fields transforms it into a
# human-readable `lastSeen` dynamic String state instead of swallowing it.
_ALWAYS_CONSUMED_KEYS = {
    "linkquality",                    # written as linkQuality by every handler
    "update_available", "update",     # OTA meta — deliberately not states
    "click",                          # legacy reclassification trigger only
}

# Payload keys each device type's _process_*_state handler ACTUALLY writes as
# named states. _capture_raw_fields skips these (plus _ALWAYS_CONSUMED_KEYS) for
# the device's own type and imports everything else as a typed dynamic state.
#
# v1.9.21: this replaces the old single global _HANDLED_PAYLOAD_KEYS set, which
# claimed keys NO handler wrote (smoke/vibration/tamper/voltage/current/
# battery_low) and claimed keys globally that only SOME types handle — so a
# smoke alarm, a contact sensor's temperature or a metering bulb's power was
# neither semantically handled NOR dynamically captured: silent total data loss.
_HANDLED_KEYS_BY_TYPE = {
    "z2mLight":             {"state", "brightness", "color_temp", "color_mode", "color"},
    "z2mRelay":             {"state", "power", "energy"},
    "z2mCover":             {"state", "position", "tilt"},
    "z2mButton":            {"action", "battery"},
    "z2mRepeater":          set(),
    "z2mContactSensor":     {"contact", "battery"},
    "z2mOccupancySensor":   {"motion", "occupancy", "presence", "pir", "illuminance",
                             "illuminance_lux", "temperature", "humidity", "battery"},
    "z2mWaterLeakSensor":   {"water_leak", "temperature", "battery"},
    "z2mTemperatureSensor": {"temperature", "humidity", "pressure", "illuminance",
                             "illuminance_lux", "battery"},
    "z2mSensor":            {"smoke", "water_leak", "motion", "occupancy", "presence",
                             "pir", "contact", "temperature", "humidity", "pressure",
                             "illuminance", "illuminance_lux", "battery"},
    "z2mLock":              {"state", "lock_state", "battery"},
    "z2mThermostat":        {"local_temperature", "current_heating_setpoint",
                             "occupied_heating_setpoint", "system_mode",
                             "running_state", "position", "battery"},
}

# Conservative fallback for any type not in the table (e.g. future types):
# the union of everything any handler writes — matches the old global set's
# behaviour minus the never-written keys.
_HANDLED_KEYS_FALLBACK = set().union(*_HANDLED_KEYS_BY_TYPE.values())


def _handled_keys_for(device_type_id):
    """Keys _capture_raw_fields must NOT import for this device type."""
    return _ALWAYS_CONSUMED_KEYS | _HANDLED_KEYS_BY_TYPE.get(
        device_type_id, _HANDLED_KEYS_FALLBACK)

# Indigo-reserved state names to avoid as dynamic state IDs (silently shadow
# native device properties — see global CLAUDE.md and feedback_indigo_state_visibility).
_RESERVED_STATE_NAMES = {
    "batteryLevel", "brightnessLevel", "onOffState", "sensorValue",
    "whiteTemperature", "redLevel", "greenLevel", "blueLevel",
    "coolerIsOn", "heaterIsOn", "hvacOperationMode", "temperatureInput1",
    "setpointHeat", "setpointCool",
}


# ── Pure helper functions (no Indigo dependency) ─────────────────────────────

import logging


_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=_lvl(level))


def _xy_to_rgb(x, y):
    """Convert CIE 1931 xy chromaticity to sRGB 0-100 integers.

    Pure-Python since v1.9.16 (colormath dropped): Wide-RGB-D65 matrix (the one
    Philips publish for Hue-class bulbs), negatives clamped, scaled so the
    dominant channel saturates (chromaticity-preserving — xy carries no
    brightness), then sRGB gamma-encoded to match what colormath used to report.
    """
    z = 1.0 - x - y
    Y = 1.0
    X = (Y / y) * x if y > 0 else 0
    Z = (Y / y) * z if y > 0 else 0
    r =  X * 1.656492 - Y * 0.354851 - Z * 0.255038
    g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
    b =  X * 0.051713 - Y * 0.121364 + Z * 1.011530
    r, g, b = (max(0.0, c) for c in (r, g, b))
    peak = max(r, g, b)
    if peak > 1.0:
        r, g, b = r / peak, g / peak, b / peak

    def _gamma(c):
        return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055

    r, g, b = (max(0.0, min(1.0, _gamma(c))) for c in (r, g, b))
    # round() not int() so a fully-saturated channel (0.999 after gamma) reports
    # 100 rather than truncating to 99; clamped for safety.
    return (min(100, round(r * 100)), min(100, round(g * 100)), min(100, round(b * 100)))


def _hs_to_rgb(hue_360, saturation_100):
    """Convert zigbee2mqtt hue (0-360) + saturation (0-100) to sRGB 0-100.

    v1.9.22: saturation divides by 100, not 255 — zigbee2mqtt publishes
    color_hs saturation on a 0-100 scale (herdsman-converters maps the ZCL
    0-254 range to 0-100 at publish time). The old /255 capped Indigo's
    reported saturation at ~39% of actual.

    Hue is wrapped and saturation clamped so a malformed payload (out-of-range
    hue/saturation) can't push colorsys into returning out-of-range channels and
    hence negative or >100 RGB. Mirrors the clamping the xy path already does.
    """
    h = (hue_360 % 360.0) / 360.0
    s = max(0.0, min(1.0, saturation_100 / 100.0))
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    # round() not int() so a fully-saturated channel reports 100 not 99.
    return (max(0, min(100, round(r * 100))),
            max(0, min(100, round(g * 100))),
            max(0, min(100, round(b * 100))))


def _brightness_255_to_100(val):
    """Convert MQTT brightness 0-255 to Indigo 0-100.

    round() not int() (v1.9.23): truncation made the readback one lower than
    the level just set (50% -> 127 -> 49). The old `>= 99 -> 100` fudge existed
    to make z2m's writable max (254) read as full — rounding does that
    naturally (254 -> 99.6 -> 100), so it's just a clamp now."""
    return min(100, round(val / 255 * 100))


def _brightness_100_to_255(val):
    """Convert Indigo 0-100 to MQTT brightness 0-255 (range 1-254)."""
    return max(1, min(254, int(val * 2.55)))


def _kelvin_to_mireds(kelvin):
    """Convert Kelvin to mireds (zigbee2mqtt color_temp)."""
    return round(1_000_000 / max(1, kelvin))


def _mireds_to_kelvin(mireds):
    """Convert mireds to Kelvin."""
    return round(1_000_000 / max(1, mireds))


def _format_last_seen(raw):
    """Format z2m's last_seen (ms-epoch int OR ISO-8601 string, depending on
    the bridge's last_seen config) as a local 'YYYY-MM-DD HH:MM:SS' string.
    Returns None when unparseable."""
    try:
        if isinstance(raw, (int, float)) and raw > 0:
            return datetime.fromtimestamp(raw / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(raw, str) and raw:
            iso = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _payload_bool(val):
    """Coerce a z2m binary payload value to bool, or None if unrecognisable.

    JSON true/false arrive as Python bools, but some devices publish string
    tokens — and raw bool() reads "false"/"OFF"/"0" as True. Numbers follow
    truthiness (0 -> False). Unrecognised strings return None so the caller
    can skip the write rather than guess.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        token = val.strip().lower()
        if token in ("true", "on", "yes", "1"):
            return True
        if token in ("false", "off", "no", "0", ""):
            return False
    return None


def _iter_features(exposes):
    """
    Yield (entry, is_top_level) for every item in exposes, plus recursively
    yield all nested features from any composite entries.
    """
    for entry in exposes:
        if not isinstance(entry, dict):
            continue    # malformed exposes entry — skip, don't abort the caller
        yield entry
        sub = entry.get("features", [])
        if sub:
            yield from _iter_features(sub)


def _detect_device_type(exposes, model=""):
    """
    Determine the best Indigo device type for a zigbee2mqtt device from its
    exposes list.  Priority: Repeater > Light > Cover > Relay > Sensor (default).

    Returns one of: "z2mLight", "z2mRelay", "z2mContactSensor", "z2mOccupancySensor",
                    "z2mWaterLeakSensor", "z2mTemperatureSensor", "z2mSensor",
                    "z2mCover", "z2mRepeater"
    """
    # Repeater: model name contains "repeater", or is a known coordinator/repeater
    # model that exposes a writable state (e.g. SMLIGHT SLZB series).
    _KNOWN_REPEATER_MODELS = {
        "ts0207_repeater",  # Tuya USB repeater
        "slzb-06p7",        # SMLIGHT Zigbee coordinator in repeater mode
        "slzb-06",          # SMLIGHT SLZB-06 coordinator/repeater
        "slzb-07",          # SMLIGHT SLZB-07
    }
    model_lower = model.lower() if model else ""
    if "repeater" in model_lower or model_lower in _KNOWN_REPEATER_MODELS:
        return "z2mRepeater"
    if exposes:
        feature_names = {feat.get("name") for feat in _iter_features(exposes)}
        if feature_names <= {"linkquality", "link_quality"} or not feature_names:
            return "z2mRepeater"

    if not exposes:
        return "z2mSensor"

    # Drop malformed (non-dict) entries once, so the direct top-level loops
    # below can't crash on a junk element (v1.9.22 — _iter_features already
    # skips them, but `for entry in exposes` does not).
    exposes = [e for e in exposes if isinstance(e, dict)]
    if not exposes:
        return "z2mSensor"

    # Check for Light (composite type "light" OR nested "brightness" feature)
    for entry in exposes:
        if entry.get("type") == "light":
            return "z2mLight"
    # Also detect lights that expose "brightness" at any nesting level
    for feat in _iter_features(exposes):
        if feat.get("name") == "brightness" and feat.get("type") == "numeric":
            return "z2mLight"

    # Check for Thermostat/TRV (composite type "climate") — v1.10.0. Checked
    # BEFORE cover so a TRV's valve-position leaf can never reach the cover
    # rule, and before lock/button/relay so climate always wins.
    for entry in exposes:
        if entry.get("type") == "climate":
            return "z2mThermostat"

    # Check for Lock (composite type "lock") — v1.10.0. Before the button and
    # relay checks: a lock's writable binary state (LOCK/UNLOCK) would
    # otherwise classify as z2mRelay and be sent ON/OFF.
    for entry in exposes:
        if entry.get("type") == "lock":
            return "z2mLock"

    # Check for Cover (composite type "cover", or a WRITABLE flat "position"
    # feature outside a climate composite). The writability + no-climate gates
    # (v1.9.21) stop TRVs being created as blinds: Tuya/Moes TRVs expose a
    # read-only valve-position percentage, and treating that as a cover sends
    # OPEN/CLOSE commands at a radiator valve. A genuine flat-expose cover's
    # position is writable (access bit 1).
    for entry in exposes:
        if entry.get("type") == "cover":
            return "z2mCover"
    if not any(entry.get("type") == "climate" for entry in exposes):
        for feat in _iter_features(exposes):
            if feat.get("name") == "position" and (feat.get("access", 0) & 2):
                return "z2mCover"

    # Check for Button/Scene controller (has "action" enum feature — TuYa TS0042, Ikea remotes etc.)
    # TWO gates before we accept the button classification:
    # 1. Not when the device reports presence/occupancy/motion/pir: on such
    #    sensors the `action` enum carries region/presence events (enter/leave/
    #    occupied), not scene-controller presses — the sensor is the primary
    #    type. Without this the Aqara FP1 (RTCZCGQ11LM: presence + action) was
    #    mis-classified as a button and lost its presence semantics (v1.9.17).
    # 2. Not when the device has an output capability (switch composite or
    #    writable binary state): a decoupled-mode wall switch or scene-capable
    #    relay must be created as z2mRelay or its load can never be switched
    #    from Indigo (v1.9.21 — mirrors _should_reclassify_as_button, which
    #    already refused to CONVERT such a device but couldn't undo a wrong
    #    creation). Its scene presses surface via the dynamic `action` state.
    _btn_names = {feat.get("name") for feat in _iter_features(exposes)}
    if not (_btn_names & {"presence", "occupancy", "motion", "pir"}):
        _has_output = any(entry.get("type") == "switch" for entry in exposes) or any(
            feat.get("name") == "state" and feat.get("type") == "binary"
            and (feat.get("access", 0) & 2)
            for feat in _iter_features(exposes)
        )
        if not _has_output:
            for feat in _iter_features(exposes):
                if feat.get("name") == "action" and feat.get("type") == "enum":
                    return "z2mButton"

    # Check for Relay (writable binary "state" feature at top level or inside "switch" composite)
    for entry in exposes:
        if entry.get("type") == "switch":
            # switch composites always contain a writable state feature
            return "z2mRelay"
    for feat in _iter_features(exposes):
        if (feat.get("name") == "state"
                and feat.get("type") == "binary"
                and (feat.get("access", 0) & 2)):  # bit 1 = writable
            return "z2mRelay"

    # Distinguish sensor sub-types before falling back to generic sensor
    feature_names = {feat.get("name") for feat in _iter_features(exposes)}
    has_contact    = "contact"    in feature_names
    has_occupancy  = "occupancy"  in feature_names
    has_presence   = "presence"   in feature_names
    has_water_leak = "water_leak" in feature_names
    has_temp       = "temperature" in feature_names
    has_humidity   = "humidity"    in feature_names
    has_pressure   = "pressure"    in feature_names
    has_illuminance = any(n in feature_names for n in ("illuminance", "illuminance_lux"))

    # Pure contact sensor: has contact, no occupancy/presence/water_leak
    if has_contact and not has_occupancy and not has_presence and not has_water_leak:
        return "z2mContactSensor"

    # Occupancy/presence sensor: has occupancy or presence, no contact
    if (has_occupancy or has_presence) and not has_contact:
        return "z2mOccupancySensor"

    # Water leak sensor: has water_leak, no contact/occupancy
    if has_water_leak and not has_contact and not has_occupancy and not has_presence:
        return "z2mWaterLeakSensor"

    # Environmental sensor: temperature/humidity/pressure/illuminance, no binary alarms
    has_env = has_temp or has_humidity or has_pressure or has_illuminance
    if has_env and not has_contact and not has_occupancy and not has_presence and not has_water_leak:
        return "z2mTemperatureSensor"

    # Default: generic catch-all (mixed capabilities or unknown)
    return "z2mSensor"


def _detect_light_capabilities(exposes):
    """Return dict of capability flags for a z2mLight device."""
    has_color_temp = False
    has_color      = False
    for feat in _iter_features(exposes):
        name = feat.get("name", "")
        if name == "color_temp":
            has_color_temp = True
        elif name in ("color_xy", "color_hs", "color"):
            has_color = True
    return {
        "has_brightness":  True,
        "has_color_temp":  has_color_temp,
        "has_color":       has_color,
    }


def _detect_contact_sensor_capabilities(exposes):
    """Return capability flags for a z2mContactSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery": "battery" in names,
    }


def _detect_occupancy_sensor_capabilities(exposes):
    """Return capability flags for a z2mOccupancySensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":      "battery"      in names,
        "has_pir":          "occupancy"    in names,
        "has_presence":     "presence"     in names,
        "has_illuminance":  any(n in names for n in ("illuminance", "illuminance_lux")),
        "has_temperature":  "temperature"  in names,
        "has_humidity":     "humidity"     in names,
    }


def _detect_water_leak_sensor_capabilities(exposes):
    """Return capability flags for a z2mWaterLeakSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":     "battery"     in names,
        "has_temperature": "temperature" in names,  # some leak sensors also report temp
    }


def _detect_temperature_sensor_capabilities(exposes):
    """Return capability flags for a z2mTemperatureSensor device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_battery":     "battery"     in names,
        "has_temperature": "temperature" in names,
        "has_humidity":    "humidity"    in names,
        "has_pressure":    "pressure"    in names,
        "has_illuminance": any(n in names for n in ("illuminance", "illuminance_lux")),
    }


def _detect_sensor_capabilities(exposes):
    """Return capability flags for a generic z2mSensor device (catch-all)."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_temperature":  "temperature"  in names,
        "has_humidity":     "humidity"     in names,
        "has_contact":      "contact"      in names,
        "has_occupancy":    ("occupancy" in names or "presence" in names or "motion" in names),
        "has_water_leak":   "water_leak"   in names,
        "has_smoke":        "smoke"        in names,
        "has_battery":      "battery"      in names,
        "has_pressure":     "pressure"     in names,
        "has_illuminance":  any(n in names for n in ("illuminance", "illuminance_lux")),
    }


def _detect_relay_capabilities(exposes):
    """Return dict of relay capability flags for a z2mRelay device."""
    names = {feat.get("name") for feat in _iter_features(exposes)}
    return {
        "has_power":  "power"  in names,
        "has_energy": "energy" in names,
    }


def _build_capabilities_display(device_type_id, caps):
    """Build a human-readable capabilities string for the device ConfigUI."""
    parts = []
    if device_type_id == "z2mLight":
        parts.append("on/off")
        if caps.get("has_brightness"):
            parts.append("brightness")
        if caps.get("has_color_temp"):
            parts.append("color temp")
        if caps.get("has_color"):
            parts.append("full color")
    elif device_type_id == "z2mRelay":
        parts.append("on/off")
        if caps.get("has_power"):
            parts.append("power (W)")
        if caps.get("has_energy"):
            parts.append("energy (kWh)")
    elif device_type_id == "z2mContactSensor":
        parts.append("contact (open/closed)")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mOccupancySensor":
        parts.append("occupancy/presence")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mWaterLeakSensor":
        parts.append("water leak")
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_battery"):
            parts.append("battery")
    elif device_type_id == "z2mTemperatureSensor":
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_pressure"):
            parts.append("pressure")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_battery"):
            parts.append("battery")
        if not parts:
            parts.append("environmental sensor")
    elif device_type_id == "z2mSensor":
        if caps.get("has_temperature"):
            parts.append("temperature")
        if caps.get("has_humidity"):
            parts.append("humidity")
        if caps.get("has_contact"):
            parts.append("contact")
        if caps.get("has_occupancy"):
            parts.append("motion/occupancy")
        if caps.get("has_water_leak"):
            parts.append("water leak")
        if caps.get("has_illuminance"):
            parts.append("illuminance")
        if caps.get("has_pressure"):
            parts.append("pressure")
        if caps.get("has_battery"):
            parts.append("battery")
        if not parts:
            parts.append("generic sensor")
    elif device_type_id == "z2mRepeater":
        parts.append("repeater / router")
    elif device_type_id == "z2mCover":
        parts.append("position (0-100)")
        if caps.get("has_tilt"):
            parts.append("tilt")
    elif device_type_id == "z2mButton":
        parts.append("button actions")
        if caps.get("has_battery"):
            parts.append("battery")
    return ", ".join(parts) if parts else device_type_id


# ── Plugin ────────────────────────────────────────────────────────────────────

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.pluginId          = pluginId
        self.pluginDisplayName = pluginDisplayName
        self.pluginVersion     = pluginVersion

        self.timestamp_enabled = bool(pluginPrefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        self.debug = pluginPrefs.get("showDebugInfo", False)

        # MQTT state
        self.mqtt_client    = None
        self.mqtt_connected = False
        self.mqtt_lock      = threading.Lock()

        # Guards the device-lookup maps below (friendly_name_map / ieee_map /
        # coordinator_map). They are mutated by BOTH the Indigo lifecycle thread
        # (deviceStartComm / deviceStopComm) and the MQTT consumer thread
        # (reclassify rebuild + bridge/devices rename), so a comprehension rebuild
        # can otherwise race a concurrent pop into a RuntimeError. RLock so a guarded
        # method may nest. Held ONLY for pure dict ops — never across an indigo.* call.
        self.maps_lock      = threading.RLock()

        # Message queue (paho callback -> main thread via runConcurrentThread)
        self.msg_queue = queue.Queue()

        # MQTT liveness backstop — stamp of last inbound message + last watchdog check.
        self.last_rx_ts       = time.time()
        self._last_mqtt_check = 0.0
        # Outstanding liveness probe: ts of the bridge/request/devices probe the
        # watchdog sent to distinguish a wedged socket from a QUIET network.
        # 0.0 = no probe outstanding.
        self._probe_sent_ts   = 0.0

        # Per-device state-request timers (deviceStartComm's settle delay),
        # tracked so stop/shutdown can cancel them (v1.9.22 — an untracked
        # Timer could fire after its device was deleted or the plugin stopped).
        self._state_request_timers = {}  # type: dict[int, threading.Timer]

        # Plain-string prefix snapshot for the paho-thread on_connect callback
        # (set in _start_mqtt_locked — no indigo.Dict reads off-main-thread).
        self._subscribed_prefixes = ()

        # (dev.id, state_key) pairs whose write already failed once — the first
        # failure logs a WARNING, repeats stay at debug (see _apply_updates).
        self._state_write_warned = set()

        # Once-per-outage connect-failure reporting (v1.10.0): paho retries
        # forever, so unreachable-broker / bad-credential errors are reported
        # once per distinct condition and re-armed by a successful connect.
        self._connect_fail_reported = False
        self._last_connect_fail_msg = None

        # IEEE addresses of the bridges' own coordinator radios (v1.10.0).
        # bridge/devices entries of type Coordinator are deliberately excluded
        # from the device cache, so without this the orphan report flags the
        # coordinator radio's repeater tile as orphaned (live false positive:
        # the SLZB-06P7 house radio).
        self._coordinator_ieees = set()

        # Serialises pluginProps read-modify-write cycles (dict(dev.pluginProps)
        # -> mutate -> replacePluginPropsOnServer) between the MQTT consumer
        # thread (_capture_raw_fields, capability self-heal) and Indigo's
        # menu/UI threads (refresh_device_capabilities). Unlike maps_lock this
        # IS deliberately held across the replace call — that's the whole
        # point: two interleaved RMWs silently drop one side's changes
        # (v1.9.23). Menu ops are rare, so contention is negligible.
        self.props_lock = threading.RLock()

        # bridge/devices cache: ieee_address -> full device dict
        self.bridge_devices = {}     # type: dict[str, dict]

        # Active Indigo devices: (mqtt_prefix, friendly_name) -> indigo device id.
        # Prefix-qualified since v1.9.22: with two bridges (house + garage) a
        # friendly name shared across them used to collide into ONE entry —
        # both physical devices' payloads routed to a single Indigo device and
        # the second could never be auto-created.
        self.friendly_name_map = {}  # type: dict[tuple[str, str], int]

        # Active Indigo devices: ieee_address -> indigo device id
        # Used for O(1) rename detection when Z2M changes a friendly_name
        self.ieee_map = {}  # type: dict[str, int]

        # Tracks which non-primary prefixes have produced at least one MQTT message.
        # Used for diagnostic logging — fires once per prefix per session.
        self._seen_prefixes = set()  # type: set[str]

        # Coordinator devices: mqtt_prefix -> indigo device id (one per Z2M bridge)
        self.coordinator_map = {}  # type: dict[str, int]

        # Latest bridge/info payload per prefix (cached so menu items / refresh can
        # re-populate states without round-tripping MQTT).
        self._bridge_info_cache = {}  # type: dict[str, dict]

        # Latest bridge/state per prefix — cached because the retained MQTT message
        # may arrive before any coordinator device exists.  Replayed on
        # deviceStartComm so the freshly created device picks up online/offline.
        self._bridge_state_cache = {}  # type: dict[str, str]

        # Per-device motion component states for occupancy sensors.
        # Stores last known bool for each motion-related key the device has ever sent
        # (motion, occupancy, presence, pir, ...).  Partial payloads only update the
        # keys they contain, so the OR across all stored values is always correct.
        self._motion_states = {}  # type: dict[int, dict[str, bool]]

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def startup(self):
        log(f"{PLUGIN_NAME} starting up")
        self._start_mqtt()

    def shutdown(self):
        log(f"{PLUGIN_NAME} shutting down")
        for dev_id in list(self._state_request_timers):
            self._cancel_state_request(dev_id)
        self._stop_mqtt()

    # ── Mac sleep / wake — disconnect MQTT cleanly on sleep so Mosquitto
    # ── doesn't hold the previous session as a stale ghost client. On wake
    # ── reconnect; retained messages will reseed device state.
    def prepare_to_sleep(self):
        log("Mac going to sleep — disconnecting from Mosquitto cleanly")
        self._stop_mqtt()
        super().prepare_to_sleep()
    prepareToSleep = prepare_to_sleep

    def wake_up(self):
        log("Mac woke — reconnecting to Mosquitto")
        # Give the fresh connection a full silence window, otherwise the liveness
        # watchdog sees the pre-sleep last_rx_ts (potentially hours old) and tears
        # the just-rebuilt client straight back down on the next check.
        self.last_rx_ts = time.time()
        # MQTT FIRST, then super() (which restarts device comm): the settle-delay
        # /get requests deviceStartComm schedules used to race the reconnect and
        # die on a not-yet-connected client (v1.9.23).
        self._start_mqtt()
        super().wake_up()
    wakeUp = wake_up

    def runConcurrentThread(self):
        """Drain the MQTT message queue on the Indigo main thread."""
        while True:
            self._drain_queue()
            self.sleep(0.2)

    def _drain_queue(self):
        """One consumer pass: process every queued MQTT message, then run the
        liveness check. Each message AND the liveness check are isolated so one
        bad item logs-and-continues instead of killing the only consumer thread
        (which would silently stop all device updates — the failure the watchdog
        exists to prevent). Extracted from runConcurrentThread as a test seam."""
        while not self.msg_queue.empty():
            try:
                topic, payload = self.msg_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._process_message(topic, payload)
            except Exception as e:
                log(f"error processing message {topic!r}: {e}", level="ERROR")
        try:
            self._mqtt_liveness_check()
        except Exception as e:
            log(f"liveness check error: {e}", level="ERROR")

    # NB: no stopConcurrentThread override — the base implementation sets
    # stopThread AND writes the wake pipe so self.sleep() returns instantly.
    # The old `self.stopThread = True` override discarded that pipe-wake and
    # made shutdown wait out the sleep interval (removed v1.9.23).

    # ── Plugin preferences ────────────────────────────────────────────────────

    def validatePrefsConfigUi(self, valuesDict):
        errors = indigo.Dict()
        prefix = valuesDict.get("mqtt_topic_prefix", "").strip()
        if not prefix:
            errors["mqtt_topic_prefix"] = "Topic prefix is required."
        # Numeric fields: catch bad values AT THE DIALOG instead of silently
        # falling back at runtime (v1.9.23).
        port_raw = str(valuesDict.get("mqtt_port", "")).strip()
        if port_raw:
            try:
                port = int(port_raw)
                if not (1 <= port <= 65535):
                    raise ValueError
            except (TypeError, ValueError):
                errors["mqtt_port"] = "Port must be a number between 1 and 65535."
        limit_raw = str(valuesDict.get("mqtt_silence_limit", "")).strip()
        if limit_raw:
            try:
                if int(limit_raw) < 60:
                    raise ValueError
            except (TypeError, ValueError):
                errors["mqtt_silence_limit"] = ("Silence limit must be a number "
                                                "of seconds, 60 or more.")
        return (len(errors) == 0), valuesDict, errors

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.debug = valuesDict.get("showDebugInfo", False)
            log("Preferences saved — reconnecting MQTT")
            # Atomic rebuild under one lock — a config save must not race the
            # liveness watchdog into leaking a second paho client.
            self._rebuild_mqtt()

    # ── Device lifecycle ──────────────────────────────────────────────────────

    def deviceStartComm(self, dev):
        # Coordinator devices have no friendly_name — they're indexed by mqtt_prefix
        if dev.deviceTypeId == "z2mCoordinator":
            prefix = dev.pluginProps.get("mqtt_prefix", "").strip()
            if not prefix:
                log(f"Coordinator '{dev.name}' has no mqtt_prefix — skipping",
                    level="WARNING")
                return
            with self.maps_lock:
                self.coordinator_map[prefix] = dev.id
            self._ensure_device_states(dev)
            # If we already have a cached bridge/info or bridge/state for this
            # prefix (retained MQTT may have arrived before this device existed),
            # push them now so the device populates immediately.
            cached_info = self._bridge_info_cache.get(prefix)
            if cached_info:
                self._process_bridge_info(cached_info, prefix)
            cached_state = self._bridge_state_cache.get(prefix)
            if cached_state:
                self._update_coordinator(prefix, status=cached_state)
            # Backfill deviceCount from current cache
            count = sum(1 for d in self.bridge_devices.values()
                        if d.get("_mqtt_prefix") == prefix)
            if count:
                dev.updateStateOnServer("deviceCount", value=count)
            if self.debug:
                log(f"Started coordinator: {dev.name} (prefix={prefix})")
            return

        props = dev.pluginProps
        fname = props.get("friendly_name", "").strip()
        if not fname:
            log(f"Device '{dev.name}' has no friendly_name — skipping", level="WARNING")
            return

        ieee = props.get("ieee_address", "")
        with self.maps_lock:
            self.friendly_name_map[(self._device_prefix(dev), fname)] = dev.id
            if ieee:
                self.ieee_map[ieee] = dev.id

        # Apply Indigo subType — dynamic for lights (Dimmer vs ColorDimmer);
        # static for everything else.  Also backfills devices created before
        # subType was declared in Devices.xml.
        self._apply_indigo_subtype(dev)

        # Apply stored color/capability flags to Indigo device
        if dev.deviceTypeId == "z2mLight":
            self._apply_light_capabilities(dev)

        # Ensure all custom states exist — guards against states added to Devices.xml
        # after a device was originally created (avoids "state key not defined" errors)
        self._ensure_device_states(dev)

        # displayStateId is cached on the device record at create time and is
        # read-only on existing instances — only fix for a stale value after a
        # <UiDisplayStateId> change in Devices.xml is delete + recreate.
        expected_display = self._EXPECTED_DISPLAY_STATE.get(dev.deviceTypeId)
        if expected_display and dev.displayStateId != expected_display:
            log(f"{dev.name}: displayStateId is {dev.displayStateId!r} but XML "
                f"now declares {expected_display!r} — delete + recreate this "
                f"device to pick up the new primary display state",
                level="WARNING")

        # v1.9.12 one-time migration: lastAction became a List enumeration, so
        # Indigo now auto-generates lastAction.<value> boolean sub-states. A
        # device created before the change keeps its old (String) cached state
        # list until we refresh it. Detect by the absence of a known sub-state:
        # stateListOrDisplayStateIdChanged() surfaces the sub-states and they
        # persist on the device record, so this skips on subsequent starts.
        # (A guard pluginProp is NOT used — replacePluginPropsOnServer during
        # deviceStartComm doesn't reliably persist.)
        if dev.deviceTypeId == "z2mButton" and "lastAction.single" not in dev.states:
            try:
                dev.stateListOrDisplayStateIdChanged()
                log(f"{dev.name}: migrated lastAction to enumeration — per-action "
                    f"sub-states (lastAction.single/.double/.hold/...) now "
                    f"available; the matching one goes true on the next press")
            except Exception as e:
                log(f"{dev.name}: lastAction enum state-list refresh failed: {e}",
                    level="WARNING")

        if self.debug:
            log(f"Started device: {dev.name} (type={dev.deviceTypeId}, name={fname})")

        # Request current state after brief delay (MQTT needs time to settle)
        prefix = self._device_prefix(dev)
        self._schedule_state_request(dev.id, fname, dev.deviceTypeId, prefix,
                                     dev_props=dict(dev.pluginProps))

    def _schedule_state_request(self, dev_id, fname, device_type_id, prefix,
                                dev_props=None):
        """Ask the device for its state after a short settle delay. Timers are
        daemonised and tracked per-device so deviceStopComm/shutdown can cancel
        them — an untracked Timer could fire after the device was deleted or
        the plugin stopped (v1.9.22; also the deviceStartComm test seam).
        dev_props is a plain-dict snapshot for the capability-gated /get —
        the Timer thread must not read live indigo objects."""
        self._cancel_state_request(dev_id)
        t = threading.Timer(STATE_REQUEST_DELAY, self._request_state,
                            args=(fname, device_type_id, prefix, dev_props))
        t.daemon = True
        self._state_request_timers[dev_id] = t
        t.start()

    def _cancel_state_request(self, dev_id):
        t = self._state_request_timers.pop(dev_id, None)
        if t is not None:
            t.cancel()

    # Expected displayStateId per device type — must match <UiDisplayStateId> in
    # Devices.xml.  Used by deviceStartComm to retroactively repair the cached
    # displayStateId on devices created before the XML value was changed.
    _EXPECTED_DISPLAY_STATE = {
        "z2mButton":            "lastAction",
        "z2mTemperatureSensor": "temperature",
    }

    # Default custom states for every device type.
    # Key   = state id as declared in Devices.xml
    # Value = safe initial value (correct Python type for the ValueType)
    # Native states (onOffState, brightnessLevel, sensorValue) are NOT listed —
    # Indigo owns those and they're always present.
    _DEVICE_STATE_DEFAULTS = {
        "z2mLight": [
            ("colorMode",    ""),
            ("colorTemp",    0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mRelay": [
            ("power",        0.0),
            ("energy",       0.0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mContactSensor": [
            ("contact",      False),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mOccupancySensor": [
            ("motion",       False),
            ("occupancy",    False),
            ("presence",     False),
            ("illuminance",  0.0),
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mWaterLeakSensor": [
            ("waterLeak",    False),
            ("temperature",  0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mTemperatureSensor": [
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("pressure",     0.0),
            ("illuminance",  0.0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mCover": [
            ("coverState",   ""),
            ("tiltAngle",    0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mButton": [
            ("lastAction",   ""),
            ("lastButton",   ""),
            ("pressCount",   0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mLock": [
            ("lockState",    ""),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mThermostat": [
            ("runningState", ""),
            ("valvePosition", 0),
            ("battery",      0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mSensor": [
            ("temperature",  0.0),
            ("humidity",     0.0),
            ("contact",      False),
            ("motion",       False),
            ("waterLeak",    False),
            ("smoke",        False),
            ("battery",      0),
            ("pressure",     0.0),
            ("illuminance",  0.0),
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mRepeater": [
            ("availability", ""),
            ("linkQuality",  0),
        ],
        "z2mCoordinator": [
            ("status",          "unknown"),
            ("version",         ""),
            ("coordinator",     ""),
            ("permitJoin",      False),
            ("permitJoinEnd",   ""),
            ("networkChannel",  0),
            ("panId",           0),
            ("extendedPanId",   ""),
            ("deviceCount",     0),
            ("restartRequired", False),
            ("logLevel",        ""),
            ("lastUpdate",      ""),
        ],
    }

    # Map of state-id -> (capability flag(s) that must be true for the state to be
    # pre-initialised).  None means "always init for this device type" (universal
    # states like availability/linkQuality).  Used to filter _DEVICE_STATE_DEFAULTS
    # so unsupported entities don't appear in the Custom States panel.
    _STATE_CAPABILITY_GATE = {
        "z2mLight":            {"colorMode": "has_color", "colorTemp": "has_color_temp"},
        # voltage/current are not detected (_detect_relay_capabilities sets only
        # has_power/has_energy), not declared in Devices.xml, and not written by
        # _process_relay_state — so no gate for them (the old has_voltage/has_current
        # entries were dead).
        "z2mRelay":            {"power": "has_power", "energy": "has_energy"},
        "z2mContactSensor":    {"battery": "has_battery"},
        "z2mCover":            {"tiltAngle": "has_tilt"},
        "z2mButton":           {"battery": "has_battery"},
        "z2mLock":             {"battery": "has_battery"},
        "z2mThermostat":       {"battery": "has_battery"},
        "z2mOccupancySensor":  {"occupancy": "has_pir", "presence": "has_presence",
                                "illuminance": "has_illuminance",
                                "temperature": "has_temperature",
                                "humidity": "has_humidity",
                                "battery": "has_battery"},
        "z2mWaterLeakSensor":  {"battery": "has_battery", "temperature": "has_temperature"},
        "z2mTemperatureSensor": {"temperature": "has_temperature",
                                 "humidity": "has_humidity",
                                 "pressure": "has_pressure",
                                 "illuminance": "has_illuminance",
                                 "battery": "has_battery"},
        "z2mSensor":           {"temperature": "has_temperature",
                                "humidity": "has_humidity",
                                "contact": "has_contact",
                                "motion": "has_occupancy",
                                "waterLeak": "has_water_leak",
                                "smoke": "has_smoke",
                                "pressure": "has_pressure",
                                "illuminance": "has_illuminance",
                                "battery": "has_battery"},
    }

    def _ensure_device_states(self, dev):
        """Initialise the states this device's hardware actually supports.

        Filters _DEVICE_STATE_DEFAULTS by the device's `has_*` capability flags
        (set at create-time from zigbee2mqtt's exposes data) so the Custom States
        panel only shows entities the physical Zigbee device reports.  States with
        no gating in _STATE_CAPABILITY_GATE are universal (availability / linkQuality
        / motion-mirror / etc.) and are always initialised.

        Per Indigo's state-visibility rule (memory: feedback_indigo_state_visibility),
        states that are never written never appear in the panel — so simply NOT
        pre-initialising unsupported states is enough to hide them.
        """
        defaults = self._DEVICE_STATE_DEFAULTS.get(dev.deviceTypeId)
        if not defaults:
            return  # unknown or native-only type — nothing to do

        gates = self._STATE_CAPABILITY_GATE.get(dev.deviceTypeId, {})
        props = dev.ownerProps
        existing = set(dev.states.keys())
        to_write = []
        for key, val in defaults:
            if key in existing:
                # State already exists on the device record.  We DO NOT clear it back
                # to default — preserves any value already received.
                continue
            gate_prop = gates.get(key)
            if gate_prop and not props.get(gate_prop, False):
                continue  # capability not advertised — leave the state hidden
            to_write.append((key, val))

        if not to_write:
            return

        log(f"{dev.name}: initialising {len(to_write)} supported state(s): "
            f"{[k for k, _ in to_write]}")
        for key, val in to_write:
            try:
                dev.updateStateOnServer(key, val)
            except Exception as e:
                log(f"{dev.name}: could not initialise state '{key}': {e}",
                    level="WARNING")

    # ── Dynamic state capture ───────────────────────────────────────────────
    # Any MQTT payload field not listed in _HANDLED_PAYLOAD_KEYS (and not handled
    # by a type-specific dispatcher) is captured as a dynamic Indigo state.  The
    # union of all keys ever seen for a device is persisted in pluginProps as
    # seenDynamicKeys (CSV).  getDeviceStateList() advertises these to Indigo
    # so they appear in the Custom States panel after stateListOrDisplayStateIdChanged.

    @staticmethod
    def _normalise_action(action):
        """Reduce a raw z2m button action to a clean camelCase token for the
        lastAction enumeration state and its auto-generated boolean sub-states.

        Indigo builds enum sub-state IDs as "lastAction.<value>", and a state-id
        segment must be camelCase ASCII — no leading digit, no underscore (see
        the state-id naming rules). Raw z2m actions break that in two ways:
        a leading "<n>_" button-index prefix ("1_single") and underscore-joined
        compound names ("brightness_move_up"). We therefore drop the button
        index (it is captured separately in lastButton) and camelCase whatever
        remains:
            "1_single"            -> "single"
            "single"              -> "single"
            "2_double"            -> "double"
            "brightness_move_up"  -> "brightnessMoveUp"
            "hold"                -> "hold"
        Any token NOT in _BUTTON_ACTION_VALUES (an exotic/device-specific action,
        or one that reduces to nothing usable like a bare "2") returns "other" —
        a DECLARED enum Option, so the action still surfaces (display + the
        lastAction.other bool sub-state fires) instead of writing a value the enum
        can't show, which previously vanished entirely for multi-function remotes.
        """
        parts = [p for p in str(action).split("_") if p != ""]
        if parts and parts[0].isdigit():
            parts = parts[1:]  # drop button-index prefix — kept in lastButton
        if not parts:
            return "other"
        token = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
        token = "".join(c for c in token if c.isascii() and c.isalnum())
        token = token.lstrip("0123456789")
        if not token:
            return "other"
        return token if token in _BUTTON_ACTION_VALUES else "other"

    def _sanitise_state_key(self, key):
        """Convert an MQTT field name into a valid Indigo state ID (camelCase).

        Indigo's XML state-id validator rejects any non-ASCII-alphanumeric
        character including the underscore — even though XML itself allows them
        — with LowLevelBadParameterError 'illegal XML tag name character'.
        We therefore convert snake_case to camelCase (the SDK convention used
        in Devices.xml everywhere) so MQTT names like `color_temp_startup` and
        `power_on_behavior` become `colorTempStartup` and `powerOnBehavior`.
        """
        if not key:
            return ""
        # Split on any non-alnum (underscore, dash, dot, space, etc.) to get parts
        parts = []
        cur = []
        for c in key:
            if c.isascii() and c.isalnum():
                cur.append(c)
            else:
                if cur:
                    parts.append("".join(cur))
                    cur = []
        if cur:
            parts.append("".join(cur))
        if not parts:
            return ""
        # First part lowercase, subsequent parts Capitalised — camelCase
        sk = parts[0][0].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
        # Strip any remaining non-ASCII-alnum (defensive — should be impossible after split)
        sk = "".join(c for c in sk if c.isascii() and c.isalnum())
        # Must start with an ASCII letter
        if not sk or not sk[0].isalpha():
            sk = "z2m" + (sk[:1].upper() + sk[1:] if sk else "")
        # XML reserves names starting with "xml" (case-insensitive)
        if sk[:3].lower() == "xml":
            sk = "z" + sk[0].upper() + sk[1:]
        if sk in _RESERVED_STATE_NAMES:
            sk = "z2m" + sk[0].upper() + sk[1:]
        return sk

    # ── Dynamic state type inference ─────────────────────────────────────────
    # Each captured field is tagged with a type token so getDeviceStateList can
    # declare it with the correct Indigo state type (Integer / Real / BoolOnOff /
    # BoolTrueFalse) instead of String.  Tokens are persisted per-device in the
    # dynamicKeyTypes pluginProp (JSON), because the value itself isn't written
    # until AFTER the state list is refreshed — so at declaration time dev.states
    # holds None and the type can only be known from the recorded token.

    @staticmethod
    def _infer_state_type(raw_val):
        """Map a raw payload value to a state-type token.

        bool           -> "bool"  (BoolTrueFalse)
        "ON" / "OFF"   -> "onoff" (BoolOnOff)
        int            -> "int"   (Integer)
        float          -> "real"  (Real)
        anything else  -> "str"   (String; dicts/lists are JSON-stringified)

        bool is checked before int because bool is a subclass of int.
        """
        if isinstance(raw_val, bool):
            return "bool"
        if isinstance(raw_val, int):
            return "int"
        if isinstance(raw_val, float):
            return "real"
        if isinstance(raw_val, str) and raw_val.strip().upper() in ("ON", "OFF"):
            return "onoff"
        return "str"

    @staticmethod
    def _merge_state_type(old, new):
        """Combine a previously recorded token with a freshly observed one.

        Same token wins.  int/real widen to "real" (a Real state holds whole
        numbers too).  Every other disagreement (bool vs number, onoff vs
        anything, etc.) is type drift — fall back to the most permissive type,
        "str", so no typed write is ever rejected.
        """
        if old == new:
            return new
        if {old, new} == {"int", "real"}:
            return "real"
        return "str"

    @staticmethod
    def _coerce_dynamic_value(raw_val, token):
        """Coerce a raw payload value to match its declared state-type token.

        The write value MUST match the declared type, so we coerce by the
        merged/declared token rather than the per-payload Python type.
        """
        if isinstance(raw_val, (dict, list)):
            try:
                return json.dumps(raw_val, separators=(",", ":"), default=str)[:512]
            except Exception:
                return str(raw_val)[:512]
        if token == "bool":
            return bool(raw_val)
        if token == "onoff":
            return str(raw_val).strip().upper() == "ON"
        if token == "int":
            try:
                return int(raw_val)
            except (TypeError, ValueError):
                return str(raw_val)
        if token == "real":
            try:
                return float(raw_val)
            except (TypeError, ValueError):
                return str(raw_val)
        return str(raw_val)

    def _load_dynamic_types(self, dev):
        """Return the persisted {state_id: type_token} map for a device."""
        raw = dev.pluginProps.get("dynamicKeyTypes", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _state_dict_for_token(self, key, label, token):
        """Build the Indigo state-list entry for a dynamic key, choosing the
        type-specific builder that matches its recorded type token."""
        if token == "bool":
            return self.getDeviceStateDictForBoolTrueFalseType(key, label, label)
        if token == "onoff":
            return self.getDeviceStateDictForBoolOnOffType(key, label, label)
        if token == "int":
            return self.getDeviceStateDictForIntegerType(key, label, label)
        if token == "real":
            return self.getDeviceStateDictForRealType(key, label, label)
        return self.getDeviceStateDictForStringType(key, label, label)

    def _static_state_ids(self, dev):
        """Set of statically-declared (Devices.xml) state IDs for this device type.

        Read from the BASE getDeviceStateList (the parser's static list) — read-only,
        never mutated here. Used by _capture_raw_fields to stop a dynamic payload
        field whose sanitised key collides with a static state from being captured
        and written with a possibly-mismatched dynamic type.
        """
        ids = set()
        try:
            base = indigo.PluginBase.getDeviceStateList(self, dev)
            for s in (base or []):
                k = s.get("Key") if hasattr(s, "get") else s["Key"]
                if k:
                    ids.add(k)
        except Exception:
            pass
        return ids

    def _capture_raw_fields(self, dev, payload):
        """Write every payload field that the type-specific dispatcher did not
        already handle.  First-time keys are added to pluginProps and the device's
        state list is refreshed.

        Each key's type is inferred from its value and persisted in
        dynamicKeyTypes so getDeviceStateList declares it with the correct Indigo
        state type.  bool -> BoolTrueFalse, "ON"/"OFF" -> BoolOnOff, int ->
        Integer, float -> Real, else String.  Complex types (dict, list) are
        JSON-stringified.  None values are skipped.  Type drift across payloads
        (e.g. int then float) is merged toward the most permissive type seen
        (see _merge_state_type); a refresh is triggered whenever a key is new OR
        its type token changes, so an existing String state migrates to its
        proper type on the next payload that includes it.

        State IDs are tightly validated against Indigo's XML element rules; any
        key that fails validation is dropped with a debug log so it never gets
        persisted to seen-set and corrupts subsequent stateListOrDisplay calls.
        """
        if not isinstance(payload, dict):
            return

        # v1.10.0: surface z2m's last_seen as a readable String state instead
        # of swallowing it — replace the raw key (ms epoch / ISO) with the
        # formatted value under the camelCase name the sanitiser would pick.
        if "last_seen" in payload:
            payload = dict(payload)
            formatted = _format_last_seen(payload.pop("last_seen"))
            if formatted:
                payload["lastSeen"] = formatted

        orig_props = dict(dev.pluginProps)
        seen_csv = orig_props.get("seenDynamicKeys", "")
        seen = set(s for s in seen_csv.split(",") if s and self._is_valid_state_id(s))
        type_map = self._load_dynamic_types(dev)
        new_keys = []
        type_changed = False
        # Phase 1: identify keys + values WITHOUT writing.  We must NOT call
        # updateStateOnServer for any state that isn't already declared in our
        # state list — Indigo logs a top-level "state key not defined" error
        # the first time, and we get one error per new key per device per session.
        # Collect them all, then declare in Phase 2, then write in Phase 3.
        pending = []  # list of (state_key, state_val)
        static_ids = None  # statically-declared state IDs (Devices.xml); built lazily

        handled_keys = _handled_keys_for(dev.deviceTypeId)
        for raw_key, raw_val in payload.items():
            if raw_key in handled_keys or raw_key.startswith("_"):
                continue
            if raw_val is None:
                continue
            state_key = self._sanitise_state_key(raw_key)
            if not state_key or not self._is_valid_state_id(state_key):
                if self.debug:
                    log(f"{dev.name}: dropping invalid state-id derived from '{raw_key}' -> '{state_key}'",
                        level="WARNING")
                continue

            # A field whose sanitised key collides with a state declared in
            # Devices.xml (e.g. a snake-case `link_quality` -> static `linkQuality`)
            # must NOT be captured dynamically: getDeviceStateList already skips
            # re-declaring it, and a dynamic-typed write could mismatch the static
            # ValueType. Leave it to the static state / type handler.
            if static_ids is None:
                static_ids = self._static_state_ids(dev)
            if state_key in static_ids:
                if self.debug:
                    log(f"{dev.name}: field '{raw_key}' collides with static state "
                        f"'{state_key}' — skipping dynamic capture", level="WARNING")
                continue

            token = self._infer_state_type(raw_val)
            if state_key not in seen:
                seen.add(state_key)
                new_keys.append(state_key)
                type_map[state_key] = token
            else:
                old_token = type_map.get(state_key)
                if old_token is None:
                    # Migration: key seen before dynamicKeyTypes existed.  Adopt
                    # the first observed type so a legacy String state gets
                    # re-declared with its proper type on this refresh.
                    type_map[state_key] = token
                    type_changed = True
                else:
                    merged = self._merge_state_type(old_token, token)
                    if merged != old_token:
                        type_map[state_key] = merged
                        type_changed = True

            # Coerce by the final/declared token so the write matches the type.
            state_val = self._coerce_dynamic_value(raw_val, type_map[state_key])
            pending.append((state_key, state_val))

        # Prune any dynamicKeyTypes entries whose key is no longer in the validated
        # seen set (e.g. a previously-persisted key that now fails validation) so the
        # two persisted stores stay in lock-step instead of leaving orphan type
        # entries behind. orphan_types also forces a write so an existing drift heals.
        orphan_types = set(type_map) - seen
        for k in orphan_types:
            type_map.pop(k, None)

        # Phase 2: if any key is new OR changed type (OR an orphan was pruned),
        # persist + refresh the state list FIRST so the writes in Phase 3 don't
        # trigger "state key not defined" errors and any retyped state is
        # re-declared before reseeding.
        if new_keys or type_changed or orphan_types:
            try:
                with self.props_lock:   # atomic RMW vs menu-thread refresh
                    new_props = dict(dev.pluginProps)
                    new_props["seenDynamicKeys"] = ",".join(sorted(seen))
                    new_props["dynamicKeyTypes"] = json.dumps(
                        type_map, separators=(",", ":"), sort_keys=True)
                    dev.replacePluginPropsOnServer(new_props)
                refreshed = indigo.devices[dev.id]
                refreshed.stateListOrDisplayStateIdChanged()
                if new_keys:
                    log(f"{dev.name}: imported {len(new_keys)} new field(s): {new_keys}")
                if type_changed:
                    log(f"{dev.name}: refined dynamic state type(s) from payload")
            except Exception as e:
                log(f"{dev.name}: dynamic-state refresh failed; rolling back. err={e}; "
                    f"new_keys={new_keys}", level="ERROR")
                try:
                    dev.replacePluginPropsOnServer(orig_props)
                except Exception:
                    pass
                # Skip Phase 3: writes for the new keys would fail anyway.
                # Old keys' writes are also skipped to keep the message atomic.
                return

        # Phase 3: now safe to write all pending values.
        for state_key, state_val in pending:
            try:
                dev.updateStateOnServer(state_key, state_val)
            except Exception as e:
                if self.debug:
                    log(f"{dev.name}: dynamic state '{state_key}' write failed: {e}", level="WARNING")

    def getDeviceStateList(self, dev):
        """Override Indigo's static state list with the static + dynamic union.

        Static states come from Devices.xml.  Dynamic states are added on the fly
        as the device reports new fields via MQTT.  Every dynamic state ID is
        re-validated here as a defensive measure — even if a corrupted entry
        somehow lands in `seenDynamicKeys`, it cannot poison this list.

        IMPORTANT: indigo.PluginBase.getDeviceStateList returns the LIVE list
        object from the parser's internal devices_type_dict.  Mutating that
        list permanently corrupts subsequent reads (the same dynamic states
        get appended on every call, accumulating duplicates and eventually
        triggering "illegal XML tag name character" in Indigo's XML
        serialiser).  We therefore work on a fresh copy and return that.
        """
        original = indigo.PluginBase.getDeviceStateList(self, dev)
        if original is None:
            return original

        # Make a shallow copy.  indigo.List/indigo.Dict items inside are reused
        # by reference — that's fine; we only need the OUTER list to be a
        # distinct object so append() doesn't mutate the parser's cache.
        state_list = list(original)

        seen_csv = dev.pluginProps.get("seenDynamicKeys", "")
        if not seen_csv:
            return state_list

        type_map = self._load_dynamic_types(dev)

        # Build the set of static-state IDs already in the list.
        existing_ids = set()
        try:
            for s in state_list:
                k = s.get("Key") if hasattr(s, "get") else s["Key"]
                if k:
                    existing_ids.add(k)
        except Exception:
            existing_ids = set()

        for key in seen_csv.split(","):
            key = key.strip()
            if not key or key in existing_ids:
                continue
            if not self._is_valid_state_id(key):
                continue  # paranoid — should already be filtered by writer
            label = key[:1].upper() + key[1:]  # cosmetic camelCase -> CamelCase
            token = type_map.get(key)
            if token is None:
                # No recorded type yet (pre-upgrade device, before any payload has
                # arrived since the upgrade).  Fall back to inferring from the
                # current stored value, defaulting to String.  The next captured
                # payload records a proper token via _capture_raw_fields.
                # dev.states is None at declaration time (v1.9.13 note) — the
                # old hasattr() check passed and None.get() raised (v1.9.23).
                try:
                    current = dev.states.get(key) if dev.states else None
                except Exception:
                    current = None
                if isinstance(current, bool):
                    token = "bool"
                elif isinstance(current, float):
                    token = "real"
                elif isinstance(current, int):
                    token = "int"
                else:
                    token = "str"
            try:
                state_list.append(self._state_dict_for_token(key, label, token))
                existing_ids.add(key)
            except Exception:
                # Skip silently — the writer logs detail; this method must return
                # a clean list every time getDeviceStateList is called.
                continue
        return state_list

    def deviceStopComm(self, dev):
        if dev.deviceTypeId == "z2mCoordinator":
            prefix = dev.pluginProps.get("mqtt_prefix", "")
            with self.maps_lock:
                self.coordinator_map.pop(prefix, None)
            if self.debug:
                log(f"Stopped coordinator: {dev.name}")
            return
        fname = dev.pluginProps.get("friendly_name", "")
        ieee = dev.pluginProps.get("ieee_address", "")
        self._cancel_state_request(dev.id)
        with self.maps_lock:
            self.friendly_name_map.pop((self._device_prefix(dev), fname), None)
            self.ieee_map.pop(ieee, None)
            self._motion_states.pop(dev.id, None)
        if self.debug:
            log(f"Stopped device: {dev.name}")

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Restart device comm only for changes that materially affect the MQTT
        subscription or device identity.

        Z2M devices route via MQTT topics built from `friendly_name` and are
        identified by `ieee_address`; a change to either requires a fresh comm
        cycle so subscriptions and lookup maps track. The coordinator's
        `mqtt_prefix` defines the topic root.

        All other pluginProps — `vendor`, `model`, `capabilities_display`,
        internal capability flags, `seenDynamicKeys`, `dynamicKeyTypes` — are
        cosmetic or healing writes that should NOT cycle comm.
        """
        keys = ("friendly_name", "ieee_address", "mqtt_prefix")
        return any(oldDevice.pluginProps.get(k) != newDevice.pluginProps.get(k) for k in keys)

    # ── Action handlers ───────────────────────────────────────────────────────

    def actionControlDevice(self, action, dev):
        """Handle all plugin device actions.

        In Indigo 2025.x all plugin device actions are routed through actionControlDevice
        regardless of device class.  Forward dimmer-class devices (z2mLight, z2mCover) to
        actionControlDimmer so their SetBrightness / SetColorLevels / etc. are handled.
        """
        if dev.deviceTypeId in ("z2mLight", "z2mCover"):
            self.actionControlDimmer(action, dev)
            return

        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        # Repeaters take no commands — their onOffState mirrors availability.
        # Publishing a /set used to log apparent success at a device that
        # ignores it (v1.9.23). Status requests are still allowed.
        if (dev.deviceTypeId == "z2mRepeater"
                and cmd != indigo.kDeviceAction.RequestStatus):
            log(f"{dev.name} is a repeater — it takes no on/off commands "
                f"(its state mirrors availability)", level="WARNING")
            return

        # Locks speak LOCK/UNLOCK, not ON/OFF (v1.10.0). Indigo's lock/unlock
        # UI arrives here as TurnOn/TurnOff on the relay class.
        if dev.deviceTypeId == "z2mLock":
            if cmd == indigo.kDeviceAction.TurnOn:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "LOCK"},
                                  dev, "lock")
            elif cmd == indigo.kDeviceAction.TurnOff:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "UNLOCK"},
                                  dev, "unlock")
            elif cmd == indigo.kDeviceAction.Toggle:
                new_state = "UNLOCK" if dev.onState else "LOCK"
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state},
                                  dev, new_state.lower())
            elif cmd == indigo.kDeviceAction.RequestStatus:
                self._request_state(fname, dev.deviceTypeId, prefix,
                                    dev_props=dict(dev.pluginProps))
                log(f'sent "{dev.name}" status request')
            else:
                log(f"Unhandled lock action {cmd} for {dev.name}", level="WARNING")
            return

        if cmd == indigo.kDeviceAction.TurnOn:
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": "ON"}, dev, "on")
        elif cmd == indigo.kDeviceAction.TurnOff:
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OFF"}, dev, "off")
        elif cmd == indigo.kDeviceAction.Toggle:
            new_state = "OFF" if dev.onState else "ON"
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state}, dev,
                              f"toggle -> {new_state.lower()}")
        elif cmd == indigo.kDeviceAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled relay action {cmd} for {dev.name}", level="WARNING")

    def actionControlDimmer(self, action, dev):
        """Handle dimmer-class device actions (z2mLight and z2mCover)."""
        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        is_cover = (dev.deviceTypeId == "z2mCover")

        if cmd == indigo.kDimmerRelayAction.TurnOn:
            if is_cover:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OPEN"}, dev, "open")
            else:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "ON"}, dev, "on")

        elif cmd == indigo.kDimmerRelayAction.TurnOff:
            if is_cover:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "CLOSE"}, dev, "close")
            else:
                self._publish_cmd(f"{prefix}/{fname}/set", {"state": "OFF"}, dev, "off")

        elif cmd == indigo.kDimmerRelayAction.Toggle:
            if is_cover:
                new_state = "CLOSE" if dev.onState else "OPEN"
            else:
                new_state = "OFF" if dev.onState else "ON"
            self._publish_cmd(f"{prefix}/{fname}/set", {"state": new_state}, dev,
                              f"toggle -> {new_state.lower()}")

        elif cmd == indigo.kDimmerRelayAction.SetBrightness:
            level = action.actionValue  # 0-100
            if is_cover:
                self._publish_cmd(f"{prefix}/{fname}/set", {"position": level}, dev,
                                  f"set position to {level}%")
            else:
                brightness = _brightness_100_to_255(level)
                payload = {"brightness": brightness, "state": "ON" if level > 0 else "OFF"}
                self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                                  f"set brightness to {level}%")

        elif cmd in (indigo.kDimmerRelayAction.BrightenBy, indigo.kDimmerRelayAction.DimBy):
            current = dev.brightness
            delta   = action.actionValue
            if cmd == indigo.kDimmerRelayAction.BrightenBy:
                new_level = min(100, current + delta)
            else:
                new_level = max(0, current - delta)
            if is_cover:
                verb = "open" if cmd == indigo.kDimmerRelayAction.BrightenBy else "close"
                self._publish_cmd(f"{prefix}/{fname}/set", {"position": new_level}, dev,
                                  f"{verb} by {delta}% -> {new_level}%")
            else:
                brightness = _brightness_100_to_255(new_level)
                payload = {"brightness": brightness, "state": "ON" if new_level > 0 else "OFF"}
                verb = "brighten" if cmd == indigo.kDimmerRelayAction.BrightenBy else "dim"
                self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                                  f"{verb} by {delta}% -> {new_level}%")

        elif cmd == indigo.kDimmerRelayAction.SetColorLevels:
            # Only applicable to z2mLight
            if is_cover:
                log(f"{dev.name}: SetColorLevels not applicable to cover", level="WARNING")
                return
            color_vals = action.actionValue
            if "whiteTemperature" in color_vals:
                kelvin = int(color_vals["whiteTemperature"])
                kelvin = max(1000, min(10000, kelvin))
                mireds = _kelvin_to_mireds(kelvin)
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"color_temp": mireds, "state": "ON"}, dev,
                                  f"set color temp to {kelvin}K")
            elif all(k in color_vals for k in ("redLevel", "greenLevel", "blueLevel")):
                r = int(round(float(color_vals["redLevel"])   / 100.0 * 255))
                g = int(round(float(color_vals["greenLevel"]) / 100.0 * 255))
                b = int(round(float(color_vals["blueLevel"])  / 100.0 * 255))
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"color": {"r": r, "g": g, "b": b}, "state": "ON"}, dev,
                                  f"set color RGB ({r}, {g}, {b})")
            else:
                log(f"{dev.name}: SetColorLevels — no actionable channels in {list(color_vals.keys())}", level="WARNING")

        else:
            log(f"Unhandled dimmer action {cmd} for {dev.name}", level="WARNING")

    def actionControlUniversal(self, action, dev):
        # Indigo's universal-action callback is actionControlUniversal (confirmed
        # against all SDK device examples) — NOT actionControlUniversalDevices, which
        # Indigo never calls (the old name left this handler dead; everyday Send Status
        # Request still worked because the class-specific handlers also service it).
        cmd    = action.deviceAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kUniversalAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
        else:
            log(f"Unhandled universal action {cmd} for {dev.name}", level="WARNING")

    def actionControlSensor(self, action, dev):
        """Handle sensor-class device actions.

        z2m sensors are read-only — the network does not accept commands back
        to them — so the only meaningful action is RequestStatus, which we
        service by re-publishing the /get topic so z2mqtt resends the
        retained payload. Implementing this method silences the
        'plugin does not define method actionControlSensor' error that
        Indigo logs whenever any Send Status Request (or similar) action
        is fired against a z2m sensor device.

        NOTE: SensorAction uses .sensorAction (NOT .deviceAction — that
        attribute only exists on DeviceAction / DimmerAction). Confirmed
        25-05-2026: passing action.deviceAction raises
        "'SensorAction' object has no attribute 'deviceAction'".
        """
        cmd    = action.sensorAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)

        if cmd == indigo.kSensorAction.RequestStatus:
            self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled sensor action {cmd} for {dev.name} "
                f"(sensors are read-only)", level="WARNING")

    def actionControlThermostat(self, action, dev):
        """Handle thermostat-class device actions for z2mThermostat (v1.10.0).

        NOTE: thermostat actions arrive via action.thermostatAction (each device
        class has its OWN action attribute — .deviceAction raises here).
        Setpoints publish the z2m key stored in the device's setpoint_key prop
        (current_heating_setpoint by default; some TRVs use occupied_).
        """
        cmd    = action.thermostatAction
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        sp_key = dev.pluginProps.get("setpoint_key", "current_heating_setpoint")

        def _current_setpoint():
            try:
                return float(dev.states.get("setpointHeat", 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        if cmd == indigo.kThermostatAction.SetHeatSetpoint:
            try:
                sp = round(float(action.actionValue), 1)
            except (TypeError, ValueError):
                log(f"{dev.name}: invalid heat setpoint value", level="ERROR")
                return
            self._publish_cmd(f"{prefix}/{fname}/set", {sp_key: sp}, dev,
                              f"set heat setpoint to {sp}")
        elif cmd in (indigo.kThermostatAction.IncreaseHeatSetpoint,
                     indigo.kThermostatAction.DecreaseHeatSetpoint):
            try:
                delta = float(action.actionValue)
            except (TypeError, ValueError):
                delta = 1.0
            if cmd == indigo.kThermostatAction.DecreaseHeatSetpoint:
                delta = -delta
            sp = round(_current_setpoint() + delta, 1)
            self._publish_cmd(f"{prefix}/{fname}/set", {sp_key: sp}, dev,
                              f"set heat setpoint to {sp}")
        elif cmd == indigo.kThermostatAction.SetHvacMode:
            mode_map = {}
            try:
                mode_map = {indigo.kHvacMode.Heat:     "heat",
                            indigo.kHvacMode.HeatCool: "auto",
                            indigo.kHvacMode.Off:      "off"}
            except Exception:
                pass
            z2m_mode = mode_map.get(action.actionMode)
            if z2m_mode:
                self._publish_cmd(f"{prefix}/{fname}/set",
                                  {"system_mode": z2m_mode}, dev,
                                  f"set mode {z2m_mode}")
            else:
                log(f"{dev.name}: HVAC mode {action.actionMode} not supported "
                    f"(heat/auto/off only)", level="WARNING")
        elif cmd in (indigo.kThermostatAction.RequestStatusAll,
                     indigo.kThermostatAction.RequestTemperatures,
                     indigo.kThermostatAction.RequestSetpoints,
                     indigo.kThermostatAction.RequestMode):
            self._request_state(fname, dev.deviceTypeId, prefix,
                                dev_props=dict(dev.pluginProps))
            log(f'sent "{dev.name}" status request')
        else:
            log(f"Unhandled thermostat action {cmd} for {dev.name} "
                f"(cooling is not supported on z2m TRVs)", level="WARNING")

    def action_set_color_temperature(self, action, dev=None, callerWaitingForResult=None):
        """Action: set light color temperature in Kelvin."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        if not (dev.pluginProps.get("has_color_temp", False) or dev.supportsWhiteTemperature):
            log(f"{dev.name}: color temperature not supported", level="WARNING")
            return
        try:
            kelvin = int(action.props.get("kelvin", 2700))
            kelvin = max(1000, min(10000, kelvin))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid kelvin value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        mireds = _kelvin_to_mireds(kelvin)
        self._publish(f"{prefix}/{fname}/set", {"color_temp": mireds, "state": "ON"})
        if self.debug:
            log(f"{dev.name}: set color temp {kelvin}K ({mireds} mireds)")

    def action_set_brightness(self, action, dev=None, callerWaitingForResult=None):
        """Action: set brightness (light) or position (cover) 0-100."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        try:
            level = max(0, min(100, int(action.props.get("brightness", 100))))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid brightness value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        if dev.deviceTypeId == "z2mCover":
            self._publish(f"{prefix}/{fname}/set", {"position": level})
            if self.debug:
                log(f"{dev.name}: set position {level}%")
        else:
            brightness = _brightness_100_to_255(level)
            self._publish(f"{prefix}/{fname}/set",
                          {"brightness": brightness, "state": "ON" if level > 0 else "OFF"})
            if self.debug:
                log(f"{dev.name}: set brightness {level}%")

    def action_set_cover_position(self, action, dev=None, callerWaitingForResult=None):
        """Action: set cover position 0-100."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        try:
            position = max(0, min(100, int(action.props.get("position", 50))))
        except (ValueError, TypeError):
            log(f"{dev.name}: invalid position value", level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._publish(f"{prefix}/{fname}/set", {"position": position})
        if self.debug:
            log(f"{dev.name}: set cover position {position}%")

    def action_refresh_state(self, action, dev=None, callerWaitingForResult=None):
        """Action: request current state from device."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._request_state(fname, dev.deviceTypeId, prefix, dev_props=dict(dev.pluginProps))

    def action_publish_custom(self, action, dev=None, callerWaitingForResult=None):
        """Action: publish a user-supplied JSON payload to this device's /set
        topic (v1.10.0) — the escape hatch for device options the typed actions
        don't cover (sensitivity, LED modes, calibration, child lock...). Uses
        z2m's snake_case property names, e.g. {"motion_sensitivity": "high"}."""
        if dev is None:
            dev = indigo.devices[action.deviceId]
        raw = (action.props.get("json_payload") or "").strip()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except (ValueError, TypeError) as e:
            log(f"{dev.name}: custom payload is not valid JSON ({e}): {raw!r}",
                level="ERROR")
            return
        fname  = dev.pluginProps.get("friendly_name", "")
        prefix = self._device_prefix(dev)
        self._publish_cmd(f"{prefix}/{fname}/set", payload, dev,
                          f"custom payload {payload}")

    def validateActionConfigUi(self, valuesDict, typeId, deviceId):
        """Validate action dialogs at save time (v1.10.0 — the custom-publish
        JSON gets checked here instead of failing at run time)."""
        errors = indigo.Dict()
        if typeId == "publishCustom":
            raw = (valuesDict.get("json_payload") or "").strip()
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("must be a JSON object, e.g. {\"key\": \"value\"}")
            except (ValueError, TypeError) as e:
                errors["json_payload"] = f"Not a valid JSON object: {e}"
        return (len(errors) == 0), valuesDict, errors

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

    # ── MQTT internals ────────────────────────────────────────────────────────

    def _effective_broker(self):
        # IndigoSecrets first, PluginConfig fallback, "" if neither set.
        return MQTT_BROKER or self.pluginPrefs.get("mqtt_broker", "").strip()

    def _effective_port(self):
        if MQTT_PORT:
            # IndigoSecrets may hold the port as a string ("1883") — paho.connect
            # needs an int, so coerce it here too rather than trusting the type.
            try:
                return int(MQTT_PORT)
            except (TypeError, ValueError):
                log(f"Invalid MQTT_PORT in IndigoSecrets ({MQTT_PORT!r}) — using 1883",
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
        username = MQTT_USERNAME or self.pluginPrefs.get("mqtt_username", "").strip()
        password = MQTT_PASSWORD or self.pluginPrefs.get("mqtt_password", "")

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

        # Update the coordinator's deviceCount + lastUpdate (if one exists for this prefix)
        self._update_coordinator(prefix, deviceCount=sum(
            1 for d in self.bridge_devices.values()
            if d.get("_mqtt_prefix") == prefix))

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

    def _process_availability(self, friendly_name, payload, prefix=None):
        """Handle availability message — update the 'availability' state.
        Lookup is prefix-qualified (v1.9.22) so a name shared across the two
        bridges resolves to the right device."""
        if prefix is None:
            prefix = self._topic_prefix()
        dev_id = self.friendly_name_map.get((prefix, friendly_name))
        if dev_id is None:
            return
        try:
            dev   = indigo.devices[dev_id]
            state = payload.get("state", "offline") if isinstance(payload, dict) else str(payload)
            dev.updateStateOnServer("availability", state, uiValue=state.capitalize())

            # For z2mRepeater devices mirror availability into onOffState so the
            # device list shows Online/Offline instead of the relay default On/Off.
            if dev.deviceTypeId == "z2mRepeater":
                is_online = (state == "online")
                dev.updateStateOnServer(
                    "onOffState", is_online,
                    uiValue="Online" if is_online else "Offline"
                )

            if self.debug:
                log(f"{dev.name}: availability = {state}")
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"availability update for '{friendly_name}'")

    def _process_device_state(self, friendly_name, payload, prefix=None):
        """Dispatch a device state payload to the type-specific handler.
        Lookup is prefix-qualified (v1.9.22) so a name shared across the two
        bridges routes each bridge's payloads to its own device."""
        if prefix is None:
            prefix = self._topic_prefix()
        dev_id = self.friendly_name_map.get((prefix, friendly_name))
        if dev_id is None:
            return  # unknown device or from another plugin/prefix
        if not isinstance(payload, dict):
            return
        try:
            dev = indigo.devices[dev_id]
        except Exception:
            return

        # Auto-reclassify: if any non-button device receives an action payload
        # (e.g. a TuYa button misidentified as relay by zigbee2mqtt), delete
        # the wrong device and recreate it as z2mButton automatically. Require a
        # NAMED action (one carrying a letter) — a bare button index like "2" or
        # other junk carries no button semantics and must not drive a destructive
        # delete+recreate (the exposes guard below is the primary protection).
        action_val = payload.get("action")
        if (action_val not in (None, "") and any(c.isalpha() for c in str(action_val))
                and dev.deviceTypeId != "z2mButton"
                and self._should_reclassify_as_button(dev)):
            self._reclassify_as_button(dev, payload)
            return

        type_id = dev.deviceTypeId
        if type_id == "z2mLight":
            self._process_light_state(dev, payload)
        elif type_id == "z2mRelay":
            self._process_relay_state(dev, payload)
        elif type_id == "z2mContactSensor":
            self._process_contact_sensor_state(dev, payload)
        elif type_id == "z2mOccupancySensor":
            self._process_occupancy_sensor_state(dev, payload)
        elif type_id == "z2mWaterLeakSensor":
            self._process_water_leak_sensor_state(dev, payload)
        elif type_id == "z2mTemperatureSensor":
            self._process_temperature_sensor_state(dev, payload)
        elif type_id == "z2mSensor":
            self._process_sensor_state(dev, payload)
        elif type_id == "z2mRepeater":
            self._process_repeater_state(dev, payload)
        elif type_id == "z2mCover":
            self._process_cover_state(dev, payload)
        elif type_id == "z2mButton":
            self._process_button_state(dev, payload)
        elif type_id == "z2mLock":
            self._process_lock_state(dev, payload)
        elif type_id == "z2mThermostat":
            self._process_thermostat_state(dev, payload)

        # After type-specific handling, capture any remaining payload fields as
        # dynamic states so all Z2M data is imported (not just the semantically-
        # mapped subset).  See _capture_raw_fields docstring.
        try:
            self._capture_raw_fields(dev, payload)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"{dev.name} raw-field capture")

    def _is_valid_state_id(self, key):
        """Indigo XML state IDs must start with an ASCII letter and contain only
        ASCII letters and digits.  Underscores are NOT accepted — Indigo's XML
        validator rejects them with LowLevelBadParameterError 'illegal XML tag
        name character' even though XML itself permits them.  Convention in the
        Indigo SDK is camelCase (linkQuality, colorMode, batteryLevel, etc.).
        """
        if not key or not key[0].isascii() or not key[0].isalpha():
            return False
        for c in key:
            if not (c.isascii() and c.isalnum()):
                return False
        return True

    def _process_light_state(self, dev, payload):
        """Update z2mLight device states from MQTT payload."""
        has_ct  = getattr(dev, "supportsWhiteTemperature", False)
        has_col = getattr(dev, "supportsColor", False)

        updates = []

        if "state" in payload:
            updates.append(("onOffState", str(payload["state"]).upper() == "ON"))

        # Each numeric block is guarded so one malformed field (a non-numeric or
        # null value from a flaky device) is skipped rather than raising and dropping
        # the WHOLE update batch (the exception otherwise propagates to runConcurrentThread).
        if "brightness" in payload:
            try:
                is_on = str(payload.get("state", "ON")).upper() == "ON"
                level = _brightness_255_to_100(int(payload["brightness"])) if is_on else 0
                updates.append(("brightnessLevel", level))
                # Keep the two native states consistent: a dimmer at 0 brightness is
                # OFF in Indigo's model. Some bulbs briefly publish {"state":"ON",
                # "brightness":0} during a fade-to-off, which would otherwise leave
                # onOffState ON while the level reads 0. This append wins over the
                # state-derived onOffState above (updates apply in order).
                if level == 0:
                    updates.append(("onOffState", False))
            except (ValueError, TypeError):
                pass

        if has_ct and "color_temp" in payload and payload["color_temp"] is not None:
            try:
                kelvin = _mireds_to_kelvin(int(payload["color_temp"]))
                updates.append(("whiteTemperature", kelvin))
                updates.append(("colorTemp", kelvin, f"{kelvin} K"))
            except (ValueError, TypeError):
                pass

        # colorMode only means something on a bulb with CT or colour — writing
        # it unconditionally surfaced the state on plain dimmers, which the
        # capability gate in _ensure_device_states deliberately hides (v1.9.23).
        if "color_mode" in payload and (has_col or has_ct):
            cm = payload["color_mode"]
            if cm == "color_temp":
                updates.append(("colorMode", "color_temp", "Color Temp"))
            elif cm in ("xy", "hs"):
                updates.append(("colorMode", "color_rgb", "Color"))

        if has_col:
            color = payload.get("color", {})
            if isinstance(color, dict):
                try:
                    if "x" in color and "y" in color:
                        r, g, b = _xy_to_rgb(float(color["x"]), float(color["y"]))
                        updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])
                    elif "hue" in color and "saturation" in color:
                        r, g, b = _hs_to_rgb(float(color["hue"]), float(color["saturation"]))
                        updates.extend([("redLevel", r), ("greenLevel", g), ("blueLevel", b)])
                except (ValueError, TypeError):
                    pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_relay_state(self, dev, payload):
        """Update z2mRelay device states from MQTT payload."""
        updates = []

        if "state" in payload:
            updates.append(("onOffState", str(payload["state"]).upper() == "ON"))

        if "power" in payload:
            try:
                watts = float(payload["power"])
                updates.append(("power", watts, f"{watts:.1f} W"))
            except (ValueError, TypeError):
                pass

        if "energy" in payload:
            try:
                kwh = float(payload["energy"])
                updates.append(("energy", kwh, f"{kwh:.3f} kWh"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_contact_sensor_state(self, dev, payload):
        """Update z2mContactSensor device states from MQTT payload.

        contact=True  → door/window closed → onOffState=False  (sensor at rest)
        contact=False → door/window open   → onOffState=True   (sensor triggered)
        """
        updates = []

        if "contact" in payload:
            val = _payload_bool(payload["contact"])   # "false"/"OFF" tokens safe
            if val is not None:
                is_open = not val
                updates.append(("contact",    val))
                updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_occupancy_sensor_state(self, dev, payload):
        """Update z2mOccupancySensor device states from MQTT payload.

        Both 'occupancy' (PIR) and 'presence' (mmWave) map to onOffState.
        Either being True sets onOffState=True so a fast PIR trigger is not lost.
        """
        updates = []

        # Motion-related keys that different sensors use under different names.
        # We track the last known value of every key a device has ever sent so
        # partial payloads (only one key changing) don't lose the other sensors' state.
        MOTION_KEYS = ("motion", "occupancy", "presence", "pir")

        store = self._motion_states.setdefault(dev.id, {})
        motion_updated = False
        for key in MOTION_KEYS:
            if key in payload:
                val = _payload_bool(payload[key])   # string tokens safe
                if val is not None:
                    store[key] = val
                    motion_updated = True

        if motion_updated:
            detected = any(store.values())
            # Update named custom states for keys the device actually sends
            if "occupancy" in store:
                updates.append(("occupancy", store["occupancy"],
                                "Detected" if store["occupancy"] else "Clear"))
            if "presence" in store:
                updates.append(("presence",  store["presence"],
                                "Detected" if store["presence"]  else "Clear"))
            updates.append(("motion",     detected))
            updates.append(("onOffState", detected, "Detected" if detected else "Clear"))

            if self.debug:
                log(f"{dev.name}: motion store={store} -> detected={detected}")

        # Self-heal capability flags if payload contains data the stored flags deny.
        # This corrects devices created when exposes data was incomplete.
        props = dev.ownerProps
        heal = {}
        if "occupancy" in store and not props.get("has_pir",      False):
            heal["has_pir"]      = True
        if "presence"  in store and not props.get("has_presence", False):
            heal["has_presence"] = True
        if heal:
            with self.props_lock:   # atomic RMW vs menu-thread refresh
                new_props = dict(dev.ownerProps)   # re-read under the lock
                new_props.update(heal)
                dev.replacePluginPropsOnServer(new_props)
            log(f"{dev.name}: corrected capability flags: {heal}")

        if "illuminance_lux" in payload or "illuminance" in payload:
            try:
                raw = payload.get("illuminance_lux", payload.get("illuminance"))
                illum = round(float(raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_water_leak_sensor_state(self, dev, payload):
        """Update z2mWaterLeakSensor device states from MQTT payload.

        water_leak=True  → leak detected → onOffState=True
        water_leak=False → all clear     → onOffState=False
        """
        updates = []

        if "water_leak" in payload:
            leak = _payload_bool(payload["water_leak"])   # string tokens safe
            if leak is not None:
                updates.append(("waterLeak",   leak))
                updates.append(("onOffState",  leak, "Leak!" if leak else "OK"))

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_temperature_sensor_state(self, dev, payload):
        """Update z2mTemperatureSensor device states from MQTT payload.

        Environmental sensor — no binary alarm state; onOffState is not used.
        """
        updates = []

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "pressure" in payload:
            try:
                pres = round(float(payload["pressure"]), 1)
                updates.append(("pressure", pres, f"{pres} hPa"))
            except (ValueError, TypeError):
                pass

        if "illuminance_lux" in payload or "illuminance" in payload:
            try:
                raw   = payload.get("illuminance_lux", payload.get("illuminance"))
                illum = round(float(raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_sensor_state(self, dev, payload):
        """Update z2mSensor device states from MQTT payload."""
        updates = []

        # Track which binary states are present for onOffState priority
        smoke      = None
        water_leak = None
        occupancy  = None
        contact    = None

        if "smoke" in payload:
            # Life-safety: smoke detectors classify as the generic sensor type,
            # so the alarm is surfaced here (declared `smoke` state + top
            # onOffState priority). _payload_bool handles the string tokens
            # ("false"/"OFF") a non-conforming device might publish — a raw
            # bool() would read those as True.
            val = _payload_bool(payload["smoke"])
            if val is not None:
                smoke = val
                updates.append(("smoke", val, "Smoke!" if val else "OK"))

        if "water_leak" in payload:
            val = _payload_bool(payload["water_leak"])   # string tokens safe
            if val is not None:
                water_leak = val
                updates.append(("waterLeak", val))

        # Handle motion/occupancy/presence — different sensors use different key names:
        #   "motion"     — Aqara FP300 and similar (fires on movement, clears quickly)
        #   "occupancy"  — PIR sensors (fast trigger, clears after timeout)
        #   "presence"   — mmWave/radar sensors (slower trigger, stays True while stationary)
        #   "pir"        — some combo sensors expose the raw PIR channel under this name
        # Track the last-known value of every motion key in self._motion_states
        # (same store pattern as _process_occupancy_sensor_state) so a PARTIAL
        # payload (only one key changing) ORs against the others rather than
        # clearing them. Without the store a mixed PIR+mmWave device that lands on
        # this catch-all type drops a still-present person whenever one component
        # key updates on its own. Only clears when ALL known keys are False.
        store = self._motion_states.setdefault(dev.id, {})
        motion_updated = False
        for key in ("motion", "occupancy", "presence", "pir"):
            if key in payload:
                val = _payload_bool(payload[key])   # string tokens safe
                if val is not None:
                    store[key] = val
                    motion_updated = True
        if motion_updated:
            combined = any(store.values())
            occupancy = combined
            updates.append(("motion", combined))

        if "contact" in payload:
            # contact=True means closed (sensor active), contact=False means open
            val = _payload_bool(payload["contact"])   # string tokens safe
            if val is not None:
                contact = val
                updates.append(("contact", val))

        if "temperature" in payload:
            try:
                temp = round(float(payload["temperature"]), 1)
                updates.append(("temperature", temp, f"{temp} C"))
            except (ValueError, TypeError):
                pass

        if "humidity" in payload:
            try:
                hum = round(float(payload["humidity"]), 1)
                updates.append(("humidity", hum, f"{hum} %"))
            except (ValueError, TypeError):
                pass

        if "pressure" in payload:
            try:
                pres = round(float(payload["pressure"]), 1)
                updates.append(("pressure", pres, f"{pres} hPa"))
            except (ValueError, TypeError):
                pass

        # Prefer illuminance_lux; fall back to illuminance
        illum_raw = payload.get("illuminance_lux", payload.get("illuminance"))
        if illum_raw is not None:
            try:
                illum = round(float(illum_raw), 1)
                updates.append(("illuminance", illum, f"{illum} lux"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        # Assign onOffState: priority smoke > waterLeak > occupancy/presence > contact
        if smoke is not None:
            updates.append(("onOffState", smoke, "Smoke!" if smoke else "OK"))
        elif water_leak is not None:
            updates.append(("onOffState", water_leak, "Leak!" if water_leak else "OK"))
        elif occupancy is not None:
            updates.append(("onOffState", occupancy, "Detected" if occupancy else "Clear"))
        elif contact is not None:
            # contact=False means open (door/window open) -> sensor triggered -> onOffState=True
            is_open = not contact
            updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))

        self._apply_updates(dev, updates)

    def _process_repeater_state(self, dev, payload):
        """Update z2mRepeater device states from MQTT payload.

        Repeaters only report linkquality. onOffState is driven by availability,
        not by payload, so no onOffState update is made here.
        """
        updates = []
        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass
        self._apply_updates(dev, updates)

    def _should_reclassify_as_button(self, dev):
        """Guard for the auto-reclassify-to-button path. A non-button device should
        only be deleted + recreated as a button if it has NO primary output
        capability. A legitimate combo device — a dimmer, cover or switch that ALSO
        publishes scene 'action's on the same MQTT topic — must never be destroyed:
        that would lose all on/off/brightness/colour/position control and orphan
        every trigger, link and control-page reference to its device id.

        Re-check the device's CURRENT Z2M exposes (self.bridge_devices): reclassify
        only when there is no presence/occupancy, no brightness, no position, no
        writable on/off state and no light/cover/switch composite. If the exposes
        can't be found, fall back to the conservative rule that only the catch-all
        sensor/repeater types may auto-convert (a relay keeps its relay device —
        recreate manually if needed).
        """
        if dev.deviceTypeId in ("z2mLight", "z2mCover", "z2mLock", "z2mThermostat"):
            return False
        props = dev.pluginProps
        ieee  = (props.get("ieee_address") or "").strip()
        fname = (props.get("friendly_name") or "").strip()
        data  = None
        for d in (self.bridge_devices or {}).values():
            if ((ieee and (d.get("ieee_address") or "").strip() == ieee)
                    or (fname and (d.get("friendly_name") or "").strip() == fname)):
                data = d
                break
        exposes = ((data or {}).get("definition") or {}).get("exposes") or []
        exposes = [e for e in exposes if isinstance(e, dict)]
        if not exposes:
            # No exposes to re-check — only the no-output catch-all types may convert.
            return dev.deviceTypeId in ("z2mSensor", "z2mRepeater")
        # A presence/occupancy sensor must NEVER be reclassified as a button: on
        # such a device the `action` enum carries region/presence events
        # (enter/leave/occupied), not scene-controller presses. This mirrors the
        # same gate in _detect_device_type (added v1.9.17). Without it,
        # _reclassify_as_button DELETES the live occupancy device and recreates it
        # as a button — orphaning its id and every trigger/link referencing it.
        # The Aqara FP1 (RTCZCGQ11LM) emits region `action` events and hit exactly
        # this path. The detection-time gate alone was not enough — the runtime
        # reclassify guard had drifted out of sync with it.
        # motion/pir included since v1.9.21: a motion sensor with a named action
        # channel is a motion sensor first, same as presence/occupancy devices.
        feat_names = {feat.get("name") for feat in _iter_features(exposes)}
        if feat_names & {"presence", "occupancy", "motion", "pir"}:
            return False
        for entry in exposes:
            if entry.get("type") in ("light", "cover", "switch", "lock", "climate"):
                return False
        for feat in _iter_features(exposes):
            name = feat.get("name")
            if name in ("brightness", "position"):
                return False
            if (name == "state" and feat.get("type") == "binary"
                    and (feat.get("access", 0) & 2)):  # bit 1 = writable
                return False
        return True

    def _reclassify_as_button(self, dev, payload):
        """Delete a misclassified device and recreate it as z2mButton.

        Called when an action payload arrives on a non-button device —
        typically a TuYa/Ikea button that zigbee2mqtt fingerprinted as relay.
        After recreation the action is processed immediately on the new device.
        """
        action_val    = str(payload.get("action", ""))
        old_id        = dev.id
        dev_name      = dev.name
        folder_id     = dev.folderId
        friendly_name = dev.pluginProps.get("friendly_name", "")
        ieee_address  = dev.pluginProps.get("ieee_address", "")
        vendor        = dev.pluginProps.get("vendor", "")
        model         = dev.pluginProps.get("model", "")
        mqtt_prefix   = dev.pluginProps.get("mqtt_prefix", self._topic_prefix())

        log(f"Auto-reclassify: '{dev_name}' received action='{action_val}' "
            f"but is type '{dev.deviceTypeId}'. Recreating as Z2M Button...", level="WARNING")

        try:
            indigo.device.delete(dev)
        except Exception as e:
            log(f"Reclassify: could not delete '{dev_name}': {e}", level="ERROR")
            return

        # Remove stale mappings — BOTH friendly_name_map and ieee_map point at the
        # now-deleted old_id; leaving ieee_map stale makes rename detection resolve
        # the deleted device id. Under maps_lock: the comprehension rebuild iterates
        # the dict, so a concurrent deviceStopComm pop would otherwise RuntimeError.
        with self.maps_lock:
            self.friendly_name_map = {
                k: v for k, v in self.friendly_name_map.items() if v != old_id
            }
            self.ieee_map = {
                k: v for k, v in self.ieee_map.items() if v != old_id
            }

        # Derive has_battery from the device's CURRENT exposes instead of
        # hardcoding False (v1.9.23): buttons are battery devices almost by
        # definition, and the flag never healed afterwards (buttons have no
        # capability detector, so Refresh Device Capabilities skips them).
        has_battery = False
        for d in (self.bridge_devices or {}).values():
            if ((ieee_address and (d.get("ieee_address") or "").strip() == ieee_address)
                    or (friendly_name and (d.get("friendly_name") or "").strip() == friendly_name)):
                exp = ((d.get("definition") or {}).get("exposes")) or []
                has_battery = any(f.get("name") == "battery"
                                  for f in _iter_features(exp))
                break

        new_props = {
            "friendly_name":      friendly_name,
            "ieee_address":       ieee_address,
            "vendor":             vendor,
            "model":              model,
            "has_battery":        has_battery,
            "capabilities_display": "button actions",
            "mqtt_prefix":        mqtt_prefix,
        }

        try:
            # Bug fix v1.9.9: _ensure_device_folder() requires the folder name —
            # was called with no argument here, crashing every reclassify of a
            # device that lived at the root level (folderId=0). Match the other
            # three call sites (discover_create_devices, create_coordinator_devices,
            # _process_bridge_devices) — all pass DEVICE_FOLDER_NAME.
            folder_id_to_use = folder_id if folder_id else self._ensure_device_folder(DEVICE_FOLDER_NAME)
            new_dev = indigo.device.create(
                protocol=indigo.kProtocol.Plugin,
                name=dev_name,
                pluginId=self.pluginId,
                deviceTypeId="z2mButton",
                folder=folder_id_to_use,
                props=new_props,
            )
            with self.maps_lock:
                self.friendly_name_map[(mqtt_prefix, friendly_name)] = new_dev.id
                if ieee_address:
                    self.ieee_map[ieee_address] = new_dev.id
            log(f"Reclassify complete: '{dev_name}' is now Z2M Button (id={new_dev.id})")
            self._process_button_state(new_dev, payload)
        except Exception as e:
            log(f"Reclassify: could not create button device '{dev_name}': {e}", level="ERROR")

    def _process_button_state(self, dev, payload):
        """Update z2mButton device states from MQTT action payload.

        action payloads are stateless events (e.g. {"action": "1_single"}).
        pressCount always increments so Indigo triggers fire even on repeated
        presses of the same button (lastAction alone would not change value).
        """
        updates = []

        if "action" in payload and payload["action"] not in (None, ""):
            action = str(payload["action"])

            # Extract button number: "1_single" → 1, "2_double" → 2, "on" → 0
            btn = 0
            try:
                btn = int(action.split("_")[0])
            except (ValueError, IndexError):
                pass

            # lastAction is a List enumeration (v1.9.12) — write the normalised
            # camelCase token so Indigo's auto-generated lastAction.<value>
            # boolean sub-states fire. The button index lives in lastButton.
            norm_action = self._normalise_action(action)

            current_count = dev.states.get("pressCount", 0)
            new_count = (int(current_count) % 9999) + 1

            updates.append(("lastAction",  norm_action, norm_action))
            updates.append(("lastButton",  btn,         str(btn)))
            updates.append(("pressCount",  new_count,   str(new_count)))
            updates.append(("onOffState",  True,        "Pressed"))

            if self.debug:
                log(f"{dev.name}: action={action!r} -> {norm_action!r} "
                    f"button={btn} count={new_count}")

        if "battery" in payload:
            try:
                batt = int(float(payload["battery"]))
                updates.append(("battery", batt, f"{batt}%"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_cover_state(self, dev, payload):
        """Update z2mCover device states from MQTT payload."""
        updates = []

        if "state" in payload:
            state_str = str(payload["state"]).upper()
            updates.append(("coverState", state_str.lower(), state_str.capitalize()))
            if state_str == "OPEN":
                updates.append(("onOffState", True, "Open"))
            elif state_str in ("CLOSE", "CLOSED"):
                updates.append(("onOffState", False, "Closed"))
            # STOP: leave onOffState unchanged

        if "position" in payload:
            try:
                pos = int(payload["position"])
                pos = max(0, min(100, pos))
                updates.append(("brightnessLevel", pos))
                # Sync onOffState with position if no explicit state key in this payload
                if "state" not in payload:
                    is_open = pos > 0
                    updates.append(("onOffState", is_open, "Open" if is_open else "Closed"))
            except (ValueError, TypeError):
                pass

        if "tilt" in payload:
            try:
                tilt = int(payload["tilt"])
                updates.append(("tiltAngle", tilt, f"{tilt}%"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_lock_state(self, dev, payload):
        """Update z2mLock device states from MQTT payload (v1.10.0).

        z2m locks report `state` ("LOCK"/"UNLOCK") and the richer `lock_state`
        enum (locked / unlocked / not_fully_locked). onOffState follows the
        Indigo convention: ON = locked. lock_state wins over state when both
        are present — it reflects the bolt, not the last command.
        """
        updates = []
        locked = None

        if "state" in payload:
            token = str(payload["state"]).strip().upper()
            if token in ("LOCK", "LOCKED", "ON"):
                locked = True
            elif token in ("UNLOCK", "UNLOCKED", "OFF"):
                locked = False

        if "lock_state" in payload:
            ls = str(payload["lock_state"]).strip().lower()
            updates.append(("lockState", ls))
            if ls == "locked":
                locked = True
            elif ls in ("unlocked", "not_fully_locked"):
                locked = False

        if locked is not None:
            updates.append(("onOffState", locked,
                            "Locked" if locked else "Unlocked"))

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _process_thermostat_state(self, dev, payload):
        """Update z2mThermostat (TRV) device states from MQTT payload (v1.10.0).

        Maps z2m climate fields to Indigo's native thermostat states:
        local_temperature -> temperatureInput1, current/occupied_heating_setpoint
        -> setpointHeat, system_mode -> hvacOperationMode. running_state and the
        (read-only) valve `position` land in custom states.
        """
        updates = []

        if "local_temperature" in payload:
            try:
                temp = round(float(payload["local_temperature"]), 1)
                updates.append(("temperatureInput1", temp, f"{temp} °C"))
            except (ValueError, TypeError):
                pass

        setpoint_raw = payload.get("current_heating_setpoint",
                                   payload.get("occupied_heating_setpoint"))
        if setpoint_raw is not None:
            try:
                sp = round(float(setpoint_raw), 1)
                updates.append(("setpointHeat", sp, f"{sp} °C"))
            except (ValueError, TypeError):
                pass

        if "system_mode" in payload:
            mode = str(payload["system_mode"]).strip().lower()
            hvac = {"heat": indigo.kHvacMode.Heat,
                    "auto": indigo.kHvacMode.HeatCool,
                    "off":  indigo.kHvacMode.Off}.get(mode)
            if hvac is not None:
                updates.append(("hvacOperationMode", hvac))

        if "running_state" in payload:
            updates.append(("runningState",
                            str(payload["running_state"]).strip().lower()))

        if "position" in payload:
            try:
                pos = int(payload["position"])
                updates.append(("valvePosition", pos, f"{pos} %"))
            except (ValueError, TypeError):
                pass

        if "battery" in payload:
            try:
                bat = int(payload["battery"])
                updates.append(("battery", bat, f"{bat} %"))
            except (ValueError, TypeError):
                pass

        if "linkquality" in payload:
            try:
                lq = int(payload["linkquality"])
                updates.append(("linkQuality", lq, f"{lq} / 255"))
            except (ValueError, TypeError):
                pass

        self._apply_updates(dev, updates)

    def _apply_updates(self, dev, updates):
        """
        Apply a list of state update tuples to an Indigo device.
        Each tuple is (key, value) or (key, value, uiValue).
        Errors on individual states are caught and logged at debug level.
        """
        for item in updates:
            key, value = item[0], item[1]
            ui_value   = item[2] if len(item) > 2 else None
            try:
                if ui_value is not None:
                    dev.updateStateOnServer(key, value, uiValue=ui_value)
                else:
                    dev.updateStateOnServer(key, value)
            except Exception as e:
                # Always visible (v1.9.23): a swallowed write failure is
                # silent data loss — but only ONCE per (device, key) so a
                # persistently-failing state can't spam the log every payload.
                warn_key = (dev.id, key)
                if warn_key not in self._state_write_warned:
                    self._state_write_warned.add(warn_key)
                    log(f"{dev.name}: could not update state '{key}': {e} "
                        f"(further failures for this state logged at debug "
                        f"only)", level="WARNING")
                elif self.debug:
                    log(f"{dev.name}: could not update '{key}': {e}", level="WARNING")
        if self.debug and updates:
            log(f"{dev.name}: updated {[u[0] for u in updates]}")

    # ── Auto-create helpers ───────────────────────────────────────────────────

    def _ensure_device_folder(self, name):
        """Return id of named device folder, creating it if absent."""
        for folder in indigo.devices.folders:
            if folder.name == name:
                return folder.id
        new_folder = indigo.devices.folder.create(name)
        log(f"Created device folder: '{name}'")
        return new_folder.id

    def _build_plugin_props(self, device_type_id, device_data, definition, exposes):
        """Build the pluginProps dict for a new auto-created device."""
        props = {
            "friendly_name":         device_data.get("friendly_name", ""),
            "ieee_address":          device_data.get("ieee_address", ""),
            "vendor":                definition.get("vendor", ""),
            "model":                 definition.get("model", ""),
        }

        if device_type_id == "z2mLight":
            caps = _detect_light_capabilities(exposes)
            props.update(caps)
            # Single source of truth for the native colour flags — must match
            # _apply_light_capabilities / Refresh Capabilities. SupportsColor is
            # has_color OR has_color_temp: a CT-only bulb needs it as the prereq for
            # SupportsWhiteTemperature, else Indigo silently ignores CT. The old
            # create-time logic (SupportsColor = has_color alone, and no
            # SupportsWhite) created CT-only bulbs unable to do colour temp until a
            # manual Refresh Capabilities — v1.9.3 fixed the refresh path but not
            # this create path.
            props.update(self._compute_light_native_flags(caps["has_color"],
                                                          caps["has_color_temp"]))

        elif device_type_id == "z2mContactSensor":
            caps = _detect_contact_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mOccupancySensor":
            caps = _detect_occupancy_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mWaterLeakSensor":
            caps = _detect_water_leak_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mTemperatureSensor":
            caps = _detect_temperature_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mSensor":
            caps = _detect_sensor_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mRelay":
            caps = _detect_relay_capabilities(exposes)
            props.update(caps)

        elif device_type_id == "z2mRepeater":
            caps = {}  # no sensor capabilities — availability + linkQuality only

        elif device_type_id == "z2mCover":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_tilt": "tilt" in names}
            props.update(caps)

        elif device_type_id == "z2mButton":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_battery": "battery" in names}
            props.update(caps)

        elif device_type_id == "z2mLock":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_battery": "battery" in names}
            props.update(caps)

        elif device_type_id == "z2mThermostat":
            names = {feat.get("name") for feat in _iter_features(exposes)}
            caps  = {"has_battery": "battery" in names}
            props.update(caps)
            # Some TRVs expose occupied_heating_setpoint instead of
            # current_heating_setpoint — remember which one to publish to.
            props["setpoint_key"] = ("occupied_heating_setpoint"
                                     if ("occupied_heating_setpoint" in names
                                         and "current_heating_setpoint" not in names)
                                     else "current_heating_setpoint")
            # Native thermostat behaviour flags (heat-only TRV).
            props.update({
                "NumTemperatureInputs":       1,
                "NumHumidityInputs":          0,
                "SupportsHeatSetpoint":       True,
                "SupportsCoolSetpoint":       False,
                "SupportsHvacOperationMode":  "system_mode" in names,
                "SupportsHvacFanMode":        False,
                "ShowCoolHeatEquipmentStateUI": False,
            })

        else:
            caps = {}

        props["capabilities_display"] = _build_capabilities_display(device_type_id, props)
        return props

    # ── Light capability helpers ──────────────────────────────────────────────

    def exception_handler(self, exc, log_failing_statement=False, context=""):
        """Log an exception with full traceback. When log_failing_statement is
        True, also extract the actual source line that raised from the deepest
        traceback frame — invaluable when one device out of dozens triggers a
        failure and the bare message doesn't say which line in which method
        blew up. Modelled on autolog's exception_handler pattern.
        """
        import traceback
        tb = exc.__traceback__
        last_frame = None
        while tb is not None:
            last_frame = tb
            tb = tb.tb_next
        prefix = f"{context}: " if context else ""
        log(f"{prefix}{type(exc).__name__}: {exc}", level="ERROR")
        if log_failing_statement and last_frame is not None:
            fname    = last_frame.tb_frame.f_code.co_filename
            lineno   = last_frame.tb_lineno
            funcname = last_frame.tb_frame.f_code.co_name
            try:
                # encoding="utf-8" — Indigo's open() defaults to ASCII and
                # plugin source contains em-dashes (CLAUDE.md gotcha)
                with open(fname, encoding="utf-8") as f:
                    src_line = f.readlines()[lineno - 1].strip()
            except Exception:
                src_line = "(source unavailable)"
            short = fname.rsplit("/", 1)[-1]
            log(f"  at {short}:{lineno} in {funcname}() -> {src_line}", level="ERROR")
        log(traceback.format_exc(), level="ERROR")

    def _apply_indigo_subtype(self, dev):
        """Set dev.subType so Indigo, HomeKitLink-Siri and control pages get the
        right semantic class (icon + accessory kind). Dynamic for lights (colour
        capability) and for z2mSensor catch-all (inferred from capability flags).
        Static for everything else. Skips devices without a clean SDK match
        (z2mWaterLeakSensor, z2mRepeater, z2mButton, and mixed-capability z2mSensor).
        """
        target = None
        type_id = dev.deviceTypeId

        if type_id == "z2mLight":
            has_col = dev.pluginProps.get("has_color", False)
            target = (indigo.kDimmerDeviceSubType.ColorDimmer if has_col
                      else indigo.kDimmerDeviceSubType.Dimmer)
        elif type_id == "z2mRelay":
            target = indigo.kRelayDeviceSubType.Outlet
        elif type_id == "z2mContactSensor":
            target = indigo.kSensorDeviceSubType.DoorWindow
        elif type_id == "z2mOccupancySensor":
            target = indigo.kSensorDeviceSubType.Motion
        elif type_id == "z2mTemperatureSensor":
            target = indigo.kSensorDeviceSubType.Temperature
        elif type_id == "z2mCover":
            target = indigo.kDimmerDeviceSubType.Blind
        elif type_id == "z2mSensor":
            # Backfill: devices created before the specific sensor types existed
            # are still on the catch-all but their capability flags reveal which
            # specific subType they would have got under the v1.8.0 classifier.
            # Setting subType in place keeps the deviceId intact (no trigger /
            # control page breakage) while giving HomeKitLink-Siri the right
            # accessory routing. Mixed-capability sensors get no subType.
            props        = dev.pluginProps
            has_contact  = props.get("has_contact",    False)
            has_occ      = props.get("has_occupancy",  False)
            has_leak     = props.get("has_water_leak", False)
            has_env      = (props.get("has_temperature", False)
                            or props.get("has_humidity",    False)
                            or props.get("has_pressure",    False)
                            or props.get("has_illuminance", False))
            if has_contact and not has_occ and not has_leak:
                target = indigo.kSensorDeviceSubType.DoorWindow
            elif has_occ and not has_contact and not has_leak:
                target = indigo.kSensorDeviceSubType.Motion
            elif has_env and not has_contact and not has_occ and not has_leak:
                target = indigo.kSensorDeviceSubType.Temperature

        if target is not None and dev.subType != target:
            dev.subType = target
            dev.replaceOnServer()

    @staticmethod
    def _compute_light_native_flags(has_color, has_color_temp):
        # SupportsColor must be True for any lamp with colour OR CT — it's the
        # top-level prerequisite for both SupportsRGB and SupportsWhiteTemperature.
        # A CT-only bulb still needs SupportsColor=True or Indigo silently ignores
        # SupportsWhiteTemperature.
        return {
            "SupportsColor":            has_color or has_color_temp,
            "SupportsRGB":              has_color,
            "SupportsWhite":            has_color_temp,
            "SupportsWhiteTemperature": has_color_temp,
        }

    def _apply_light_capabilities(self, dev):
        """Set Indigo color capability flags from stored pluginProps (z2mLight only)."""
        props   = dev.pluginProps
        has_col = props.get("has_color",      False)
        has_ct  = props.get("has_color_temp", False)

        # If both flags are absent pluginProps is likely empty/unreadable — skip to
        # avoid clobbering existing capability flags with False values.
        if not has_col and not has_ct:
            return

        # Always call replacePluginPropsOnServer when capability data is present.
        # Indigo only propagates native attributes to the device via this call.
        with self.props_lock:   # atomic RMW vs the other props writers
            new_props = dict(dev.pluginProps)
            new_props.update(self._compute_light_native_flags(has_col, has_ct))
            dev.replacePluginPropsOnServer(new_props)
