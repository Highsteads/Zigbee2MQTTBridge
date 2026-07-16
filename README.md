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
  - **Z2M Sensor family** — a generic sensor plus auto-classified Contact, Occupancy / presence, Water-leak and Temperature / Humidity types, each given the matching Indigo subType so HomeKit and friends route them correctly. Smoke detectors are handled too, with the alarm driving the sensor's on/off state
  - **Z2M Lock** (relay, Lock subtype) — door locks with proper lock / unlock commands and the full lock state (including "not fully locked") in its own state
  - **Z2M Thermostat / TRV** (thermostat) — radiator valves and climate devices as real Indigo thermostats: current temperature, heat setpoint (settable from the standard thermostat UI), heat / auto / off mode, running state and valve position
  - **Z2M Coordinator** — one device per MQTT bridge, tracking the Z2M version, coordinator type, permit-join, network and device count
- **Every payload field is imported.** Beyond the semantic states above, any other field a device reports is captured as a dynamically-declared state of the correct Indigo type (boolean / integer / real / string), so nothing is thrown away
- **Self-healing MQTT** — an application-level liveness backstop rebuilds the connection if it falls silent, catching the half-open-socket wedge that paho's own auto-reconnect can miss. Before rebuilding it first probes the bridge, so a small quiet network is never mistaken for a dead connection. MQTT also disconnects and reconnects cleanly across Mac sleep and wake
- Multiple zigbee2mqtt instances supported (for example a main bridge plus a separate garage coordinator), with each device routed to its own bridge even when friendly names clash
- **Pairing from Indigo** — Enable / Disable Pairing menu items open and close permit-join on every configured bridge, and each device carries a readable "last seen" state
- **Publish Custom Payload** action — send any JSON settings object to a device (sensitivity, LED modes, calibration and so on) without leaving Indigo
- **Test MQTT Connection** menu item — one log dump with the full environment banner plus live broker, traffic and bridge checks, ideal for a support post. A companion Report Orphaned Devices item lists any Indigo device whose Zigbee counterpart has been removed
- Availability and link quality tracked per device, friendly names containing `/` handled, everything organised in a **Zigbee2MQTT** device folder

## Requirements

- Indigo 2023.2 or later (developed and run on Indigo 2025.2 / Python 3.13)
- zigbee2mqtt running and reachable over MQTT
- MQTT credentials in `IndigoSecrets.py` OR entered in PluginConfig (fallback added in v1.9.6)
- Bundled Python dependencies, installed automatically on first run: `paho-mqtt` only (as of v1.9.16)

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

- **1.10.0** (16-07-2026) — new device types and quality-of-life features from a full review pass. Door locks get their own device type with proper lock and unlock commands (they were previously treated as plain switches), and radiator valves / climate devices become real Indigo thermostats with a settable heat setpoint, mode control and valve position. A new Publish Custom Payload action sends any JSON settings object to a device, pairing can be opened and closed straight from the plugin menu, every device gains a readable "last seen" state, and a Test MQTT Connection menu item produces a single log dump made for support posts. An unreachable broker or wrong password is now reported clearly once, rather than silently or on every retry.
- **1.9.21–1.9.23** (16-07-2026) — a fresh full review with fixes in three sweeps. The important ones: a wall switch that also sends scene actions is now created as a switchable relay rather than a button (before, its load could not be controlled from Indigo at all), and smoke alarms now actually reach Indigo — previously a smoke detector's alarm produced no state change anywhere. Sensors bolted onto other device types (a door sensor's thermometer, a plug's voltage) are no longer dropped, radiator valves no longer appear as window blinds, and identical friendly names on two bridges no longer cross their wires. Colour bulbs report full saturation correctly, brightness readback matches what you set, and a command that could not be delivered now says so instead of claiming success. Dozens of smaller robustness and logging refinements ride along, and the test suite grew from 474 to just under 600.
- **1.9.20** (27-06-2026) — third deep-review batch, clearing the last of the review's lower-priority items. All internal robustness. The device-lookup tables are now lock-protected so a device starting or stopping can never collide with a background rename, a dimmer that reports zero brightness now reads as off (some bulbs briefly say "on at zero" mid-fade), the auto-detect-a-button safety net ignores a bare button number that carries no real action, colour readings round to a clean 100 per cent at full saturation rather than 99, and a stray device field that happens to share a name with a built-in state is left alone rather than written with the wrong type. The worker loop was also restructured so one bad message can never stall the rest. The test suite grew to 474.
- **1.9.19** (26-06-2026) — second deep-review batch, mostly robustness corners. Rebuilding the MQTT connection is now done as one atomic step, so a settings save can never collide with the self-heal watchdog and leave a stray connection running in the background. A mixed motion-and-presence sensor that falls back to the generic sensor type no longer reports a room empty when only one of its detectors updates. The button "last action" now covers the full vocabulary of multi-function remotes, and anything unusual lands tidily on "Other" rather than vanishing. Tunable-white bulbs also pick up their colour-temperature capability the moment they are created rather than only after a manual capability refresh, and Refresh Device State is now offered on every sensor type. The test suite grew to 448.
- **1.9.18** (26-06-2026) — important fix for presence sensors. A motion or presence sensor that also reports region or presence events (such as the Aqara FP1) could be quietly rebuilt as a button the first time one of those events arrived, which changed the underlying device and broke anything pointing at it. That can no longer happen — a sensor reporting presence or occupancy is never reclassified as a button. Also reconnects more gracefully after the Mac wakes from sleep, and a few internal guards were tightened so the background worker keeps running through an unexpected hiccup.
- **1.9.17** (13-06-2026) — device-type detection fix: a device that reports both presence and an action list (again, the Aqara FP1) is now recognised as a presence sensor rather than a button when it is first discovered. Added a "device zoo" test layer that runs real captured device descriptions through the classifier to catch this class of mistake early.
- **1.9.16** (10-06-2026) — housekeeping from a full repo audit, nothing visible changes day to day. Installs are much lighter: the unmaintained `colormath` library (which dragged the large `numpy` package onto every machine) has been dropped — the one colour conversion it performed is now done in a few lines of plain Python, with proper gamma correction so reported lamp colours stay true. The repo also gained automatic testing on every change (GitHub Actions runs the full 269-test suite plus a lint pass), a couple of silent edge cases now log a warning instead of vanishing (a malformed bridge message used to be discarded without trace), and an internal threading rule that one callback was quietly bending is now followed to the letter.
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

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
