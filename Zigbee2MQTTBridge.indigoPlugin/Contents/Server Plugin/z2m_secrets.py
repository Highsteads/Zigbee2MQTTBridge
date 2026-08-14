#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_secrets.py
# Description: The four MQTT credentials, read from the shared IndigoSecrets.py
#              master with a per-key try/except so one missing key cannot blank
#              the other three. PluginConfig is the fallback when a value is
#              absent here — that resolution lives in z2m_mqtt.py, the only
#              consumer.
#
#              Extracted in v2.2.0 so the MQTT mixin can read the credentials
#              without importing plugin.py, which would be circular.
#
#              NOTE the module cache. IndigoSecrets is an ordinary Python
#              module, so each plugin host keeps whatever was on disk when it
#              first imported it and never re-reads the file. Editing
#              IndigoSecrets.py therefore changes nothing here until the plugin
#              restarts — a rotated key is not live on save.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import sys as _sys

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")

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
