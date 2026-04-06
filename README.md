# Zigbee2MQTT Bridge

An [Indigo](https://www.indigodomo.com/) plugin that connects directly to a [zigbee2mqtt](https://www.zigbee2mqtt.io/) MQTT broker, auto-discovers all Zigbee device types, and creates matching Indigo devices — all organised in a **Zigbee2MQTT** device folder.

## Features

- Connects to zigbee2mqtt via MQTT (paho-mqtt)
- Auto-detects device type from zigbee2mqtt `exposes` array
- **Discover & Create Devices** menu item: one click creates all Indigo devices, no manual setup
- Four Indigo device types:
  - **Z2M Light** (dimmer) — bulbs, LED strips; brightness + optional colour/CCT
  - **Z2M Relay** (relay) — switches, outlets, plugs; on/off + optional power/energy
  - **Z2M Sensor** (sensor) — contact, motion, temperature, humidity, water leak, illuminance, battery
  - **Z2M Cover** (dimmer) — blinds, shutters; position 0-100% maps to Indigo brightness
- Availability and link quality tracked per device
- Handles friendly names containing `/` (sub-room naming)
- All devices created in a **Zigbee2MQTT** device folder

## Requirements

- Indigo 2025.1 or later
- zigbee2mqtt running and accessible via MQTT
- MQTT credentials in `/Library/Application Support/Perceptive Automation/secrets.py`

## Installation

1. Go to the [Releases](../../releases) page and download `Zigbee2MQTTBridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Zigbee2MQTTBridge.indigoPlugin`
3. Double-click `Zigbee2MQTTBridge.indigoPlugin` — Indigo will install it automatically

## Credentials

This plugin reads MQTT credentials from the shared secrets file:

```
/Library/Application Support/Perceptive Automation/secrets.py
```

Copy `secrets_example.py` (inside the bundle) to that path and fill in your details:

```python
MQTT_BROKER   = "192.168.1.x"    # IP of your MQTT broker
MQTT_PORT     = 1883
MQTT_USERNAME = ""                # leave blank if no auth
MQTT_PASSWORD = ""
```

If you already have these keys set for HueMQTT, no changes are needed.

## Usage

1. Enable the plugin in Indigo (Plugins > Manage Plugins)
2. Set the **Topic Prefix** in plugin preferences (default: `zigbee2mqtt`)
3. Wait for `MQTT connected` and `Bridge device cache updated: N devices` in the event log
4. Go to **Plugins > Zigbee2MQTT Bridge > Discover & Create Devices**
5. All your Zigbee devices appear in Indigo under the **Zigbee2MQTT** folder

Re-run **Discover & Create Devices** any time you add new Zigbee devices.

## Authors

CliveS & Claude Sonnet 4.6
