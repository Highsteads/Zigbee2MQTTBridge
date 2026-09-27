---
title: Firmware updates
nav_order: 6
---

# Firmware updates

Many Zigbee devices can have their built-in software, their **firmware**, updated over the Zigbee radio. zigbee2mqtt keeps track of which of your devices have an update waiting, and the plugin shows you that in Indigo and lets you install one when you choose.

**Nothing updates by itself.** An update takes several minutes, the device does not respond while it runs, and if it is interrupted — by switching the device off at the wall, say — the device can be left unusable. So the plugin only ever starts one when you ask.

## What each device shows

Devices that zigbee2mqtt says can take updates carry these:

| Shown as | What it means |
|---|---|
| **Firmware State** | **idle** when there is nothing to do, **available** when an update is waiting, and **updating** while one runs. |
| **Firmware Update Available** | Ticked while an update is waiting. |
| **Installed Firmware** | The version the device has now. |
| **Latest Firmware** | The newest version zigbee2mqtt knows of. |
| **Update Progress %** | How far an update has got, while it runs. |

The plugin goes by the **Firmware State** zigbee2mqtt reports, not by comparing the two version numbers, because manufacturers number their versions in their own ways and the numbers do not always compare.

## Checking for updates

Choose **Plugins → Zigbee2MQTT Bridge → Check for Firmware Updates**. The plugin asks zigbee2mqtt to check every device that can take updates. This only looks — it installs nothing.

The answers arrive over the next few minutes. A battery device answers only when it next wakes, so some take longer, and one that never answers is simply asleep, not faulty.

Then choose **Plugins → Zigbee2MQTT Bridge → Report Firmware Status**. The Event Log lists every device that can take updates, the version it has, the newest version, and whether one is waiting. Devices with an update waiting are shown as warnings so they stand out.

## Installing an update

1. Choose **Plugins → Zigbee2MQTT Bridge → Update Device Firmware...**
2. Pick the device from the list. Only devices with an update waiting are listed, each with the version it has and the version it will move to. If the list says **-- no updates waiting --**, run **Check for Firmware Updates** first.
3. Click the button to start it.

The Event Log says the update has started. Watch the device's **Update Progress %** if you like. Leave the device powered until it finishes.

To start one from a schedule or an action group instead, for a quiet time of night, add the **Update Device Firmware** action under **Device Actions** and choose the device.

The plugin refuses to start an update on a device that cannot take one, on a device with no update waiting, or on a device that is already updating, and says why in the Event Log.

## Knowing when it has finished

When the update is done, the Event Log says so, with the new version, such as **now running 1.163.1 (build 16788992, 14 May 2026)**.

An update that reaches 100% has only finished copying the new firmware across. The device then installs it and restarts, and the plugin waits until the device reports back before calling the update finished. If the device comes back still on its old version, the Event Log says the update did not complete.

You can have Indigo tell you, using the triggers **Zigbee Device Firmware Update Available**, **Zigbee Device Firmware Update Finished** and **Zigbee Device Firmware Update Failed** — see [Actions and triggers](actions-and-triggers.md).
