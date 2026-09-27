---
title: Home
nav_order: 1
---

# Zigbee2MQTT Bridge for Indigo

This plugin brings your Zigbee bulbs, plugs, switches, sensors, blinds, locks and radiator valves into [Indigo](https://www.indigodomo.com) as ordinary Indigo devices, which you can switch, watch and use in triggers, schedules and control pages like any other.

It does this through **zigbee2mqtt**, a free program that many people already use to run their Zigbee devices. You need zigbee2mqtt set up and working first — the plugin does not replace it, it connects Indigo to it.

## The three pieces, in plain words

- **Zigbee** is the low-power radio that most smart bulbs, plugs and battery sensors use to talk to each other. It is not Wi-Fi, so it needs a Zigbee radio of its own, usually a USB stick or a small network box called a **coordinator**.
- **zigbee2mqtt** is the program that runs that radio. It pairs your devices, keeps a list of them, and turns everything they say into short messages — "the kitchen light is on at 40%", "the back door has opened" — and takes messages the other way to switch them.
- **MQTT** is a simple way for programs to pass those messages to each other through a central post office called a **broker**. Mosquitto is the broker most people use, and it can run on the same Mac as Indigo.

The plugin connects to the broker, reads every message zigbee2mqtt sends, and keeps the matching Indigo devices up to date. When you switch something in Indigo, the plugin sends zigbee2mqtt the message to do it.

## What it does for you

- **Creates all your devices in one go.** One menu item makes an Indigo device for every Zigbee device zigbee2mqtt knows about, picks the right kind for each, and puts them all in a **Zigbee2MQTT** folder.
- **Adds new ones by itself.** Pair a new device in zigbee2mqtt while the plugin is running and its Indigo device appears without you doing anything, and renaming a device in zigbee2mqtt renames it in Indigo too.
- **Controls lights, plugs, blinds, locks and radiator valves** with Indigo's usual controls, including brightness, colour and colour temperature on bulbs that have them.
- **Brings in every reading** — temperature, humidity, motion, doors and windows, water leaks, smoke, power and energy, battery level, and anything else a device reports.
- **Fills in Indigo's own battery and energy readings,** and turns a device red in Indigo when zigbee2mqtt says it has gone offline.
- **Keeps settings on the device where you put them.** Some sensors forget their settings after a battery change, and the plugin notices and puts them back.
- **Gives a sensor's extra readings their own devices** — a presence sensor that also measures temperature can have its temperature as a proper Indigo temperature sensor.
- **Handles firmware updates**, telling you when one is waiting and installing it only when you ask.
- **Runs triggers** when a device joins or leaves the network, a firmware update finishes, or zigbee2mqtt goes offline.
- **Works with two zigbee2mqtt set-ups at once.** I run one for the house and a second for the garage, and both feed the same plugin.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and bring in your devices | [Getting started](getting-started.md) |
| Know what each kind of device shows in Indigo | [Your devices](devices.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Use the plugin's actions and triggers | [Actions and triggers](actions-and-triggers.md) |
| Check for and install firmware updates | [Firmware updates](firmware-updates.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/Zigbee2MQTTBridge/releases/latest).
