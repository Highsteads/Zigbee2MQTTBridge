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
- **Indigo's own battery and energy readings are filled in** — a battery device appears in Indigo's low-battery list and anywhere else a device's battery is read, and a metering plug reports into the Energy UI. Reset Energy Total works even though the counter itself lives on the Zigbee device: the plugin remembers the reading at the moment you reset and counts from there
- **An offline device goes red.** When zigbee2mqtt reports a device offline, the Indigo device is put into an error state, so the device list and any health-monitoring plugin can see it
- **Network health** — the plugin reads zigbee2mqtt's health report and keeps per-device counters for rejoins and network-address changes, the only record of a device dropping off and coming back. **Report Network Health** lists the worst offenders, alongside how long zigbee2mqtt has been running and how hard its host is working
- **Trigger events** — trigger directly on a device joining, leaving, announcing itself, failing or passing its interview, rejoining, changing network address, or on a bridge going offline, returning, or asking to be restarted. The coordinator device records which device the last event was about, so a trigger's actions can name it
- Availability and link quality tracked per device, friendly names containing `/` handled, everything organised in a **Zigbee2MQTT** device folder

## Requirements

- Indigo 2023.2 or later (developed and run on Indigo 2025.2 / Python 3.13)
- zigbee2mqtt running and reachable over MQTT
- MQTT credentials in `IndigoSecrets.py` OR entered in PluginConfig (fallback added in v1.9.6)
- One bundled Python dependency, installed automatically on first run: `paho-mqtt` 2.1.0, pinned since v2.0.0

## Installation

1. Go to the [Releases](../../releases) page and download `Zigbee2MQTTBridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Zigbee2MQTTBridge.indigoPlugin`
3. Double-click `Zigbee2MQTTBridge.indigoPlugin` — Indigo will install it automatically

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin, like every CliveS Indigo plugin, reads sensitive values from one
shared master file:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you don't have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` out of
the plugin bundle into `/Library/Application Support/Perceptive Automation/`,
rename it to `IndigoSecrets.py`, and fill in your values. Or skip the file
altogether and type the values into the plugin's configuration dialog — where
both are set, `IndigoSecrets.py` wins.

If neither source supplies a value the plugin needs, it logs an ERROR naming
the key and telling you to either fill in the matching field or add the key to
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

Every log line carries a millisecond timestamp `[HH:MM:SS.mmm]`, so you can
line events up precisely against the other CliveS plugins — Device Activity
Monitor uses the same format.

To turn the prefix off, or back on, at any time:

**Plugins → Zigbee2MQTT Bridge → Toggle Timestamps in Log (on/off)**

The plugin stores the setting in `pluginPrefs` (`timestampEnabled`) and it
survives a restart. It defaults to ON.

## Version history

**v2.7.1** — Tidier completion message. The log said *"now on version {'date_code': '20260514', 'file_version': 16788992, 'software_build_id': '1.163.1'}"* — the raw reply from zigbee2mqtt, dropped straight into the sentence. It now reads *"now running 1.163.1 (build 16788992, 14 May 2026)"*. And because two separate signals both notice an update ending, it no longer says so twice.

**v2.7.0** — **You can be told when a firmware update finishes.** There were events for an update becoming available but none for it ending, so you had to keep checking. There are now triggers for **Firmware Update Finished** and **Firmware Update Failed** — hook one to a notification and the lamp tells you itself.

Worth knowing what "finished" means: progress reaching 100% only means the file has transferred. The device then writes it and restarts, and it is coming back that counts. The trigger waits for that, so it fires when the device is genuinely running the new firmware.

**v2.6.0** — **Installing a firmware update is now two clicks.** There is a new **Plugins → Zigbee2MQTT Bridge → Update Device Firmware...** menu item, listing only the devices that actually have an update waiting, with the version they are on and the version they would move to. Pick one and it starts.

Previously this meant building an Action Group to press a button once, which was the wrong shape for a one-off job. The action is still there for use in a trigger or schedule, and both routes go through exactly the same safety checks.

**v2.5.1** — Quieter firmware checks. Asking a houseful of battery sensors about their firmware means most of them are asleep and will not answer, which is normal rather than a fault — those replies no longer appear as errors, and a real failure still does. The log also no longer refers to a device called "?" when zigbee2mqtt's reply does not identify one.

**v2.5.0** — **Split a sensor's extra readings into their own devices.** A presence sensor that also measures temperature, humidity and light puts all of it into one Indigo device, where the extra readings sit as plain states — no sensor type, nothing HomeKit can see, and nowhere obvious to put them on a control page.

Open such a device's settings and you will now find a **Separate Devices** section listing what else it measures. Tick one and that reading gets its own Indigo device, grouped with the original, showing up as a proper temperature or humidity sensor.

The original device is left completely alone — same device, same id, same states — so every trigger, script and control page pointing at it carries on working. And if you change your mind, unticking the box never deletes anything: the extra device is renamed and set aside, in case something is pointing at it, and you delete it yourself when you are sure.

**v2.4.2** — Housekeeping. Settings you leave blank are no longer stored, so a device's properties show only the handful you actually chose. And a startup message about two devices displaying an older state in the device list is now an ordinary note rather than a warning — it is cosmetic, the only cure would be deleting and recreating the device, and a warning you can never act on just teaches you to ignore warnings.

**v2.4.1** — **Fixed a settings comparison that could nag a device.** Devices describe an on/off setting in their own words — some say `"ON"` and `"OFF"`, some say true and false, and the same device can do both for different settings. The plugin compared them carelessly, so a setting that was already correct could look wrong. In practice that meant it wrote the value again when you saved the dialog, and would have kept rewriting it every time the device mentioned that setting — wasteful on a battery device.

Settings that cannot be compared with confidence are now left alone rather than assumed wrong.

**v2.4.0** — **Firmware updates, surfaced at last.** zigbee2mqtt already keeps track of which devices have a firmware update waiting, and the plugin was quietly discarding it. Each device now shows its firmware state, the version it is on and the version available, and there is a trigger for when one appears. Two new menu items check for updates and report what is waiting.

Installing one is always your decision — nothing updates on its own. An update runs for several minutes over a radio link and interrupting it can leave a device unusable, so the action refuses unless an update is genuinely waiting and the device is not already busy with one.

**v2.3.0** — **Device settings stay where you put them.** Some sensors keep their settings in their own firmware, not in Indigo — sensitivity, detection delays, reporting intervals. Nothing owned those settings, so when a device forgot them nothing noticed. Two presence sensors here were set deliberately in June, quietly reverted to factory defaults after a battery change, and stayed wrong for four weeks.

Each device's settings dialog now has a **Device Settings** section, built from what that particular device says it can be told. Set a value there and the plugin remembers it, notices when the device drifts off it, says so in the log, and puts it back.

Only real settings appear — ones the device can also report back, so the plugin can tell "it has drifted" from "it agrees". Things like *Restart Device* and *Start Learning* look like settings but are one-shot commands, and are deliberately left out: re-applying one every time a device reconnected would restart the sensor over and over.

Leave a field blank and the plugin has no opinion about it, which is the default for everything.

**v2.2.0** — **Mains-powered devices no longer show a flat battery.** zigbee2mqtt says how each device is powered and the plugin was ignoring it, so anything on mains was given a battery reading of 0% — which looks exactly like a dead cell. Those devices now carry no battery reading at all, and any that already picked one up is labelled "Mains" instead. A device whose power source zigbee2mqtt does not report keeps its battery reading, deliberately: hiding a genuinely flat one would be the worse mistake.

Also a large internal tidy-up. The main plugin file had grown past 5,000 lines and is now split across a dozen focused modules. Nothing changes in use — same devices, same states, same settings — but future work lands in sensible places instead of one enormous file.

**v2.1.1** — added the plugin's icon. It had never had one, so it showed as a blank tile wherever Indigo lists plugins by picture. Nothing else changed.

**v2.1.0** — **Indigo now sees what it was always able to show.** Battery-powered Zigbee devices reported their charge into a plugin state and nowhere else, so Indigo's own low-battery list, and every other plugin that reads a device's battery, saw nothing at all — only Z-Wave devices had it. They now carry the real Indigo battery level. Metering plugs reach the Energy UI for the first time, and Reset Energy Total works properly: the kilowatt-hour counter lives on the Zigbee device and cannot be reset from Indigo, so the plugin stores the reading taken at the moment you reset and counts from there. When zigbee2mqtt says a device is offline, that device now goes red in Indigo and shows as being in error, which is what health-monitoring plugins look at — until now an offline sensor looked perfectly well.

Two new things arrive with it. The plugin reads zigbee2mqtt's **health report**, published every ten minutes and previously ignored, which is the only place that records a device rejoining the network or hopping to a different route — the answer to "why did that sensor go quiet". Each device gains its own counters, each bridge gains the zigbee2mqtt process and host figures, and a new **Report Network Health** menu item lists the troublemakers worst first. And the plugin gains **trigger events** for the first time: a device joining, leaving, announcing itself or failing its interview, a device rejoining or changing network address, and a bridge going offline, coming back or asking to be restarted. Previously any of these needed a script watching the log.

- **2.0.3** (08-08-2026) — added the missing support link. Every Indigo plugin is meant to carry a web address inside its bundle — it is what the "About" item in the Plugins menu opens. This one had the entry but left it blank, so that menu item went nowhere. It now points at this repository. Nothing else changed.
- **2.0.1–2.0.2** (21-07-2026) — housekeeping pair. Named log levels now map to the real logging levels — warnings and errors raised through the shared helper had been appearing as plain info lines, so amber and red entries people relied on for diagnosis never showed. Shared-utility refresh: calling the log timestamp filter twice no longer double-stamps every line, and the module imports cleanly outside Indigo.
- **2.0.0** (16-07-2026) — the MQTT library moves to paho-mqtt 2.1.0. No behaviour change day to day, but it is a clean break with the old 1.x library, hence the major version. If an upgrade ever misbehaves after this one, delete the plugin's Packages folder and its pip success marker, then restart the plugin so the bundle reinstalls its libraries from scratch.
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

## Plugin menu

**Plugins → Zigbee2MQTT Bridge →**

| Menu item | What it does |
|-----------|--------------|
| **Discover & Create Devices** | Create an Indigo device for every zigbee2mqtt device that does not have one yet, all in the **Zigbee2MQTT** folder. |
| **Create Coordinator Devices** | Add one coordinator device per configured bridge, named `Z2M Bridge (<prefix>)`. |
| **Refresh Device List from MQTT** | Ask each bridge to republish its device list, so the plugin's cache catches up without a restart. |
| **Refresh Device Capabilities** | Re-read what each existing device can do from the live `exposes` definition and correct its capability flags and Indigo subType, with no delete and recreate. |
| **Report Orphaned Devices** | List Indigo devices whose Zigbee counterpart has gone from the bridge. Reports only — it never deletes anything. |
| **Report Network Health** | List what zigbee2mqtt's health report says about each bridge and its devices — how long zigbee2mqtt has been up, how hard the host is working, and which devices have rejoined the network or changed address, worst first. |
| **Enable Pairing (Permit Join, 254s)** | Open every configured bridge for pairing for 254 seconds, zigbee2mqtt's longest window. The coordinator device's permit-join state confirms it took. |
| **Disable Pairing (Permit Join Off)** | Close every bridge to pairing at once. |
| **Toggle Timestamps in Log (on/off)** | Turn the millisecond log prefix on or off. |
| **Test MQTT Connection** | Dump the full banner and then check the broker, the traffic and the bridge in one go — made for a support post. |
| **Show Plugin Info** | Log the full plugin and environment banner. |

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
