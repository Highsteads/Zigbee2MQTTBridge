#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_scenes.py
# Description: Zigbee scenes (v2.15.0) — recall, store and remove the scenes
#              kept in the bulbs themselves, for a group or a single light.
#
#              A Zigbee scene lives in each member's own memory: "Evening" is
#              every bulb's brightness and colour, recalled by all of them at
#              once from one broadcast. Home Assistant and ioBroker offer this;
#              with groups in 2.14.0 it became worth having here.
#
#              Facts it rests on, read from zigbee2mqtt 2.14.2 and
#              zigbee-herdsman-converters (toZigbee.ts scene_*):
#              * Sent to the entity's own /set: {"scene_recall": n},
#                {"scene_store": {"ID": n, "name": "..."}}, {"scene_remove": n}.
#                IDs are 0-255, and 0 is reserved on a single device (group 0),
#                so this plugin uses 1-255 throughout.
#              * The stored scenes are listed per group in bridge/groups
#                (`scenes`) and per endpoint in bridge/devices
#                (`endpoints.<ep>.scenes`), each {id, name}; zigbee2mqtt
#                republishes both when a scene changes (bridge.ts
#                onScenesChanged), so the lists here stay current by
#                themselves.
#              * A /set has no reply topic. Success shows as the scene
#                appearing in, or leaving, the next list.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import z2m_helpers
from z2m_groups import is_group

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


SCENE_IDS = range(1, 256)
NEW_SCENE = "new"


class ScenesMixin:
    """See the file header above."""

    def _scenes_for(self, dev):
        """[(id, name)] stored for this group or light, by id."""
        found = {}
        if is_group(dev):
            prefix = self._device_prefix(dev)
            try:
                entry = (self.bridge_groups.get(prefix) or {}).get(int(dev.ownerProps.get("group_id")))
            except (TypeError, ValueError):
                entry = None
            lists = [(entry or {}).get("scenes") or []]
        else:
            ieee = (dev.ownerProps.get("ieee_address") or "").strip()
            data = self.bridge_devices.get(ieee) if ieee else None
            endpoints = (data or {}).get("endpoints") or {}
            lists = [(ep or {}).get("scenes") or [] for ep in endpoints.values()
                     if isinstance(ep, dict)]
        for scenes in lists:
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                try:
                    sid = int(scene.get("id"))
                except (TypeError, ValueError):
                    continue
                found.setdefault(sid, str(scene.get("name") or f"Scene {sid}"))
        return sorted(found.items())

    def _scene_device(self, target_id):
        try:
            return indigo.devices[int(target_id)]
        except (KeyError, TypeError, ValueError):
            return None

    # ── Dialog lists ─────────────────────────────────────────────────────────

    def list_device_scenes(self, filter="", valuesDict=None, typeId="", targetId=0):
        """The scenes stored for the device the action is for. filter="store"
        adds "A new scene" at the top."""
        dev = self._scene_device(targetId)
        rows = [(str(sid), f"{name} ({sid})") for sid, name in
                (self._scenes_for(dev) if dev is not None else [])]
        if filter == "store":
            return [(NEW_SCENE, "A new scene")] + rows
        return rows or [("none", "-- no scenes stored yet --")]

    # ── Actions ──────────────────────────────────────────────────────────────

    def _scene_target(self, action, dev):
        if dev is None:
            dev = self._scene_device(getattr(action, "deviceId", 0))
        if dev is None:
            log("Zigbee scene: no device given — nothing sent.", level="WARNING")
            return None, None
        fname = dev.pluginProps.get("friendly_name", "")
        return dev, f"{self._device_prefix(dev)}/{fname}/set"

    @staticmethod
    def _scene_number(value):
        try:
            sid = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return sid if sid in SCENE_IDS else None

    def action_recall_scene(self, action, dev=None, callerWaitingForResult=None):
        dev, topic = self._scene_target(action, dev)
        if dev is None:
            return
        sid = self._scene_number(action.props.get("scene"))
        if sid is None:
            log(f"{dev.name}: Recall Zigbee Scene has no scene chosen — nothing sent.",
                level="WARNING")
            return
        name = dict(self._scenes_for(dev)).get(sid, f"scene {sid}")
        self._publish_cmd(topic, {"scene_recall": sid}, dev, f"recall {name}")

    def action_store_scene(self, action, dev=None, callerWaitingForResult=None):
        """Store what the lights are doing now as a scene.

        "A new scene" takes the lowest free number. Overwriting keeps the
        scene's name unless a new one is given.
        """
        dev, topic = self._scene_target(action, dev)
        if dev is None:
            return
        stored = dict(self._scenes_for(dev))
        choice = str(action.props.get("scene") or NEW_SCENE)
        if choice == NEW_SCENE:
            sid = next((n for n in SCENE_IDS if n not in stored), None)
            if sid is None:
                log(f"{dev.name}: every scene number is in use — remove one first.",
                    level="WARNING")
                return
        else:
            sid = self._scene_number(choice)
            if sid is None:
                log(f"{dev.name}: Store Zigbee Scene has no scene chosen — nothing "
                    f"sent.", level="WARNING")
                return
        name = str(action.props.get("sceneName") or "").strip() \
            or stored.get(sid) or f"Scene {sid}"
        self._publish_cmd(topic, {"scene_store": {"ID": sid, "name": name}}, dev,
                          f"store scene {name} as {sid}")

    def action_remove_scene(self, action, dev=None, callerWaitingForResult=None):
        dev, topic = self._scene_target(action, dev)
        if dev is None:
            return
        sid = self._scene_number(action.props.get("scene"))
        if sid is None:
            log(f"{dev.name}: Remove Zigbee Scene has no scene chosen — nothing sent.",
                level="WARNING")
            return
        name = dict(self._scenes_for(dev)).get(sid, f"scene {sid}")
        self._publish_cmd(topic, {"scene_remove": sid}, dev, f"remove {name}")

    def _validate_scene_action(self, valuesDict, typeId, errors):
        """Called from validateActionConfigUi for the three scene actions."""
        choice = str(valuesDict.get("scene") or "")
        if typeId == "storeScene":
            if choice != NEW_SCENE and self._scene_number(choice) is None:
                errors["scene"] = "Choose a scene to overwrite, or A new scene."
            if len(str(valuesDict.get("sceneName") or "")) > 64:
                errors["sceneName"] = "Keep the name to 64 characters or fewer."
        elif self._scene_number(choice) is None:
            errors["scene"] = "Choose a scene. If the list is empty, store one first."

    def _scene_summary(self, dev):
        """The stored scenes as a person reads them: "Evening (1), Reading (2)"."""
        return ", ".join(f"{name} ({sid})" for sid, name in self._scenes_for(dev))
