---
title: Actions and triggers
nav_order: 5
---

# Actions and triggers

## Indigo's usual controls

Lights, plugs, blinds, locks and radiator valves answer Indigo's standard controls wherever you use them — the device list, a control page, a schedule, a trigger or an action group:

- **Lights** — Turn On, Turn Off, Toggle, Set Brightness, Brighten By and Dim By, and on bulbs that have them, colour and white temperature.
- **Plugs and switches** — Turn On, Turn Off and Toggle.
- **Blinds** — Turn On opens, Turn Off closes, and Set Brightness sets how far open, from 0 (closed) to 100 (open).
- **Locks** — lock and unlock.
- **Radiator valves** — set the heat setpoint, raise or lower it, and change the mode to heat, automatic or off.

**Send Status Request** asks zigbee2mqtt to send the device's latest state again. A repeater takes no commands other than this one.

## The plugin's own actions

These are under **Device Actions** when you add an action.

| Action | What it does |
|---|---|
| **Set Color Temperature** | For a light that can change its shade of white. Set **Color Temperature (Kelvin)** — about 2700 for a warm white, 4000 for a neutral white, 6500 for a cold daylight white. It switches the light on if it is off. |
| **Set Brightness / Position** | For a light, sets its brightness from 0 to 100%, where 0 switches it off. For a blind, sets how far open it is. |
| **Set Cover Position** | For a blind, sets how far open it is, from 0 (fully closed) to 100 (fully open). |
| **Refresh Device State** | Asks zigbee2mqtt to fetch the device's latest state. |
| **Publish Custom Payload** | Sends a device a setting, or anything else, in the form zigbee2mqtt understands, for anything the other actions do not cover — see below. |
| **Update Device Firmware** | Starts a firmware update on the device you choose, if one is waiting. It does nothing on a device with no update waiting — see [Firmware updates](firmware-updates.md). |

### Publish Custom Payload

Every Zigbee device has settings zigbee2mqtt can change — a sensor's sensitivity, the brightness of a plug's indicator light, a child lock. zigbee2mqtt's web page shows them under each device, with their names. This action sends one or more of them.

Type the settings into **JSON payload**, written the way zigbee2mqtt names them, in curly brackets, such as:

```
{"motion_sensitivity": "high"}
```

The action window checks the text is in the right form when you click **Save**, so a mistake shows there rather than when the action runs.

A battery device only listens while it is awake, so a setting sent to a sleeping sensor may not arrive. Pressing its button, or setting off its motion sensor, usually wakes it. For a setting you want kept, the **Device Settings** section of the device's own settings window is the better choice, because it puts the setting back whenever the device forgets it — see [Settings](settings.md).

## Running something on a button press

A **Z2M Button / Scene** device can run a trigger on a particular kind of press.

1. Create a new trigger and set its type to **Device State Changed**.
2. Choose the button device.
3. From its list of states, choose the press you want under **Button Action** — **Single**, **Double**, **Hold** and so on — and have it run when that becomes true.

A trigger like this runs when the kind of press changes. If you press the same way twice in a row, **Last Action** does not change, so the trigger runs only for the first. To catch every press, trigger on **Press Count** changing, which goes up with each one, and check **Last Action** in the trigger's conditions.

## The plugin's triggers

These are under **Zigbee2MQTT Bridge** when you create a new trigger. None of them needs setting up — each runs for any device on any zigbee2mqtt you connect.

| Trigger | When it runs |
|---|---|
| **Zigbee Device Joined the Network** | A new device joins. |
| **Zigbee Device Left the Network** | A device leaves the network. |
| **Zigbee Device Announced Itself** | A device says hello after a battery change, a power cut or a restart. This happens now and then without anything being wrong. |
| **Zigbee Device Interview Failed** | zigbee2mqtt could not finish setting up a newly paired device. |
| **Zigbee Device Interview Succeeded** | zigbee2mqtt finished setting up a newly paired device. |
| **Zigbee Device Rejoined (leave count rose)** | zigbee2mqtt's health report shows a device dropped off the network and joined again. |
| **Zigbee Device Changed Network Address** | zigbee2mqtt's health report shows a device took a new place in the network. |
| **Zigbee Device Firmware Update Available** | A device has a firmware update waiting. It runs once when the update appears, not again while it waits. |
| **Zigbee Device Firmware Update Finished** | A firmware update has finished and the device is running the new version. |
| **Zigbee Device Firmware Update Failed** | A firmware update ended with the device still on the old version. |
| **Zigbee2MQTT Bridge Went Offline** | zigbee2mqtt itself stops. |
| **Zigbee2MQTT Bridge Came Online** | zigbee2mqtt comes back after going offline. |
| **Zigbee2MQTT Bridge Needs a Restart** | zigbee2mqtt says it needs restarting for a setting to take effect. |

The two health-report triggers can run up to ten minutes after the event, because zigbee2mqtt sends its health report every ten minutes.

### Knowing which device it was

A trigger does not carry the device's name itself, so the plugin writes it onto the **Z2M Coordinator** device first: **Last Event** says what happened, **Last Event Device** names the device, and **Last Event Time** says when. If you have made the coordinator device with **Plugins → Zigbee2MQTT Bridge → Create Coordinator Devices**, your trigger's actions can read the device name from there — to put it in a notification, for example.
