#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_clean_disconnect_real_paho.py
# Description: The plugin really does say goodbye to the broker on stop and on
#              Mac sleep — proved with REAL paho against a tiny fake broker on
#              localhost, not with a stand-in.
#
#              Review finding 7 (01-11-2026) suspected the opposite:
#              _stop_mqtt_locked calls loop_stop() BEFORE disconnect(), so the
#              DISCONNECT packet looked as if it might never be sent. Measured
#              on paho 2.1.0, it is: once loop_stop() has ended the network
#              thread, paho's _packet_queue writes the packet straight to the
#              socket, then closes it and runs on_disconnect. No plugin change
#              was needed; this test keeps it that way if the code or the paho
#              version changes.
#
#              The suite is otherwise paho-free (CI does not install it), so
#              this module SKIPS when paho 2.x is not importable.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import queue
import socket
import threading
import time

import pytest

paho = pytest.importorskip("paho.mqtt.client")
if not hasattr(paho, "CallbackAPIVersion"):
    pytest.skip("paho 1.x installed; the plugin needs 2.x", allow_module_level=True)

CONNACK_ACCEPTED = b"\x20\x02\x00\x00"
DISCONNECT       = b"\xe0\x00"


class FakeBroker:
    """Accept one client, accept its CONNECT, record everything after it."""

    def __init__(self):
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port     = self._srv.getsockname()[1]
        self.received = b""
        self.closed   = False      # the client closed its end of the socket
        self._thread  = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self._srv.settimeout(5)
        try:
            conn, _ = self._srv.accept()
        except socket.timeout:
            return
        with conn:
            conn.settimeout(5)
            conn.recv(1024)                       # CONNECT
            conn.sendall(CONNACK_ACCEPTED)
            try:
                while True:
                    data = conn.recv(1024)
                    if not data:
                        self.closed = True
                        break
                    self.received += data
            except socket.timeout:
                pass
        self._srv.close()

    def wait(self):
        self._thread.join(timeout=10)


@pytest.fixture
def connected(plugin, mqtt_mod, secrets_mod, monkeypatch):
    """The plugin connected, through its own _start_mqtt, to a fake broker."""
    monkeypatch.setattr(mqtt_mod, "mqtt", paho)          # real paho, whatever the import found
    monkeypatch.setattr(secrets_mod, "MQTT_BROKER", "")
    monkeypatch.setattr(secrets_mod, "MQTT_PORT", None)
    monkeypatch.setattr(secrets_mod, "MQTT_USERNAME", "")
    monkeypatch.setattr(secrets_mod, "MQTT_PASSWORD", "")
    broker = FakeBroker()
    plugin.pluginPrefs["mqtt_broker"] = "127.0.0.1"
    plugin.pluginPrefs["mqtt_port"]   = str(broker.port)
    plugin.msg_queue = queue.Queue()
    plugin._start_mqtt()
    deadline = time.time() + 5
    while not plugin.mqtt_connected and time.time() < deadline:
        time.sleep(0.02)
    assert plugin.mqtt_connected, "the plugin never connected to the fake broker"
    yield plugin, broker
    plugin._stop_mqtt()                                  # tidy up if a test failed


def _queued(plugin, topic):
    """Payloads queued for the main thread under `topic`."""
    found = []
    while not plugin.msg_queue.empty():
        item = plugin.msg_queue.get_nowait()
        if item[0] == topic:
            found.append(item[1])
    return found


def test_stop_sends_disconnect_and_closes_the_socket(connected):
    plugin, broker = connected
    plugin._stop_mqtt()
    broker.wait()
    assert DISCONNECT in broker.received, "the broker never got a DISCONNECT"
    assert broker.closed, "the socket was left open"
    assert plugin.mqtt_client is None
    assert plugin.mqtt_connected is False


def test_sleep_disconnects_cleanly(connected):
    plugin, broker = connected
    plugin.prepare_to_sleep()
    broker.wait()
    assert DISCONNECT in broker.received
    assert broker.closed


def test_a_clean_stop_is_reported_as_clean(connected):
    """on_disconnect runs with a success reason, so the main thread logs
    'disconnected cleanly' rather than the 'unexpectedly' WARNING."""
    plugin, broker = connected
    plugin._stop_mqtt()
    broker.wait()
    reports = _queued(plugin, "__disconnected__")
    assert reports, "on_disconnect never ran"
    assert reports[-1]["rc"] == 0, reports


def test_stop_does_not_hang(connected):
    plugin, broker = connected
    t0 = time.time()
    plugin._stop_mqtt()
    assert time.time() - t0 < 3, "stopping blocked the Indigo thread"
