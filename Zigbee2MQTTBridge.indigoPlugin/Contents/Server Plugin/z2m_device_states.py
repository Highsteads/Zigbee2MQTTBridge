#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_device_states.py
# Description: Device state declaration and the dynamic-state machinery: which states a
#              device type gets, the sanitiser and type inference behind captured
#              payload fields, and getDeviceStateList.
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

from z2m_constants import (
    _BUTTON_ACTION_VALUES, _RESERVED_STATE_NAMES, _handled_keys_for,
)
from z2m_helpers import _format_last_seen


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


class DeviceStatesMixin:
    """See the file header above."""


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
