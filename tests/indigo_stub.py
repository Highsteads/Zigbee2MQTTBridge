#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    indigo_stub.py
# Description: Minimal stand-in for the `indigo` module used inside Indigo's
#              embedded Python interpreter. Lets plugin.py import outside the
#              Indigo host so the pure-helper functions and the static / mock-able
#              instance methods can be unit-tested. NOT a runtime replacement —
#              it raises if a method is called that the tests have not explicitly
#              stubbed.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026
# Version:     1.0

from __future__ import annotations

import sys
import types


# ── enum-like containers ─────────────────────────────────────────────────────

class _Enum:
    """Tiny enum stand-in — every attribute access returns a unique sentinel.

    Real Indigo enums are opaque objects; tests only care that the same constant
    compares equal to itself. We back them with a stable string token so
    ``indigo.kSensorAction.RequestStatus`` always returns the same value across
    accesses, and so test failures print something meaningful.
    """

    def __init__(self, namespace: str):
        self._namespace = namespace
        self._values: dict[str, str] = {}

    def __getattr__(self, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._values:
            self._values[name] = f"{self._namespace}.{name}"
        return self._values[name]


kDeviceAction        = _Enum("kDeviceAction")
kDimmerRelayAction   = _Enum("kDimmerRelayAction")
kSensorAction        = _Enum("kSensorAction")
kUniversalAction     = _Enum("kUniversalAction")
kThermostatAction    = _Enum("kThermostatAction")
kDimmerDeviceSubType = _Enum("kDimmerDeviceSubType")
kSensorDeviceSubType = _Enum("kSensorDeviceSubType")
kRelayDeviceSubType  = _Enum("kRelayDeviceSubType")
kStateImageSel       = _Enum("kStateImageSel")
kProtocol            = _Enum("kProtocol")
kHvacMode            = _Enum("kHvacMode")


# ── server-side log / Dict ────────────────────────────────────────────────────

class _Server:
    def __init__(self):
        self.log_lines: list[tuple[str, str]] = []
        # Attributes that plugin_utils.log_startup_banner reads from indigo.server.
        self.version    = "2025.2.0"
        self.apiVersion = "3.4"

    def log(self, message: str, level: str = "INFO", type: str | None = None):  # noqa: A002
        self.log_lines.append((level, str(message)))

    def getInstallFolderPath(self):
        return "/tmp/indigo-stub"

    # No-ops for things plugin code calls but tests don't exercise.
    def getReflectorURL(self):
        return ""


server = _Server()


class Dict(dict):
    """Indigo's `indigo.Dict` is dict-compatible; tests just need a real dict
    that survives the iteration patterns plugin code uses."""


# ── PluginBase ───────────────────────────────────────────────────────────────

class PluginBase:
    """Minimal PluginBase. Subclasses only get what tests need."""

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        self.pluginId          = pluginId
        self.pluginDisplayName = pluginDisplayName
        self.pluginVersion     = pluginVersion
        self.pluginPrefs       = pluginPrefs if pluginPrefs is not None else Dict()
        self.debug             = False

        # logger used by plugin_utils.install_timestamp_filter; the timestamp
        # filter test isn't a target here, so a no-op stand-in is enough.
        class _Logger:
            def addFilter(self, *_args, **_kwargs): pass
            def removeFilter(self, *_args, **_kwargs): pass
            def info(self, *_a, **_k): pass
            def debug(self, *_a, **_k): pass
            def warning(self, *_a, **_k): pass
            def error(self, *_a, **_k): pass

        self.logger = _Logger()

    # plugin.py overrides most of these; PluginBase shouldn't need to do real work.
    # PluginBase's dynamic-ConfigUI hook. The real one (plugin_base.py:1240)
    # returns the type's static ConfigUIRawXml; the stub returns a minimal
    # well-formed document so a mixin overriding it has something to append to.
    device_config_ui_xml = "<?xml version=\"1.0\"?>\n<ConfigUI>\n</ConfigUI>"

    def getDeviceConfigUiXml(self, typeId, devId):
        return self.device_config_ui_xml

    def closedDeviceConfigUi(self, values_dict, user_cancelled, type_id, dev_id):
        return None

    def deviceUpdated(self, *_args, **_kwargs): pass
    def stateListOrDisplayStateIdChanged(self, *_args, **_kwargs): pass

    def getDeviceStateList(self, dev):
        """Return the device's statically-declared states as [{'Key': id}, ...].
        Tests set dev.static_state_keys to control what Devices.xml would declare.
        A fresh list each call (the real one returns a live ref; plugin.py copies
        it before appending dynamic states)."""
        keys = getattr(dev, "static_state_keys", None) or []
        return [{"Key": k} for k in keys]

    # State-dict builders plugin.py's getDeviceStateList override uses to declare
    # dynamic states. Real Indigo returns richer dicts; the 'Key'/'Type' subset is
    # what the tests assert on.
    @staticmethod
    def _state_dict(key, trigger_label, label, type_name):
        return {"Key": key, "TriggerLabel": trigger_label, "StateLabel": label,
                "Type": type_name}

    def getDeviceStateDictForBoolTrueFalseType(self, key, trigger_label, label):
        return self._state_dict(key, trigger_label, label, "BoolTrueFalse")

    def getDeviceStateDictForBoolOnOffType(self, key, trigger_label, label):
        return self._state_dict(key, trigger_label, label, "BoolOnOff")

    def getDeviceStateDictForIntegerType(self, key, trigger_label, label):
        return self._state_dict(key, trigger_label, label, "Integer")

    def getDeviceStateDictForRealType(self, key, trigger_label, label):
        return self._state_dict(key, trigger_label, label, "Real")

    def getDeviceStateDictForStringType(self, key, trigger_label, label):
        return self._state_dict(key, trigger_label, label, "String")

    # Lifecycle hooks the plugin chains via super() — no-ops are enough for tests.
    def sleep(self, *_args, **_kwargs): pass
    def wake_up(self, *_args, **_kwargs): pass
    wakeUp = wake_up
    def prepare_to_sleep(self, *_args, **_kwargs): pass
    prepareToSleep = prepare_to_sleep


# ── Device registry ──────────────────────────────────────────────────────────

class FakeDevice:
    """Sufficient for the plugin's read paths and to capture state writes.

    Mimics the relevant subset of indigo.Device for tests. State writes go into
    ``self.states`` and ``self.state_writes`` (a list of every write so order-
    sensitive tests can assert on it).
    """

    def __init__(self, id, name, deviceTypeId, pluginProps=None, states=None,
                 onState=False, brightness=0, sensorValue=None,
                 displayStateId="onOffState", subType="", static_state_keys=None,
                 folderId=0, enabled=True):
        self.id              = id
        self.name            = name
        self.deviceTypeId    = deviceTypeId
        self.folderId        = folderId
        self.enabled         = enabled
        self.static_state_keys = static_state_keys or []   # Devices.xml static states
        self.pluginProps     = pluginProps or {}
        self.ownerProps      = self.pluginProps           # alias used by plugin code
        self.states          = states or {}
        self.state_writes    = []                         # list of (key, value, ui)
        self.onState         = onState
        self.brightness      = brightness
        self.sensorValue     = sensorValue
        self.displayStateId  = displayStateId
        self.subType         = subType
        self.pluginId        = "com.clives.indigoplugin.z2mbridge"
        self.supportsColor   = bool(pluginProps and pluginProps.get("has_color"))
        self.supportsWhiteTemperature = bool(pluginProps and pluginProps.get("has_color_temp"))
        self.errorState      = ""
        self.error_writes    = []                         # every setErrorStateOnServer call

    # Native attributes exist ONLY while the matching Supports* property is set
    # — Indigo's conditional inheritance, the same rule that governs
    # sensorValue and onOffState.  Modelling it here is the point: a stub that
    # accepted these writes unconditionally would pass whether or not the
    # plugin ever sets the property, which is exactly the bug worth catching.
    _CONDITIONAL_NATIVE_STATES = {
        "batteryLevel":     "SupportsBatteryLevel",
        "curEnergyLevel":   "SupportsEnergyMeterCurPower",
        "accumEnergyTotal": "SupportsEnergyMeter",
    }

    # ── server-side methods plugin.py calls on the device object ─────────────

    def refreshFromServer(self):
        return None

    def setErrorStateOnServer(self, value):
        # Real Indigo turns the state column red; None clears it.
        self.errorState = "" if value is None else str(value)
        self.error_writes.append(value)

    def updateStateOnServer(self, key, value, uiValue=None, **_kwargs):
        # Optional strictness (v1.9.22, stub-drift fix): real Indigo REJECTS a
        # write to a state key that isn't declared. Tests opt in by setting
        # dev.strict_states = True after declaring static_state_keys (and any
        # dynamic keys via pluginProps seenDynamicKeys) — the permissive default
        # keeps the existing suite behaviour.
        gate = self._CONDITIONAL_NATIVE_STATES.get(key)
        if gate is not None and not self.pluginProps.get(gate, False):
            # Enforced whether or not strict_states is on: this one is not
            # about XML declaration, it is Indigo refusing a native attribute
            # the device has not been given.
            raise KeyError(f"native state '{key}' does not exist on "
                           f"{self.name} — {gate} is not set")
        if getattr(self, "strict_states", False):
            declared = set(self.static_state_keys)
            declared.update(k for k in self.pluginProps.get(
                "seenDynamicKeys", "").split(",") if k)
            declared.update({"onOffState", "brightnessLevel", "sensorValue",
                             "redLevel", "greenLevel", "blueLevel",
                             "whiteTemperature"})   # native class states
            declared.update(self._CONDITIONAL_NATIVE_STATES)   # gated above
            if key not in declared:
                raise KeyError(f"state key '{key}' not declared on {self.name} "
                               f"(real Indigo rejects this write)")
        self.states[key]    = value
        self.state_writes.append((key, value, uiValue))
        if key == "onOffState":
            self.onState = bool(value)

    def updateStatesOnServer(self, updates):
        for u in updates:
            self.updateStateOnServer(u["key"], u["value"], u.get("uiValue"))

    def replacePluginPropsOnServer(self, new_props):
        # Indigo REPLACES (not merges) — match real behaviour.
        self.pluginProps = dict(new_props)
        self.ownerProps  = self.pluginProps

    def replaceOnServer(self):
        return None

    def stateListOrDisplayStateIdChanged(self):
        return None


class _DeviceRegistry:
    def __init__(self):
        self._by_id: dict[int, FakeDevice] = {}
        self.folders = _FolderCollection()

    def add(self, dev: FakeDevice):
        self._by_id[dev.id] = dev

    def __getitem__(self, key):
        if isinstance(key, str):
            for d in self._by_id.values():
                if d.name == key:
                    return d
            raise KeyError(key)
        return self._by_id[key]

    def __contains__(self, key):
        # Live-verified on real Indigo: `<id> in indigo.devices` returns False
        # for an unknown id rather than raising. Without this the `in` would
        # fall back to __iter__ and compare an int against device OBJECTS,
        # which is False even for ids that DO exist — a silently wrong answer.
        if isinstance(key, int):
            return key in self._by_id
        return any(d is key or getattr(d, "name", None) == key
                   for d in self._by_id.values())

    def __iter__(self):
        return iter(self._by_id.values())

    def iter(self, *_args, **_kwargs):
        return iter(self._by_id.values())


class _Folder:
    def __init__(self, id, name):
        self.id   = id
        self.name = name


class _FolderCollection(list):
    def __init__(self):
        super().__init__()
        self._next_id = 1

    def create(self, name):
        self._next_id += 1
        f = _Folder(self._next_id, name)
        self.append(f)
        return f

    @property
    def folder(self):
        return self


devices = _DeviceRegistry()


# A second registry-like shim so `indigo.devices.folder.create(...)` works.
class _FolderShim:
    @staticmethod
    def create(name):
        return devices.folders.create(name)


devices.folder = _FolderShim()


# Variable registry — unused but referenced by some plugin paths in passing.
class _Vars:
    def __init__(self): self._by_id = {}
    def __getitem__(self, k): return self._by_id[k]


variables = _Vars()


# Trigger execution stub.
class FakeTrigger:
    """Minimal stand-in for an indigo trigger of ours (v2.1.0 plugin events).

    Only `id`, `name` and `pluginTypeId` are read by the plugin — the last is
    what decides which triggers a raised event executes.
    """

    def __init__(self, id, pluginTypeId, name=None):
        self.id           = id
        self.pluginTypeId = pluginTypeId
        self.name         = name or f"trigger-{id}"


class _TriggerShim:
    """Records executions so tests can assert which triggers fired, and — just
    as importantly — that the wrong ones did not."""

    def __init__(self):
        self.executed = []

    def execute(self, trigger):
        self.executed.append(trigger)

    def reset(self):
        self.executed.clear()


trigger = _TriggerShim()


# indigo.device (singular) namespace — create/delete, backed by the registry.
# Tests that need isolation should monkeypatch indigo.device with a fresh
# DeviceShim(devices) rather than a bare Mock (a Mock left on the shared module
# leaks into later tests — seen with an early reclassify test).
class DeviceShim:
    def __init__(self, registry):
        self._registry = registry
        self._next_id = 900000
        self.groups = {}

    def create(self, protocol=None, name="", pluginId="", deviceTypeId="",
               folder=0, props=None, **_kwargs):
        self._next_id += 1
        dev = FakeDevice(id=self._next_id, name=name, deviceTypeId=deviceTypeId,
                         pluginProps=dict(props or {}), folderId=folder)
        self._registry.add(dev)
        return dev

    def groupWithDevice(self, dev_id, target_id=None):
        """Records the grouping. Real Indigo makes the OLDEST member the root
        regardless of argument order, so tests assert on membership only."""
        self.groups.setdefault(target_id, set()).add(dev_id)

    def ungroupDevice(self, dev):
        dev_id = getattr(dev, "id", dev)
        for members in self.groups.values():
            members.discard(dev_id)

    def getGroupList(self, dev_id):
        for root, members in self.groups.items():
            if dev_id == root or dev_id in members:
                return [root] + sorted(members)
        return [dev_id]

    def delete(self, dev):
        dev_id = getattr(dev, "id", dev)
        self._registry._by_id.pop(dev_id, None)


device = DeviceShim(devices)


# ── Module installation helper ───────────────────────────────────────────────

def install():
    """Install this stub as `indigo` in sys.modules. Call from conftest.py
    BEFORE importing plugin.py."""
    mod = types.ModuleType("indigo")
    mod.PluginBase           = PluginBase
    mod.Dict                 = Dict
    mod.server               = server
    mod.devices              = devices
    mod.device               = device
    mod.variables            = variables
    mod.trigger              = trigger

    mod.kDeviceAction        = kDeviceAction
    mod.kDimmerRelayAction   = kDimmerRelayAction
    mod.kSensorAction        = kSensorAction
    mod.kUniversalAction     = kUniversalAction
    mod.kThermostatAction    = kThermostatAction
    mod.kDimmerDeviceSubType = kDimmerDeviceSubType
    mod.kSensorDeviceSubType = kSensorDeviceSubType
    mod.kRelayDeviceSubType  = kRelayDeviceSubType
    mod.kStateImageSel       = kStateImageSel
    mod.kProtocol            = kProtocol
    mod.kHvacMode            = kHvacMode

    sys.modules["indigo"] = mod
    return mod
