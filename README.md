# Zigbee2MQTT Bridge for Indigo

**Bring your Zigbee lights, plugs, sensors, blinds, locks and radiator valves into Indigo, through zigbee2mqtt.**

**Version:** 2.13.0 | **Author:** CliveS & Claude | **Needs:** Indigo 2023.2 or later, zigbee2mqtt and an MQTT broker

**[Read the full guide](https://highsteads.github.io/Zigbee2MQTTBridge/)** — setting up, what everything means, and what to do when something goes wrong.

---

## What it does

This plugin lets [Indigo](https://www.indigodomo.com) see and control the Zigbee devices you run with [zigbee2mqtt](https://www.zigbee2mqtt.io). zigbee2mqtt is a free program that runs a Zigbee radio and turns everything your devices say into short messages, which it passes through an **MQTT broker** — a small message post office such as Mosquitto. The plugin connects to that broker, so Indigo hears about every change the moment zigbee2mqtt does, and sends your commands back the same way.

- **Creates all your devices in one go,** picking the right kind for each and putting them in a **Zigbee2MQTT** folder, and adds new ones by itself when you pair them.
- **Controls lights, plugs, blinds, locks and radiator valves** with Indigo's usual controls, including colour and shade of white on bulbs that have them.
- **Brings in every reading** — temperature, humidity, motion and presence, doors and windows, water leaks, smoke, power and energy — and anything else a device reports.
- **Fills in Indigo's own battery and energy readings,** and turns a device red when zigbee2mqtt says it has gone offline.
- **Keeps settings on the device where you put them.** Some sensors forget their settings after a battery change, and the plugin notices and puts them back.
- **Gives a sensor's extra readings their own devices,** so a presence sensor's temperature can be a proper Indigo temperature sensor.
- **Handles firmware updates,** telling you when one is waiting and installing it only when you ask.
- **Runs triggers** when a device joins or leaves, a button is pressed a particular way, a firmware update finishes, or zigbee2mqtt goes offline.
- **Looks after zigbee2mqtt itself** — backs it up to the Mac, restarts it, and checks it for routers that have stopped answering.
- **Works with two zigbee2mqtt set-ups at once.** I run one for the house and one for the garage.

## What it works with

Anything zigbee2mqtt supports. The plugin makes each one into the matching Indigo device:

| In Indigo | Your device |
|---|---|
| **Z2M Light** | Bulbs, lamps and LED strips |
| **Z2M Relay** | Wall switches, smart plugs and switch modules |
| **Z2M Cover** | Blinds, curtains and shutters |
| **Z2M Lock** | Door locks |
| **Z2M Thermostat / TRV** | Radiator valves and other heating controls |
| **Z2M Contact Sensor**, **Z2M Occupancy Sensor**, **Z2M Water Leak Sensor**, **Z2M Temperature Sensor**, **Z2M Sensor** | Door and window, motion and presence, water leak, temperature and humidity sensors, smoke alarms and the rest |
| **Z2M Button / Scene** | Wireless buttons and remotes |
| **Z2M Repeater** | Repeaters and range extenders |
| **Z2M Coordinator** | zigbee2mqtt itself, one for each you run |

You need zigbee2mqtt already set up and working, with its messages going to an MQTT broker. The plugin connects Indigo to it and does not replace it.

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/Zigbee2MQTTBridge/releases/latest) and download `Zigbee2MQTTBridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Zigbee2MQTTBridge.indigoPlugin`
3. Double-click `Zigbee2MQTTBridge.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. Open **Plugins → Zigbee2MQTT Bridge → Configure**, fill in **Broker Host** with your MQTT broker's network address — the four numbers, such as `192.168.1.10` — and its **Username** and **Password** if it has them. Leave **Topic Prefix** as `zigbee2mqtt` unless you changed zigbee2mqtt's base topic, and click **Save**.
2. Wait a few seconds for the Event Log to say **Bridge device cache updated**, then choose **Plugins → Zigbee2MQTT Bridge → Discover & Create Devices**.
3. Your Zigbee devices appear in a **Zigbee2MQTT** folder in Indigo. Switch one from Indigo, and it should respond straight away.

The [full guide](https://highsteads.github.io/Zigbee2MQTTBridge/) goes through each step, explains every setting, and covers what to do if something does not work.

## What's new

**v2.13.0** — A **Zigbee Button Pressed** trigger that runs on every press, an offline-device count on each coordinator, **Back Up zigbee2mqtt** to the Mac, **Restart zigbee2mqtt**, **Check for Missing Routers** and **Set Up a Device Again**, and **Stop Blind** and **Fade Light** actions.

**v2.12.0** — Switches with two or more channels now work, with a device for each extra channel if you want one. Device Settings take a device's named choices, such as a Hue bulb's **previous** colour after a power cut.

**v2.11.0** — Nine faults found by an independent review, all fixed. Separate devices no longer stop the original updating, a smoke alarm that also measures temperature is made as an alarm, **Refresh Device List from MQTT** works, and grouped device settings reach the device. The [version history](https://highsteads.github.io/Zigbee2MQTTBridge/changelog.html) lists all nine.

Every version is listed in the [version history](https://highsteads.github.io/Zigbee2MQTTBridge/changelog.html).

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
