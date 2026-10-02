#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_settings.py
# Description: Managed device settings — the firmware settings that live on the
#              Zigbee device itself (sensitivity, delays, reporting intervals),
#              held as intent in pluginProps, offered in the device's own config
#              dialog, and re-asserted when the device drifts away from them.
#
#              This exists because those settings live on the SENSOR, not in
#              Indigo, so nothing owned them and nothing noticed when they
#              changed. Two FP300s were deliberately set to AI-adaptive OFF on
#              24-Jun-2026 and were back ON by 06-Jul — inside a burst of
#              power_outage_count increments, i.e. a battery change restoring
#              the firmware defaults. They stayed wrong for FOUR WEEKS while
#              bedroom presence fragmented every night, with nothing logged.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import json

import z2m_helpers

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


# Access is a bitmask on every expose: 1 = published in state, 2 = settable via
# /set, 4 = gettable via /get.
ACCESS_PUBLISHED = 1
ACCESS_SET       = 2
ACCESS_GET       = 4

# Prefix for the stored intent. Namespaced so it can never collide with the
# plugin's own props or with a device's own captured fields.
SETTING_PREFIX = "z2mset_"

# Joins a composite child's path into its stored name: color_options +
# execute_if_off -> color_options__execute_if_off (2.11.0).
PATH_JOIN = "__"


class SettingsMixin:
    """Managed device settings — see the file header above."""

    # ── Discovery ────────────────────────────────────────────────────────────

    @staticmethod
    def _iter_settable_exposes(exposes, path=(), parent_label=""):
        """Yield every expose that is a genuine, manageable SETTING.

        The rule is access & SET *and* access & PUBLISHED. Both halves matter:

        * Without SET we could not write it.
        * Without PUBLISHED we could never read back what the device actually
          has, so we could not tell drift from agreement — and a setting we
          cannot verify is one we would re-assert blindly for ever.

        That second half is also what keeps us away from the write-only
        entries, which are COMMANDS wearing a setting's clothes:
        `restart_device`, `spatial_learning`, `identify`, and the FP300's
        twenty-four `detection_range_N` flags all carry access=2 alone.
        Re-asserting `restart_device` whenever a device reconnected would
        reboot it in a loop, so this distinction is load-bearing, not tidiness.
        """
        for feature in exposes or []:
            if feature.get("features"):
                # A light / switch / climate WRAPPER only groups its features:
                # they are top-level properties and are sent as they are. A
                # COMPOSITE with a property of its own is a parent: its
                # features travel inside it ({"color_options":
                # {"execute_if_off": true}}). Flattening both the same way sent
                # a composite's children bare, which the device ignores, and
                # missed their drift (2.11.0).
                inner_path, inner_label = path, parent_label
                if feature.get("type") == "composite" and feature.get("property"):
                    inner_path = path + (feature["property"],)
                    inner_label = (feature.get("label")
                                   or feature["property"].replace("_", " ").title())
                yield from SettingsMixin._iter_settable_exposes(
                    feature["features"], inner_path, inner_label)
                continue
            access = feature.get("access", 0) or 0
            if not (access & ACCESS_SET and access & ACCESS_PUBLISHED):
                continue
            if not feature.get("property"):
                continue
            if feature.get("type") not in ("binary", "numeric", "enum", "text"):
                continue
            if path:
                feature = dict(feature, _path=path + (feature["property"],),
                               _parent_label=parent_label)
            yield feature

    def _managed_settings_for(self, dev):
        """The settable exposes for this device, from the live bridge cache."""
        props = dev.ownerProps
        ieee = (props.get("ieee_address") or "").strip()
        entry = self.bridge_devices.get(ieee) if ieee else None
        if not entry:
            return []
        definition = entry.get("definition") or {}
        return list(self._iter_settable_exposes(definition.get("exposes") or []))

    # ── Stored intent ────────────────────────────────────────────────────────

    @staticmethod
    def _setting_key(prop):
        return SETTING_PREFIX + prop

    @staticmethod
    def _spec_path(spec):
        """Where the setting lives in a payload: its parents, then itself."""
        return tuple(spec.get("_path") or (spec["property"],))

    @staticmethod
    def _spec_name(spec):
        """The name the intent is stored under. A top-level setting keeps
        its own property, as before 2.11.0, so nothing already stored moves; a
        composite's child joins its path with a double underscore."""
        return PATH_JOIN.join(SettingsMixin._spec_path(spec))

    @staticmethod
    def _value_at(container, path):
        """(found, value) for a path through nested dicts."""
        value = container
        for step in path:
            if not isinstance(value, dict) or step not in value:
                return False, None
            value = value[step]
        return True, value

    @staticmethod
    def _nest(specs, values):
        """Build the /set payload from {spec name: value}."""
        out = {}
        for name, value in values.items():
            path = SettingsMixin._spec_path(specs[name])
            node = out
            for step in path[:-1]:
                node = node.setdefault(step, {})
            node[path[-1]] = value
        return out

    def _reported_setting(self, dev, spec):
        """What the device last reported for this setting, or None.

        A composite arrives as one state holding the whole object, which the
        raw-field capture stores as JSON text, so it is read back from that.
        """
        path = self._spec_path(spec)
        top = dev.states.get(self._sanitise_state_key(path[0]))
        if len(path) == 1:
            return top
        if isinstance(top, str):
            try:
                top = json.loads(top)
            except ValueError:
                return None
        found, value = self._value_at(top, path[1:])
        return value if found else None

    @staticmethod
    def _intended_settings(props):
        """Every setting the user has pinned, as {z2m property: raw string}.

        An empty value means 'not managed' — the user cleared the field, so we
        stop having an opinion about it rather than pinning it to blank.
        """
        out = {}
        for key, value in (props or {}).items():
            if not key.startswith(SETTING_PREFIX):
                continue
            if value is None or str(value).strip() == "":
                continue
            out[key[len(SETTING_PREFIX):]] = str(value).strip()
        return out

    @staticmethod
    def _coerce_setting(spec, raw):
        """Turn a stored string back into the type zigbee2mqtt expects.

        Everything comes out of a ConfigUI as a string — including a checkbox,
        which arrives as "true"/"false" — so this is the boundary where the
        payload gets its real type back. Returns None when the value cannot be
        made sense of, and the caller then leaves the setting alone rather than
        publishing a guess.
        """
        if raw is None:
            return None
        text = str(raw).strip()
        if text == "":
            return None
        kind = spec.get("type")
        if kind == "binary":
            low = text.lower()
            if low in ("true", "1", "yes", "on"):
                return spec.get("value_on", True)
            if low in ("false", "0", "no", "off"):
                return spec.get("value_off", False)
            return None
        if kind == "numeric":
            # A numeric expose may declare named PRESETS, and a preset's value
            # can sit outside the ordinary range on purpose: a Hue bulb's
            # color_temp_startup runs 153-500 but `previous` is 65535, meaning
            # "come back at the colour it had". Accept the name or the value
            # and let a preset past the range check (2.12.0).
            presets = SettingsMixin._presets(spec)
            if text.lower() in presets:
                return presets[text.lower()]
            try:
                number = float(text)
            except (TypeError, ValueError):
                return None
            if number in presets.values():
                return int(number) if number == int(number) else number
            lo, hi = spec.get("value_min"), spec.get("value_max")
            if lo is not None and number < lo:
                return None
            if hi is not None and number > hi:
                return None
            return int(number) if number == int(number) else number
        if kind == "enum":
            values = spec.get("values") or []
            # Match case-insensitively but publish the EXACT token z2m declared —
            # these are matched literally at the far end.
            for value in values:
                if str(value).lower() == text.lower():
                    return value
            return None
        return text   # text

    @staticmethod
    def _presets(spec):
        """{lower-case preset name: value} for a numeric expose."""
        out = {}
        for preset in spec.get("presets") or []:
            if not isinstance(preset, dict):
                continue
            name, value = preset.get("name"), preset.get("value")
            if name and isinstance(value, (int, float)) and not isinstance(value, bool):
                out[str(name).lower()] = value
        return out

    @staticmethod
    def _binary_as_bool(spec, value):
        """Reduce a binary value to a real bool, or None if it makes no sense.

        A binary expose declares its OWN on/off tokens, and devices genuinely
        disagree about what they are — the FP300 publishes
        `ai_sensitivity_adaptive` as the strings "ON"/"OFF" while publishing
        `led_disabled_night` as real booleans, on the same device.

        So NEVER use Python truthiness here. `bool("OFF")` is True, because a
        non-empty string is truthy — which made the intended value "OFF" and a
        reported False disagree for ever, publishing the setting again on every
        payload that mentioned it. On a battery sensor that is a write storm.
        Live-hit 15-08-2026 minutes after the feature shipped; the tests missed
        it because the fixture omitted value_on/value_off, so it exercised the
        one shape that happens to work.
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().lower()
        if text == str(spec.get("value_on", "\0")).strip().lower():
            return True
        if text == str(spec.get("value_off", "\0")).strip().lower():
            return False
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        return None

    @staticmethod
    def _compare_values(spec, intended, reported):
        """True (agrees), False (genuinely differs), or None (cannot tell).

        Three answers rather than two, because the two callers want opposite
        things from "cannot tell": a drift check must stay its hand, while a
        dialog save should go ahead — the user has just asked for that value.
        Collapsing unknown into either one gets the other caller wrong, and the
        wrong one is a write storm at a battery device.
        """
        if reported is None or intended is None:
            return None
        kind = spec.get("type")
        if kind == "numeric":
            try:
                return abs(float(intended) - float(reported)) < 1e-9
            except (TypeError, ValueError):
                return None
        if kind == "binary":
            want = SettingsMixin._binary_as_bool(spec, intended)
            have = SettingsMixin._binary_as_bool(spec, reported)
            if want is None or have is None:
                return None
            return want == have
        return str(intended).lower() == str(reported).lower()

    @staticmethod
    def _values_agree(spec, intended, reported):
        """True only when the device DEFINITELY holds the intended value.

        Both sides are reduced to a common form first, because they arrive in
        different ones: the intended value has been coerced into whatever token
        the device wants to be SENT, while the reported value is whatever the
        device chose to PUBLISH, and for binaries those are often not the same
        type at all.

        Unknown is not agreement, so this is safe for "should I send it?" —
        but do NOT invert it to mean drift. Use _compare_values for that.
        """
        return SettingsMixin._compare_values(spec, intended, reported) is True

    # ── Drift detection and re-assertion ─────────────────────────────────────

    def _check_setting_drift(self, dev, payload):
        """Compare a fresh payload against the pinned settings and re-assert.

        Called on the back of an INBOUND message, which is the whole trick: a
        battery device only accepts a write while it is awake, and zigbee2mqtt
        does not reliably queue one for a sleeping sensor. A device that has
        just published is provably awake, so this is the one moment a write is
        certain to land — no polling, no guessing, no queue.
        """
        if not isinstance(payload, dict):
            return
        intended = self._intended_settings(dev.ownerProps)
        if not intended:
            return

        specs = {self._spec_name(s): s for s in self._managed_settings_for(dev)}
        if not specs:
            return

        drifted = {}
        for prop, raw_intent in intended.items():
            spec = specs.get(prop)
            if spec is None:
                continue          # no longer offered by this device's definition
            found, reported = self._value_at(payload, self._spec_path(spec))
            if not found:
                continue          # this payload says nothing about it
            if reported is None:
                # Present in the payload but null — zigbee2mqtt publishes these
                # after a restart. That is "the device has not told us", NOT
                # "the device disagrees", and treating it as drift would fire a
                # write off the back of no information. Inaction is cheap here:
                # the real value arrives with the next payload.
                continue
            want = self._coerce_setting(spec, raw_intent)
            if want is None:
                continue          # unusable stored value — never publish a guess
            if self._compare_values(spec, want, reported) is not False:
                # Agrees, or cannot be compared. Only a definite difference is
                # drift — anything else and we stay our hand rather than write
                # to a device off the back of a value we did not understand.
                continue
            drifted[prop] = (want, reported)

        if not drifted:
            return

        for prop, (want, found) in sorted(drifted.items()):
            log(f"{dev.name}: '{prop}' is {found!r} but was set to {want!r} — "
                f"re-applying", level="WARNING")
        self._publish_settings(
            dev, self._nest(specs, {p: v for p, (v, _) in drifted.items()}),
            reason="drift")

    def _publish_settings(self, dev, values, reason=""):
        """Publish a settings payload to the device's /set topic."""
        if not values:
            return False
        fname = (dev.ownerProps.get("friendly_name") or "").strip()
        if not fname:
            return False
        prefix = self._device_prefix(dev)
        topic = f"{prefix}/{fname}/set"
        if self._publish(topic, values):
            detail = f" ({reason})" if reason else ""
            log(f"{dev.name}: applied {json.dumps(values, sort_keys=True)}{detail}")
            return True
        log(f"{dev.name}: could not apply {sorted(values)} — the broker did not "
            f"accept the message", level="WARNING")
        return False

    # ── Device config dialog ─────────────────────────────────────────────────

    def getDeviceConfigUiXml(self, typeId, devId):
        """Append a Device Settings section to the type's static ConfigUI.

        Overrides an UNDOCUMENTED PluginBase hook (plugin_base.py:1240, whose
        default returns the static ConfigUIRawXml). Any failure here falls
        straight back to that default — a device that cannot open its own
        config dialog would be far worse than one without this section.
        """
        base = super().getDeviceConfigUiXml(typeId, devId)
        try:
            dev = indigo.devices[devId]
        except Exception:
            return base
        try:
            specs = self._managed_settings_for(dev)
            if not specs:
                return base
            fields = self._build_settings_fields(dev, specs)
            if not fields:
                return base
            if "</ConfigUI>" not in (base or ""):
                return base
            return base.replace("</ConfigUI>", fields + "\n</ConfigUI>", 1)
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"settings ConfigUI for '{dev.name}'")
            return base

    def _build_settings_fields(self, dev, specs):
        """Generate the ConfigUI XML for this device's settable exposes."""
        from xml.sax.saxutils import escape, quoteattr

        parts = [
            '\n    <Field id="z2mSettingsSep" type="separator"/>',
            '    <Field id="z2mSettingsLabel" type="label" fontColor="darkgray">',
            '        <Label>Device Settings — stored here and re-applied if the '
            'device loses them (a battery change resets some sensors to their '
            'defaults). Leave a field blank to stop managing it.</Label>',
            '    </Field>',
        ]
        for spec in specs:
            prop = spec["property"]
            field_id = self._setting_key(self._spec_name(spec))
            label = spec.get("label") or prop.replace("_", " ").title()
            if spec.get("_parent_label"):
                label = f"{spec['_parent_label']}: {label}"
            desc = (spec.get("description") or "").strip()
            # What the device currently reports, so the dialog opens showing
            # reality rather than an empty box the user must guess at.
            current = self._reported_setting(dev, spec)
            hint = f" Currently reporting: {current}." if current not in (None, "") else ""
            kind = spec.get("type")

            if kind == "enum":
                parts.append(f'    <Field id={quoteattr(field_id)} type="menu" defaultValue="">')
                parts.append(f'        <Label>{escape(label)}:</Label>')
                parts.append('        <List>')
                parts.append('            <Option value="">-- not managed --</Option>')
                for value in spec.get("values") or []:
                    parts.append(f'            <Option value={quoteattr(str(value))}>'
                                 f'{escape(str(value))}</Option>')
                parts.append('        </List>')
            elif kind == "binary":
                # A menu rather than a checkbox: a checkbox has no third state,
                # so it could not express "not managed" and would silently pin
                # every binary setting to False the moment the dialog was saved.
                parts.append(f'    <Field id={quoteattr(field_id)} type="menu" defaultValue="">')
                parts.append(f'        <Label>{escape(label)}:</Label>')
                parts.append('        <List>')
                parts.append('            <Option value="">-- not managed --</Option>')
                parts.append('            <Option value="true">On</Option>')
                parts.append('            <Option value="false">Off</Option>')
                parts.append('        </List>')
            else:
                parts.append(f'    <Field id={quoteattr(field_id)} type="textfield" defaultValue="">')
                parts.append(f'        <Label>{escape(label)}:</Label>')
                if kind == "numeric":
                    lo, hi = spec.get("value_min"), spec.get("value_max")
                    presets = self._presets(spec)
                    if presets:
                        desc = (f"Or type one of: {', '.join(presets)}. "
                                f"{desc}").strip()
                        named = [n for n, v in presets.items() if v == current]
                        if named:
                            hint = f" Currently reporting: {current} ({named[0]})."
                    if lo is not None or hi is not None:
                        desc = f"Range {lo} to {hi}. {desc}".strip()

            if desc or hint:
                parts.append(f'        <Description>{escape((desc + hint).strip())}</Description>')
            parts.append('    </Field>')
        return "\n".join(parts)

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        """Drop the settings the user left blank before Indigo stores them.

        A generated dialog offers a field per settable expose — two dozen on an
        FP300 — and Indigo stores every one, so leaving them alone buries the
        handful that mean something under a pile of empty props. Blank already
        means "no opinion", so removing them changes nothing except how
        readable the device's properties are.
        """
        for key in [k for k in list(valuesDict.keys())
                    if k.startswith(SETTING_PREFIX)
                    and str(valuesDict.get(k) or "").strip() == ""]:
            del valuesDict[key]
        return (True, valuesDict)

    def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, devId):
        """Publish any setting the user changed, once the dialog is saved."""
        # Chain first: more than one mixin hooks this, and whichever appears
        # earlier in the MRO would otherwise silently swallow the others.
        try:
            super().closedDeviceConfigUi(valuesDict, userCancelled, typeId, devId)
        except AttributeError:
            pass
        if userCancelled:
            return
        try:
            dev = indigo.devices[devId]
        except Exception:
            return
        try:
            specs = {self._spec_name(s): s for s in self._managed_settings_for(dev)}
            if not specs:
                return
            to_send = {}
            for prop, spec in specs.items():
                raw = valuesDict.get(self._setting_key(prop))
                if raw is None or str(raw).strip() == "":
                    continue      # not managed — say nothing to the device
                want = self._coerce_setting(spec, raw)
                if want is None:
                    log(f"{dev.name}: '{prop}' value {raw!r} is not valid for this "
                        f"setting — not applied", level="WARNING")
                    continue
                reported = self._reported_setting(dev, spec)
                if self._values_agree(spec, want, reported):
                    continue      # already correct, no need to disturb the device
                to_send[prop] = want
            if to_send:
                self._publish_settings(dev, self._nest(specs, to_send),
                                       reason="saved from the device dialog")
        except Exception as e:
            self.exception_handler(e, log_failing_statement=True,
                                   context=f"applying settings for '{dev.name}'")
