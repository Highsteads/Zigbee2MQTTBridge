#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_v2160_ota_schedule.py
# Description: v2.16.0 — scheduled firmware updates, cancelling and stopping
#              them, and release notes.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0
"""From zigbee2mqtt 2.14.2 otaUpdate.ts: bridge/request/device/ota_update/
schedule | unschedule | update/abort, each answered on bridge/response/... with
the transaction echoed; the device's `update` object gains state "scheduled"
and carries latest_release_notes. A failed scheduled attempt returns to
"scheduled"; an abort returns to "available"."""

import indigo  # stub
from indigo_stub import FakeTrigger

PREFIX = "zigbee2mqtt"
OTA = f"{PREFIX}/bridge/request/device/ota_update"


def _dev(plugin, make_device, state="available", dev_id=2601):
    dev = make_device(dev_id, "Porch Sensor", "z2mContactSensor",
                      pluginProps={"friendly_name": "Porch", "ieee_address": "0xpor",
                                   "mqtt_prefix": PREFIX},
                      states={"updateState": state})
    plugin.bridge_devices["0xpor"] = {"ieee_address": "0xpor", "friendly_name": "Porch",
                                      "_mqtt_prefix": PREFIX,
                                      "definition": {"supports_ota": True, "exposes": []}}
    plugin.ieee_map["0xpor"] = dev.id
    plugin.friendly_name_map[(PREFIX, "Porch")] = dev.id
    return dev


def _published(plugin, monkeypatch):
    out = []
    monkeypatch.setattr(plugin, "_publish", lambda t, p: out.append((t, p)) or True)
    return out


def _update(state, **extra):
    return dict({"state": state, "installed_version": 1, "latest_version": 2}, **extra)


def _events(plugin):
    indigo.trigger.reset()
    for i, event in enumerate(("otaUpdateAvailable", "otaUpdateFinished", "otaUpdateFailed")):
        plugin.triggerStartProcessing(FakeTrigger(i + 1, event))
    return lambda: [t.pluginTypeId for t in indigo.trigger.executed]


# ── scheduling ───────────────────────────────────────────────────────────────

def test_next_time_schedules_instead_of_updating(plugin, make_device, make_action,
                                                 monkeypatch):
    dev = _dev(plugin, make_device)
    out = _published(plugin, monkeypatch)
    plugin.action_update_firmware(make_action(props={"when": "next"}), dev)
    plugin.menu_update_firmware({"targetDevice": str(dev.id), "when": "next"})
    assert out == [(f"{OTA}/schedule", {"id": "0xpor", "transaction": "0xpor"})] * 2


def test_an_action_saved_before_the_choice_still_updates_now(plugin, make_device,
                                                             make_action, monkeypatch):
    dev = _dev(plugin, make_device)
    out = _published(plugin, monkeypatch)
    plugin.action_update_firmware(make_action(props={}), dev)
    assert out == [(f"{OTA}/update", {"id": "0xpor", "transaction": "0xpor"})]


def test_a_scheduled_device_is_not_started_again(plugin, make_device, monkeypatch, logs):
    dev = _dev(plugin, make_device, state="scheduled")
    out = _published(plugin, monkeypatch)
    plugin._start_firmware_update(dev, when="now")
    assert out == []
    assert any("already scheduled" in m for m in logs.at("WARNING"))


def test_scheduled_still_counts_as_an_update_waiting(plugin, make_device):
    events = _events(plugin)
    dev = _dev(plugin, make_device)
    plugin._process_update_object(dev, _update("scheduled"))
    assert dev.states["updateState"] == "scheduled"
    assert dev.states["updateAvailable"] is True
    assert events() == []


# ── what the state changes mean ──────────────────────────────────────────────

def test_a_scheduled_update_that_runs_and_finishes(plugin, make_device, logs):
    events = _events(plugin)
    dev = _dev(plugin, make_device, state="scheduled")
    plugin._process_update_object(dev, _update("updating", progress=5))
    assert any("scheduled firmware update has started" in m for m in logs.event_messages)
    plugin._process_update_object(dev, _update("idle", installed_version=2))
    assert events() == ["otaUpdateFinished"]


def test_a_failed_attempt_goes_back_on_the_schedule_quietly(plugin, make_device, logs):
    events = _events(plugin)
    dev = _dev(plugin, make_device, state="updating")
    plugin._process_update_object(dev, _update("scheduled"))
    assert events() == [], "it will be tried again — the update is not over"
    assert any("will try again" in m for m in logs.at("WARNING"))


def test_a_stop_we_asked_for_is_not_a_failure(plugin, make_device, monkeypatch, logs):
    events = _events(plugin)
    dev = _dev(plugin, make_device, state="updating")
    out = _published(plugin, monkeypatch)
    plugin._cancel_firmware_update(dev)
    assert out == [(f"{OTA}/update/abort", {"id": "0xpor", "transaction": "0xpor"})]
    plugin._process_update_object(dev, _update("available"))
    assert events() == [], "no failure, and no fresh 'available' either"
    assert any("stopped, as asked" in m for m in logs.event_messages)
    assert dev.id not in plugin._ota_aborting


def test_a_failure_we_did_not_ask_for_still_fires(plugin, make_device):
    events = _events(plugin)
    dev = _dev(plugin, make_device, state="updating")
    plugin._process_update_object(dev, _update("available"))
    assert events() == ["otaUpdateFailed"]


# ── cancelling ───────────────────────────────────────────────────────────────

def test_cancelling_a_scheduled_update_unschedules_it(plugin, make_device, monkeypatch):
    dev = _dev(plugin, make_device, state="scheduled")
    out = _published(plugin, monkeypatch)
    plugin.menu_cancel_firmware({"targetDevice": str(dev.id)})
    assert out == [(f"{OTA}/unschedule", {"id": "0xpor", "transaction": "0xpor"})]


def test_nothing_to_cancel_sends_nothing(plugin, make_device, make_action, monkeypatch, logs):
    dev = _dev(plugin, make_device, state="idle")
    out = _published(plugin, monkeypatch)
    plugin.action_cancel_firmware(make_action(), dev)
    assert out == []
    assert any("nothing to cancel" in m for m in logs.at("WARNING"))


def test_the_cancel_list_shows_scheduled_and_installing(plugin, make_device):
    _dev(plugin, make_device, state="scheduled", dev_id=2602)
    assert plugin.list_devices_updating_or_scheduled() == [("2602", "Porch Sensor  (scheduled)")]


# ── replies ──────────────────────────────────────────────────────────────────

def _reply(plugin, tail, status="ok", error=None):
    payload = {"status": status, "data": {"id": "0xpor"}, "transaction": "0xpor"}
    if error:
        payload["error"] = error
        payload["data"] = {}
    plugin._process_message(f"{PREFIX}/bridge/response/device/ota_update/{tail}", payload)


def test_an_abort_reply_is_not_a_finished_update(plugin, make_device, logs):
    events = _events(plugin)
    _dev(plugin, make_device, state="updating")
    _reply(plugin, "update/abort")
    assert events() == []
    assert not any("finished" in m for m in logs.event_messages)


def test_schedule_and_unschedule_replies_are_reported(plugin, make_device, logs):
    _dev(plugin, make_device)
    _reply(plugin, "schedule")
    _reply(plugin, "unschedule")
    text = "\n".join(logs.event_messages)
    assert "firmware update scheduled" in text
    assert "scheduled firmware update is cancelled" in text


def test_a_refused_schedule_is_an_error_but_not_a_failed_update(plugin, make_device, logs):
    events = _events(plugin)
    _dev(plugin, make_device)
    _reply(plugin, "schedule", status="error", error="Device 'Porch' does not support OTA updates")
    assert events() == []
    assert any("scheduling the update did not complete" in m for m in logs.at("ERROR"))


# ── release notes ────────────────────────────────────────────────────────────

def test_release_notes_are_logged_once_and_shortened(plugin, make_device, logs):
    dev = _dev(plugin, make_device, state="idle")
    notes = "Fixes pairing.\n" + "x" * 400
    plugin._process_update_object(dev, _update("available", latest_release_notes=notes))
    plugin._process_update_object(dev, _update("available", latest_release_notes=notes))
    lines = [m for m in logs.event_messages if "release notes" in m]
    assert len(lines) == 1
    assert "Fixes pairing. xxx" in lines[0] and lines[0].endswith("...")
    assert len(lines[0]) < 400


def test_the_firmware_report_carries_the_notes(plugin, make_device, logs):
    dev = _dev(plugin, make_device, state="idle")
    plugin._process_update_object(dev, _update("available", latest_release_notes="Better range"))
    plugin.report_firmware_status()
    assert any("release notes: Better range" in m for m in logs.event_messages)
