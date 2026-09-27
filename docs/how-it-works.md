---
title: How it works
nav_order: 4
---

# How it works

You do not need to know any of this to use the plugin. It is here for anyone who likes to know what is going on.

## Listening to the broker

When the plugin starts, it connects to your MQTT broker and asks to hear every message zigbee2mqtt sends under its base topic — `zigbee2mqtt` unless you changed it. zigbee2mqtt sends a message each time a device changes or reports a reading, so the plugin hears about a door opening or a light switching at the same moment zigbee2mqtt does, and updates the Indigo device straight away. There is no polling and no delay built in.

To switch something, the plugin sends zigbee2mqtt a message asking it to, and zigbee2mqtt passes it over the Zigbee radio. When the device confirms the change, zigbee2mqtt reports it back and Indigo shows it.

If a message cannot be sent — because the broker has gone, say — the Event Log says the command was not delivered, naming the device.

## Knowing which device is which

zigbee2mqtt keeps a list of every device it has paired, with the name you gave it, the make and model, and a description of everything the device can do and report. The plugin fetches that list as soon as it connects, and zigbee2mqtt sends it again whenever it changes.

From that list the plugin works out what kind of Indigo device each Zigbee device should be:

- a device that describes itself as a light, or has a brightness level, becomes a **Z2M Light**
- a heating control becomes a **Z2M Thermostat / TRV**, and a lock a **Z2M Lock**
- a blind, or anything with a position you can set, becomes a **Z2M Cover**
- a device that only sends presses, with nothing to switch, becomes a **Z2M Button / Scene**
- anything with an on/off you can switch becomes a **Z2M Relay**
- a repeater, or a device that reports nothing but its signal strength, becomes a **Z2M Repeater**
- a sensor becomes the kind that fits what it measures — contact, occupancy, water leak or temperature — or a general **Z2M Sensor** if it measures a mixture

A wall switch that can also send scene presses is made a **Z2M Relay**, so you can still switch its load from Indigo.

Each Indigo device remembers the Zigbee device's own permanent identity number, so it stays tied to the right one. **If you rename a device in zigbee2mqtt, the plugin renames the Indigo device to match** and carries on. If you move a device from one zigbee2mqtt to the other, the plugin follows it there.

If a device first made as a general sensor later turns out to be a button — some remotes only describe themselves fully after their first press — the plugin replaces it with a **Z2M Button / Scene** device. It never does this to a light, a switch, a blind, a lock, a thermostat or a presence sensor, because that would lose their controls.

## New devices

When zigbee2mqtt sends a new list with a device the plugin has not seen before, the plugin creates its Indigo device by itself, in the **Zigbee2MQTT** folder. zigbee2mqtt has to finish setting a new device up — it calls this the **interview** — before the plugin knows what the device can do, so a device part-way through pairing is created as soon as its interview is complete.

## Everything a device says

Each kind of device has the readings you would expect, listed on the [Your devices](devices.md) page. Beyond those, any other field a device sends is kept as a state of its own, as a number, a word or a tick box to match what the device sent, so a reading the plugin has no special place for still reaches Indigo.

## Staying connected

The plugin checks every 30 seconds that messages are still arriving. If nothing has come in for five minutes, it sends zigbee2mqtt a small request, and if that gets no answer by the next check, it drops the connection and makes a new one. This catches a connection that has stopped working without saying so, which can happen after a network hiccup.

On a very small or quiet Zigbee network, where five minutes can pass without a single message, you can raise that limit with **Watchdog Silence Limit** on the [Settings](settings.md) page.

When the Mac goes to sleep, the plugin disconnects from the broker cleanly, and it reconnects when the Mac wakes.

## Offline devices

zigbee2mqtt decides for itself when a device has gone quiet for too long and reports it offline. When it does, the plugin sets the Indigo device's **Availability** to **Offline**, turns the device red in the device list, and writes one warning to the Event Log. Any plugin that watches for failed devices sees it too. When the device is heard from again, the red clears and the log says it is back online.

## Network health

Every ten minutes, zigbee2mqtt sends a health report. The plugin copies the figures about the computer running zigbee2mqtt onto the **Z2M Coordinator** device, and each device's own figures onto that device. When a device's **Leave Count** goes up — it dropped off the network and joined again — the plugin writes a warning to the Event Log and runs any **Zigbee Device Rejoined** trigger. **Plugins → Zigbee2MQTT Bridge → Report Network Health** lists the devices that have done this most.

## Settings kept on the device

Some Zigbee devices keep their settings in their own memory rather than in zigbee2mqtt — a presence sensor's sensitivity, how long it waits before saying a room is empty, how often a sensor reports. After a battery change some of them go back to their factory settings, and nothing tells you. Two presence sensors in my bedroom did exactly that and stayed wrong for four weeks.

So each device's settings window has a **Device Settings** section, built from the settings that particular device says it has. It only lists settings the device can both be told and report back, so the plugin can always tell whether the device still agrees. Choose a value and click **Save**, and the plugin sends it to the device.

From then on, every time the device reports, the plugin compares what it says with what you chose. If they differ, the plugin writes a warning to the Event Log and sends your setting again. It does this at the moment the device reports because a battery device only listens while it is awake, and a device that has just reported is awake.

Leave a setting on **-- not managed --**, or blank, and the plugin leaves it alone. That is how every setting starts.

## What goes in the log

The Indigo Event Log only shows things you might need to know about: devices joining or leaving the network, a device going offline or coming back, a command that could not be delivered, a setting put back, a firmware update, and anything that went wrong. Routine activity — each command sent, each status request, the steps of connecting to the broker — is written to the plugin's own log file instead, so the Event Log does not fill up with it. The [Settings](settings.md) page shows how to have it in the Event Log as well.

The plugin also tells SQL Logger, if you use it, not to keep a history of **LastSeen**, **Link Quality** and **Messages / sec**, which change with every message a device sends and would otherwise fill the history with thousands of rows a day. Every reading you care about — temperatures, motion, doors, power — is kept as before.
