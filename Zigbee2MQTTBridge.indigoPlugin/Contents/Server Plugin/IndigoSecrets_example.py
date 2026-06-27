#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    IndigoSecrets_example.py
# Description: Template for IndigoSecrets.py — the MQTT credentials this plugin
#              (Zigbee2MQTT Bridge) reads. Copy to IndigoSecrets.py and fill in
#              your values. This bundled copy lists ONLY the keys Zigbee2MQTT
#              Bridge uses; the full multi-plugin master template lives at the
#              shared path below.
# Author:      CliveS & Claude Opus 4.8
# Date:        27-06-2026
# Version:     2.0

# ============================================================
# HOW THIS FILE WORKS
# ============================================================
#
# Plugins read credentials from a single shared file at this version-stable path
# (it never changes across Indigo upgrades):
#
#     /Library/Application Support/Perceptive Automation/IndigoSecrets.py
#
# Each plugin does:
#     sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
#     from IndigoSecrets import MQTT_BROKER   # etc.
# (NEVER "from secrets import ..." — that shadows Python's stdlib secrets module,
#  which is exactly why the file is named IndigoSecrets, not secrets.)
#
# If IndigoSecrets.py is missing, or a key is absent, this plugin falls back to
# the values entered in its own dialog (Plugins -> Zigbee2MQTT Bridge ->
# Configure). A missing single key never blanks the others (per-key try/except).
#
# FIRST-TIME SETUP
# Copy this file into:
#     /Library/Application Support/Perceptive Automation/
# then RENAME the copy from  IndigoSecrets_example.py  to  IndigoSecrets.py
# and fill in the MQTT values below. If you run other CliveS plugins too, use the
# full master template (every plugin's keys) from any of their bundles instead,
# so a single IndigoSecrets.py serves them all.
#
# SECURITY
# IndigoSecrets.py is listed in .gitignore on every plugin repo and is NEVER
# committed to git. Keep a backup in a password manager.
#
# ============================================================

# ============================
# MQTT broker (Mosquitto / zigbee2mqtt)
# Required by: Zigbee2MQTT Bridge
# ============================
MQTT_BROKER   = "192.168.1.10"   # your broker's LAN IP or hostname
MQTT_PORT     = 1883
MQTT_USERNAME = ""               # leave blank if the broker allows anonymous
MQTT_PASSWORD = ""
