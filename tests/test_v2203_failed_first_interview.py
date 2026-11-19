#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2203_failed_first_interview.py
# Description: v2.20.3 - a device whose first interview fails is not created
#              from zigbee2mqtt's stand-in definition (which made it a
#              repeater for good); it is created once the interview succeeds.
# Author:      CliveS & Claude Fable 5.2
# Date:        19-11-2026
# Version:     1.0
"""Live case, 18-11-2026: a Third Reality 3RSPU01080Z plug joined, its first
interview failed, and zigbee2mqtt published it with a definition holding no
model and only link quality. The plugin created it as z2mRepeater 23 seconds
after it joined; the interview succeeded two and a half minutes later, too
late, because a device's type cannot be changed."""

import pytest

from z2m_detection import _interview_unfinished

RELAY = [{"type": "switch",
          "features": [{"name": "state", "type": "binary", "access": 7}]}]
STAND_IN = {"exposes": [{"name": "linkquality", "type": "numeric", "access": 1}],
            "model": "", "vendor": ""}
EXISTING = {"ieee_address": "0x1", "friendly_name": "Existing", "type": "Router",
            "interview_completed": True, "interview_state": "SUCCESSFUL",
            "definition": {"exposes": [], "model": "X", "vendor": "V"}}


def _plug(**over):
    d = {"ieee_address": "0x2", "friendly_name": "0x2", "type": "Router",
         "interview_completed": True, "interview_state": "SUCCESSFUL",
         "definition": {"exposes": RELAY, "model": "3RSPU01080Z",
                        "vendor": "Third Reality"}}
    d.update(over)
    return d


@pytest.fixture
def house(plugin, monkeypatch):
    import indigo
    from indigo_stub import DeviceShim
    monkeypatch.setattr(indigo, "device", DeviceShim(indigo.devices), raising=False)
    plugin.bridge_devices = {"0x1": dict(EXISTING, _mqtt_prefix="zigbee2mqtt")}
    plugin._process_bridge_devices([EXISTING], prefix="zigbee2mqtt")
    return plugin


def _made(name="0x2"):
    import indigo
    return [d for d in indigo.devices if d.name == name]


@pytest.mark.parametrize("data, unfinished", [
    ({"definition": None}, True),
    ({"definition": STAND_IN, "interview_completed": False}, True),
    ({"definition": STAND_IN, "interview_state": "FAILED"}, True),
    ({"definition": STAND_IN, "interview_state": "IN_PROGRESS"}, True),
    ({"definition": STAND_IN, "interview_state": "PENDING"}, True),
    ({"definition": STAND_IN, "interview_completed": True,
      "interview_state": "SUCCESSFUL"}, False),
    ({"definition": STAND_IN}, False),          # older zigbee2mqtt: no flags
])
def test_what_counts_as_unfinished(data, unfinished):
    assert _interview_unfinished(data) is unfinished


def test_a_failed_first_interview_does_not_make_a_repeater(house):
    house._process_bridge_devices(
        [EXISTING, _plug(definition=STAND_IN, interview_completed=False,
                         interview_state="FAILED")],
        prefix="zigbee2mqtt")
    assert not _made(), "must wait for the interview"


def test_it_is_created_as_a_relay_once_the_interview_succeeds(house):
    house._process_bridge_devices(
        [EXISTING, _plug(definition=STAND_IN, interview_completed=False,
                         interview_state="FAILED")],
        prefix="zigbee2mqtt")
    house._process_bridge_devices([EXISTING, _plug()], prefix="zigbee2mqtt")
    made = _made()
    assert len(made) == 1
    assert made[0].deviceTypeId == "z2mRelay"


def test_a_device_that_arrives_complete_is_still_created_at_once(house):
    house._process_bridge_devices([EXISTING, _plug()], prefix="zigbee2mqtt")
    assert _made() and _made()[0].deviceTypeId == "z2mRelay"
