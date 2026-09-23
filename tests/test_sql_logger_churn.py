#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    test_sql_logger_churn.py
# Description: v2.8.3. lastSeen, linkQuality and messagesPerSec change on almost
#              every Zigbee message, so SQL Logger stored ~29,000 history rows a
#              day that held nothing else. deviceStartComm adds them to the
#              device's sqlLoggerIgnoreStates shared prop without overriding the
#              user; coordinators are left alone.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0


def _start(plugin, make_device, monkeypatch, dev_id=900, **kw):
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: None)
    dev = make_device(dev_id, "Hall Sensor", "z2mContactSensor",
                      pluginProps={"friendly_name": "Hall Sensor", "ieee_address": "0xab"}, **kw)
    plugin.deviceStartComm(dev)
    return dev


def test_the_merge_keeps_the_user_and_never_narrows_star(plugin_mod):
    assert plugin_mod.merge_sql_logger_ignore("") == "lastSeen, linkQuality, messagesPerSec"
    assert plugin_mod.merge_sql_logger_ignore("battery") == \
        "battery, lastSeen, linkQuality, messagesPerSec"
    assert plugin_mod.merge_sql_logger_ignore("LINKQUALITY,lastseen, MessagesPerSec") is None
    assert plugin_mod.merge_sql_logger_ignore("*") is None


def test_start_comm_writes_the_list_once(plugin, make_device, monkeypatch):
    dev = _start(plugin, make_device, monkeypatch)
    plugin.deviceStartComm(dev)
    assert dev.sharedProps["sqlLoggerIgnoreStates"] == "lastSeen, linkQuality, messagesPerSec"
    assert dev.shared_writes == 1


def test_a_users_star_is_left_alone(plugin, make_device, monkeypatch):
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: None)
    dev = make_device(901, "Quiet", "z2mContactSensor",
                      pluginProps={"friendly_name": "Quiet", "ieee_address": "0xac"})
    dev.sharedProps = {"sqlLoggerIgnoreStates": "*"}
    plugin.deviceStartComm(dev)
    assert dev.shared_writes == 0


def test_a_coordinator_is_left_alone(plugin, make_device):
    dev = make_device(902, "Coordinator", "z2mCoordinator",
                      pluginProps={"mqtt_prefix": "zigbee2mqtt"})
    plugin.deviceStartComm(dev)
    assert dev.shared_writes == 0


def test_a_failed_write_does_not_stop_the_device(plugin, make_device, monkeypatch):
    monkeypatch.setattr(plugin, "_schedule_state_request", lambda *a, **k: None)
    dev = make_device(903, "Stubborn", "z2mContactSensor",
                      pluginProps={"friendly_name": "Stubborn", "ieee_address": "0xad"})

    def boom(props):
        raise RuntimeError("server said no")
    dev.replaceSharedPropsOnServer = boom
    plugin.deviceStartComm(dev)
    assert plugin.friendly_name_map[("zigbee2mqtt", "Stubborn")] == dev.id
