# Zigbee2MQTT Bridge

An [Indigo](https://www.indigodomo.com/) plugin that connects directly to a [zigbee2mqtt](https://www.zigbee2mqtt.io/) MQTT broker, auto-discovers all Zigbee device types, and creates matching Indigo devices — all organised in a **Zigbee2MQTT** device folder.

## Features

- Connects to zigbee2mqtt via MQTT (paho-mqtt)
- Auto-detects device type from zigbee2mqtt `exposes` array
- **Discover & Create Devices** menu item: one click creates all Indigo devices, no manual setup
- Six Indigo device types:
  - **Z2M Light** (dimmer) — bulbs, LED strips; brightness + optional colour/CCT
  - **Z2M Relay** (relay) — switches, outlets, plugs; on/off + optional power/energy
  - **Z2M Sensor** (sensor) — contact, motion, temperature, humidity, water leak, illuminance, battery
  - **Z2M Cover** (dimmer) — blinds, shutters; position 0-100% maps to Indigo brightness
  - **Z2M Repeater** (switch) — Zigbee signal repeaters (SLZB, SMLIGHT); link quality + availability
  - **Z2M Button / Scene** (sensor) — button/scene controllers; lastAction, pressCount, lastButton states
- Availability and link quality tracked per device
- Handles friendly names containing `/` (sub-room naming)
- All devices created in a **Zigbee2MQTT** device folder

## Requirements

- Indigo 2025.1 or later
- zigbee2mqtt running and accessible via MQTT
- MQTT credentials in `/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

## Installation

1. Go to the [Releases](../../releases) page and download `Zigbee2MQTTBridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Zigbee2MQTTBridge.indigoPlugin`
3. Double-click `Zigbee2MQTTBridge.indigoPlugin` — Indigo will install it automatically

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin (along with all CliveS Indigo plugins) reads sensitive values from
a shared master credentials file at:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you do not have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` from
the plugin bundle to that location and fill in your values. Or skip
`IndigoSecrets.py` entirely and enter values via the plugin's configuration
dialog — `IndigoSecrets.py` wins over the dialog when both are set.

If a required value is set in NEITHER source the plugin logs an ERROR
pointing the user to either fill in the matching field or add the key to
`IndigoSecrets.py`.
## Usage

1. Enable the plugin in Indigo (Plugins > Manage Plugins)
2. Set the **Topic Prefix** in plugin preferences (default: `zigbee2mqtt`)
3. Wait for `MQTT connected` and `Bridge device cache updated: N devices` in the event log
4. Go to **Plugins > Zigbee2MQTT Bridge > Discover & Create Devices**
5. All your Zigbee devices appear in Indigo under the **Zigbee2MQTT** folder

Re-run **Discover & Create Devices** any time you add new Zigbee devices.

## Authors

CliveS & Claude Sonnet 4.6
