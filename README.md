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

- Indigo 2023.2 or later (Python 3.11+)
- zigbee2mqtt running and accessible via MQTT
- MQTT credentials in `IndigoSecrets.py` OR in PluginConfig (v1.9.6+)

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

**Keys read by Zigbee2MQTTBridge:**

```python
MQTT_BROKER   = "192.168.x.x"   # hostname or IP of your MQTT broker
MQTT_PORT     = 1883
MQTT_USERNAME = ""              # blank = no auth
MQTT_PASSWORD = ""
```

All four have matching PluginConfig fields under **Plugins → Zigbee2MQTT
Bridge → Configure** *(fallback added in v1.9.6)*.

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]` so
events can be correlated tightly with other CliveS plugins (Device Activity
Monitor uses the same convention).

To turn the prefix off (or back on) at any time:

**Plugins → Zigbee2MQTT Bridge → Toggle Timestamps in Log (on/off)**

The setting is stored in `pluginPrefs` (`timestampEnabled`) and persists across
restarts. Defaults to ON.

## Version history

- **1.9.7** (23-05-2026) — millisecond timestamp `[HH:MM:SS.mmm]` prefix on every `self.logger` line via `plugin_utils.install_timestamp_filter()`; new "Toggle Timestamps in Log" menu item.
- **1.9.6** (23-05-2026) — PluginConfig fallback for MQTT broker/port/username/password (secrets-policy: users without `IndigoSecrets.py` can now configure entirely via the GUI). Legacy `secrets.py` wording updated to `IndigoSecrets.py` in labels and error messages.
- **1.9.5** — current release feature set.

## Usage

1. Enable the plugin in Indigo (Plugins > Manage Plugins)
2. Set the **Topic Prefix** in plugin preferences (default: `zigbee2mqtt`)
3. Wait for `MQTT connected` and `Bridge device cache updated: N devices` in the event log
4. Go to **Plugins > Zigbee2MQTT Bridge > Discover & Create Devices**
5. All your Zigbee devices appear in Indigo under the **Zigbee2MQTT** folder

Re-run **Discover & Create Devices** any time you add new Zigbee devices.

## Acknowledgements

With thanks to **Autolog** for the [zigbee2mqtt plugin](https://github.com/autolog/zigbee2mqtt) — studying its design showed us the way to build this plugin, and the project would not exist without that prior work.

## Authors

CliveS & Claude Opus 4.7
