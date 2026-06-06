# Zigbee2MQTT Bridge

An [Indigo](https://www.indigodomo.com/) plugin that connects directly to a [zigbee2mqtt](https://www.zigbee2mqtt.io/) MQTT broker, auto-discovers all Zigbee device types, and creates matching Indigo devices — all organised in a **Zigbee2MQTT** device folder.

## Features

- Connects directly to the zigbee2mqtt MQTT broker (paho-mqtt) — no extra bridge in between
- Auto-detects the right Indigo device type from each device's zigbee2mqtt `exposes` definition
- **Discover & Create Devices** menu item: one click creates every Indigo device, no manual setup
- Device types created:
  - **Z2M Light** (dimmer) — bulbs, LED strips and Hue, with brightness plus optional colour / colour-temperature
  - **Z2M Relay** (relay) — switches, outlets and plugs, with on/off plus optional power / energy
  - **Z2M Cover** (dimmer) — blinds and shutters, with position 0-100% mapped to Indigo brightness, plus tilt
  - **Z2M Repeater** — Zigbee routers and coordinators in repeater mode (SLZB, SMLIGHT), with link quality and availability
  - **Z2M Button / Scene** — button and scene controllers. The `lastAction` state is an Indigo enumeration, so you get a boolean sub-state per action (`lastAction.single`, `.double`, `.hold`, and so on) and can trigger on a specific press straight from the Triggers UI, with no string compare
  - **Z2M Sensor family** — a generic sensor plus auto-classified Contact, Occupancy / presence, Water-leak and Temperature / Humidity types, each given the matching Indigo subType so HomeKit and friends route them correctly
  - **Z2M Coordinator** — one device per MQTT bridge, tracking the Z2M version, coordinator type, permit-join, network and device count
- **Every payload field is imported.** Beyond the semantic states above, any other field a device reports is captured as a dynamically-declared state of the correct Indigo type (boolean / integer / real / string), so nothing is thrown away
- **Self-healing MQTT** — an application-level liveness backstop rebuilds the connection if it falls silent, catching the half-open-socket wedge that paho's own auto-reconnect can miss. MQTT also disconnects and reconnects cleanly across Mac sleep and wake
- Multiple zigbee2mqtt instances supported (for example a main bridge plus a separate garage coordinator)
- Availability and link quality tracked per device, friendly names containing `/` handled, everything organised in a **Zigbee2MQTT** device folder

## Requirements

- Indigo 2023.2 or later (developed and run on Indigo 2025.2 / Python 3.13)
- zigbee2mqtt running and reachable over MQTT
- MQTT credentials in `IndigoSecrets.py` OR entered in PluginConfig (fallback added in v1.9.6)
- Bundled Python dependencies, installed automatically on first run: `paho-mqtt`, `colormath`

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
the plugin bundle to `/Library/Application Support/Perceptive Automation/` and rename it to `IndigoSecrets.py`, then fill in your values. Or skip
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

- **1.9.15** (06-06-2026) — review fixes: corrected the universal-action handler name so Send Status Request works on every path, stopped combo devices (a dimmer or switch that also sends scene actions) being mistakenly rebuilt as buttons, and a malformed payload field is now skipped on its own rather than dropping the whole update.
- **1.9.14** (29-05-2026) — self-healing MQTT: an application-level liveness backstop rebuilds the connection after a silent half-open socket that paho's own auto-reconnect can miss.
- **1.9.13** (28-05-2026) — dynamic state-type inference: each captured payload field is declared with the correct Indigo type (boolean / integer / real / string) rather than always string.
- **1.9.12** (28-05-2026) — `lastAction` on button devices became an Indigo enumeration, so each action gets a boolean sub-state for one-click triggers.
- **1.9.11** (27-05-2026) — clean MQTT disconnect and reconnect across Mac sleep and wake.
- **1.9.8–1.9.10** (25-05-2026) — `actionControlSensor` so Send Status Request works on sensor devices, `didDeviceCommPropertyChange` to stop unnecessary device-comm cycling, and a pytest test suite.
- **1.9.0–1.9.7** (22–23-05-2026) — coordinator devices, the Refresh Device Capabilities menu, Indigo subType mapping for HomeKit, PluginConfig credential fallback, and millisecond log timestamps.

## Usage

1. Enable the plugin in Indigo (Plugins → Manage Plugins)
2. Set the **Topic Prefix** in plugin preferences (default: `zigbee2mqtt`)
3. Wait for `MQTT connected` and `Bridge device cache updated: N devices` in the event log
4. **Plugins → Zigbee2MQTT Bridge → Discover & Create Devices** — creates every device
5. (Optional) **Create Coordinator Devices** — adds one coordinator device per MQTT bridge
6. All your Zigbee devices appear in Indigo under the **Zigbee2MQTT** folder

Re-run **Discover & Create Devices** any time you add new Zigbee devices, and
**Refresh Device Capabilities** after a device's zigbee2mqtt definition changes (it
re-detects capabilities and corrects the Indigo subType without delete-and-recreate).

## Acknowledgements

With thanks to **Autolog** for the [zigbee2mqtt plugin](https://github.com/autolog/zigbee2mqtt) — studying its design showed us the way to build this plugin, and the project would not exist without that prior work.

## Authors

CliveS & Claude Opus 4.8
