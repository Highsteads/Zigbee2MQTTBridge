#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    IndigoSecrets_example.py
# Description: Template for IndigoSecrets.py, trimmed to the four MQTT settings
#              this plugin reads. Copy it to IndigoSecrets.py and fill in your
#              values. IndigoSecrets.py lives at:
#                  /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#              It is NEVER committed to git. Keep a backup in a password manager.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     2.0

# ============================================================
# HOW THIS FILE WORKS
# ============================================================
#
# IndigoSecrets.py is one file of settings shared by several CliveS Indigo
# plugins, at a path that does not change when Indigo is upgraded:
#
#     /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#
# Zigbee2MQTT Bridge reads only the four MQTT lines below. Each is read on its
# own, so a missing line never blanks the others. Any line that is missing or
# left blank ("") is taken from Plugins -> Zigbee2MQTT Bridge -> Configure
# instead, and the port falls back to 1883 only when neither gives one.
#
# If you already have an IndigoSecrets.py for another plugin, add these four
# lines to it rather than replacing it.
#
# The plugin reads the file when it starts, so restart the plugin after
# changing it.
#
# ============================================================

# ============================
# MQTT
# Required by: Zigbee2MQTT Bridge (broker details)
# Leave a value blank ("") to use the plugin's own Configure window for it —
# a placeholder value here would WIN over the dialog (this file is read first).
# ============================
MQTT_BROKER   = ""          # e.g. "192.168.1.10"
MQTT_PORT     = ""          # e.g. 1883 — blank uses the Configure window's Broker Port
MQTT_USERNAME = ""
MQTT_PASSWORD = ""
