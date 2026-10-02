---
title: Version history
nav_order: 10
---

# Version history

The newest version is at the top.

## 2.17.0 — 2 October 2026

**Report Network Map.** A new menu item and action that have zigbee2mqtt ask every router which devices it can hear, then write a plain report to the log. It starts with what needs attention — a device with no route, a device on a weak link and the router it uses, a router that did not answer — then lists each router with how many devices rely on it, and every device with the router it talks through, weakest first. A light that devices rely on is pointed out, because switching it off at the wall cuts them off. On my house network it took just over two minutes and found a motion sensor hanging on to a light in the garage by a thread.

## 2.16.0 — 2 October 2026

- **Firmware updates for battery devices.** **Update Device Firmware** now asks when to install: **Now**, or **The next time the device asks**. The second waits until the device wakes and asks for new firmware by itself, so a sleeping sensor no longer misses the update. If an attempt fails, zigbee2mqtt tries again next time, and the Failed trigger waits until the update is really over.
- **Cancel Firmware Update** — a menu item and an action that cancel a scheduled update or stop one that is installing. Stopping one you asked to stop is not counted as a failure.
- **Release notes.** Where the maker publishes notes on what an update changes, the start of them appears in the log when the update becomes available, and in **Report Firmware Status**.
- A device whose update failed or was stopped no longer runs the **Firmware Update Available** trigger again for the same update.

## 2.15.0 — 2 October 2026

**Zigbee scenes.** Three new actions for a group or a light: **Store Zigbee Scene** saves what the lights are doing now — on or off, brightness and colour — in each light's own memory, **Recall Zigbee Scene** puts every light back that way at the same moment, and **Remove Zigbee Scene** deletes one. The scenes are picked from a list of the ones stored, and a group device shows them in a new **Scenes** state.

## 2.14.0 — 2 October 2026

**zigbee2mqtt groups are now Indigo devices.** Make a group in zigbee2mqtt's web page, add your lights or plugs to it, and the plugin makes a **Z2M Group Light** or **Z2M Group Switch** for it. Switching the group sends one message to every member at once, so the lights change together instead of one after another, and the group works anywhere a light or switch does — control pages, schedules, triggers and HomeKit. **Discover & Create Devices** makes them too. A group follows a rename in zigbee2mqtt, shows its members, and gains colour controls when a member that has colour joins.

## 2.13.0 — 2 October 2026

Five things other home automation systems do with zigbee2mqtt that this plugin did not.

- **A Zigbee Button Pressed trigger.** Choose the device and the press, or any press, and it runs on every press, the same press twice in a row included. Before, a trigger on the button's state ran only when the kind of press changed.
- **The whole network at a glance.** Each coordinator device now shows how many devices are offline and which, and a **Number of Offline Zigbee Devices Changed** trigger runs when that changes.
- **Back Up zigbee2mqtt.** A menu item and an action save zigbee2mqtt's settings and device list to a folder on the Mac, keeping the newest ten. It is everything you need to set zigbee2mqtt up again on new hardware. The file holds your Zigbee network's key, so it is saved where only your Mac account can read it.
- **Looking after zigbee2mqtt from Indigo.** **Restart zigbee2mqtt**, **Check for Missing Routers** (a mains-powered device that has stopped answering) and **Set Up a Device Again** (the usual cure for a device that has stopped reporting), each as a menu item and an action.
- **Stop Blind** and **Fade Light to Brightness** actions. The fade is done by the bulb itself, over the seconds you choose.

## 2.12.0 — 2 October 2026

- **Switches with more than one channel now work.** A two-gang wall switch, such as a Tuya TS0002, used to come in as one device that never showed on or off, and whose On and Off went to whichever channel zigbee2mqtt chose. The device now follows and switches its first channel, and each other channel can have a device of its own from the **Separate Devices** section of its settings window.
- **Device Settings take a device's named choices.** Where a device lists named values for a number, such as a Hue bulb's **previous** for the colour it comes back at after a power cut, you can type the name, and a value outside the ordinary range is accepted when it is one of those choices. The window lists them, and shows the name beside what the device reports.

## 2.11.0 — 2 October 2026

Nine faults found by a second, independent review, all fixed. None of them was causing trouble in my house, but each would have caught somebody out.

- **Separate devices now work.** Splitting a reading out into a device of its own stopped the original device updating, because the new device took over the messages meant for the original. The original now keeps them and passes the reading on, as it was always meant to, and switching the new device off or deleting it no longer cuts the original off.
- **A smoke alarm that also measures temperature is now made as an alarm.** It used to come in as a temperature sensor, whose on and off never moved, so a trigger watching for it to turn on would never fire. One already made that way by an older version writes an error to the log every time it reports smoke, telling you how to make it again as an alarm.
- **Refresh Device List from MQTT now works.** It used to ask zigbee2mqtt for something zigbee2mqtt does not offer, so nothing came back. It now asks the MQTT broker to send the list zigbee2mqtt left there, and says so in the log if none arrives.
- **Device Settings that belong to a group are sent the way the device expects.** A bulb's colour options, for example, live inside a group, and the plugin was sending them on their own, which the device ignores. They now show the group's name in front and go to the device inside their group.
- **A failed firmware update fires the Firmware Update Failed trigger once,** not twice with the second naming a device called "unknown".
- **A firmware check now says whether an update is waiting,** not just that it finished.
- **A device renamed in zigbee2mqtt can no longer undo Refresh Device Capabilities** if the two happen at the same moment.
- **Motion cannot clear by mistake after a restart.** A sensor with both a motion detector and a presence radar could show the room empty when one of them reported on its own, while the other still saw someone there.
- **Topic Prefix can now have several levels,** such as `house/zigbee2mqtt`, which zigbee2mqtt allows. The plugin used to accept one and then ignore every message under it. It now refuses a prefix with `+` or `#` in it, and two prefixes where one sits inside the other.
- **The first device on a brand new Zigbee network is made by itself,** even when it joined while the plugin was not connected.

## 2.10.0 — 27 September 2026

When zigbee2mqtt reports a device offline, the plugin turns it red in Indigo so you and any plugin watching for failed devices can see it. That red could vanish within ten minutes while the device was still dead, because other updates the plugin writes to the device, such as its network counters, were clearing it. The red now stays until zigbee2mqtt hears from the device again, and nothing else about what the plugin shows has changed.

## 2.9.0 — 27 September 2026

The **Update Device Firmware** action never asked which device to update, so it could never do anything. It now shows a list of your Zigbee devices when you add it to a schedule or an action group, and it still refuses any device with no update waiting.

The **Broker Port** in the plugin's settings was ignored unless the shared settings file existed with a blank port line, so a broker on any port other than 1883 could only be set in that file. The number you type into **Broker Port** is now used whenever the shared file does not give a port of its own, and 1883 only when neither does.

The example shared settings file inside the plugin now holds just the four broker lines this plugin reads, rather than every setting for every one of my plugins.

## 2.8.3 — 23 September 2026

Zigbee devices no longer fill SQL Logger's history with radio housekeeping. Every message a device sends updates when it was last heard, its link quality and its message rate, and SQL Logger was saving a history row for those alone — about 29,000 rows a day in my house. The plugin now tells SQL Logger to skip those three. Every other reading is kept as before, anything you had already told SQL Logger to skip is kept, and existing history is untouched.

## 2.8.2 — 11 September 2026

The plugin carries a note of where its code lives on GitHub, and it now spells that note the same way other Indigo plugins do. Nothing else changed.

## 2.8.1 — 7 September 2026

The plugin's settings window was stretched far wider than its own window could show, so the help beside each setting was cut off. The longest help texts now sit in paragraphs that wrap. No setting changed.

## 2.8.0 — 6 September 2026

Each command the plugin sends, such as switching a lamp to 40%, is written to the plugin's own log file rather than the Indigo Event Log, where they added about 80 lines a day. A new **Log Routine Activity to the Event Log** setting puts them back. Failures, devices joining or leaving, and zigbee2mqtt going offline still appear in the Event Log.

## 2.7.3 — 2 September 2026

A new model of SMLIGHT coordinator box, the SLZB-06P10, was made a relay instead of a repeater. Every SLZB-06 and SLZB-07 model is now recognised as a repeater, including ones not yet made.

## 2.7.2 — 2 September 2026

- A device made by duplicating another in Indigo kept the original's identity number, which could have led the plugin to rename the copy after the original. The plugin now corrects the number from zigbee2mqtt.
- The plugin will not rename a device to a name another of your devices already has, and says so once in the log.
- A device first seen before zigbee2mqtt had finished setting it up is now created as soon as it has, rather than never.

## 2.7.1 — 15 August 2026

When a firmware update finishes, the log gives the new version in readable form, such as **now running 1.163.1 (build 16788992, 14 May 2026)**, and says so once rather than twice.

## 2.7.0 — 15 August 2026

New **Zigbee Device Firmware Update Finished** and **Zigbee Device Firmware Update Failed** triggers. An update counts as finished only once the device has restarted on the new version, not when the file has finished copying.

## 2.6.0 — 15 August 2026

New **Plugins → Zigbee2MQTT Bridge → Update Device Firmware...** menu item, which lists only the devices with an update waiting, with the version each is on and the version it would move to. Pick one and it starts.

## 2.5.1 — 15 August 2026

When you check for firmware updates, a battery device that is asleep and does not answer is no longer reported as an error. A real failure still is.

## 2.5.0 — 15 August 2026

A sensor's extra readings can have devices of their own. A presence sensor that also measures temperature, humidity or light gains a **Separate Devices** section in its settings, and ticking a reading gives it its own Indigo sensor device, grouped with the original. The original device is left exactly as it was, and unticking the box never deletes anything.

## 2.4.2 — 15 August 2026

Device settings you leave blank are no longer stored. A startup message about two devices showing an older state in the device list is now an ordinary note rather than a warning, because the only cure is to delete and recreate them.

## 2.4.1 — 15 August 2026

Fixed a comparison that could make a device setting that was already right look wrong, so the plugin would have sent it again every time the device reported. A setting the plugin cannot compare with confidence is now left alone.

## 2.4.0 — 14 August 2026

Firmware updates. Each device shows whether an update is waiting, the version it is on and the newest version, with a trigger for when an update appears and menu items to check for updates and report what is waiting. Nothing updates unless you ask.

## 2.3.0 — 14 August 2026

Device settings that stay put. Each device's settings window has a **Device Settings** section for the settings it keeps in its own memory. Set a value there and the plugin notices when the device loses it — after a battery change, say — and puts it back.

## 2.2.0 — 14 August 2026

Devices on mains power no longer show a battery reading of 0%, which looked like a flat battery. The plugin's code was also reorganised into smaller parts, with no change in use.

## 2.1.1 — 14 August 2026

The plugin has an icon.

## 2.1.0 — 14 August 2026

- Battery devices fill in Indigo's own battery level, and plugs that measure power and energy report into Indigo's own energy readings, including resetting the energy total.
- A device zigbee2mqtt reports offline turns red in Indigo.
- zigbee2mqtt's health report comes in, with **Report Network Health** in the Plugins menu.
- The first triggers: devices joining, leaving, announcing themselves, being set up or failing to be, rejoining or changing network address, and zigbee2mqtt going offline, coming back or needing a restart.

## 2.0.3 — 8 August 2026

The **About** item in the Plugins menu opens this project's page. It went nowhere before.

## 2.0.2 — 21 July 2026

Log lines no longer come out with the time printed twice.

## 2.0.1 — 21 July 2026

Warnings and errors appear in the Event Log as warnings and errors. Before, they all appeared as ordinary lines.

## 2.0.0 — 16 July 2026

The plugin moved to the newer version of the MQTT library it uses. Nothing changed in use.

## 1.10.0 — 16 July 2026

- New **Z2M Lock** and **Z2M Thermostat / TRV** device kinds, so locks lock and unlock and radiator valves work as Indigo thermostats.
- New **Publish Custom Payload** action, for sending a device any setting zigbee2mqtt understands.
- New menu items to open and close pairing, test the connection, and list devices zigbee2mqtt no longer knows about.
- Each device shows when zigbee2mqtt last heard from it.
- A broker that cannot be reached, or turns away the password, is reported once rather than not at all or over and over.

## 1.9.21 to 1.9.23 — 16 July 2026

Fixes from a full review.

- A wall switch that also sends scene presses is made a relay, so its load can be switched from Indigo.
- Smoke alarms reach Indigo. Before, an alarm changed nothing.
- Readings on devices of another kind, such as a door sensor's temperature, are no longer lost.
- Radiator valves are no longer made as blinds, and two devices with the same name on two zigbee2mqtt set-ups are kept apart.
- Colour bulbs report full colour correctly, and a command that could not be sent says so.
- On a quiet network the plugin checks the connection before rebuilding it, and the time it waits is a setting.

## 1.9.20 — 27 June 2026

Fixes from a review, all behind the scenes. A bulb that reports zero brightness shows as off, and colour readings reach a full 100%.

## 1.9.18 and 1.9.19 — 26 June 2026

- A presence sensor that also reports events, such as the Aqara FP1, could be rebuilt as a button, which broke anything pointing at it. That can no longer happen.
- Remotes with many buttons have their presses named, and anything else shows as **Other**.
- Bulbs that change only their shade of white get that control as soon as they are created.
- **Refresh Device State** works on every kind of sensor.
- The plugin reconnects more smoothly after the Mac wakes.

## 1.9.17 — 13 June 2026

A device that reports both presence and button events, such as the Aqara FP1, is made a presence sensor rather than a button.

## 1.9.16 — 10 June 2026

The plugin installs faster and takes up less space, because it no longer needs a large colour library. Nothing changed in use.

## 1.9.15 — 6 June 2026

**Send Status Request** works everywhere, a dimmer or switch that also sends scene presses is no longer rebuilt as a button, and one bad reading no longer throws away the rest of a device's update.

## 1.9.14 — 29 May 2026

The plugin notices when its connection to the broker has stopped working without saying so, and makes a new one.

## 1.9.13 — 28 May 2026

The extra readings a device sends are kept as numbers, words or tick boxes to match, rather than all as words.

## 1.9.12 — 28 May 2026

A trigger can run on a particular kind of button press — single, double, hold and so on — straight from Indigo's trigger window.

## 1.9.11 — 27 May 2026

The plugin disconnects from the broker cleanly when the Mac sleeps, and reconnects when it wakes.

## 1.9.8 to 1.9.10 — 25 May 2026

**Send Status Request** works on sensors, and the plugin no longer restarts a device every time it stores something about it.

## 1.9.7 — 23 May 2026

Every log line starts with the time to the thousandth of a second, with a menu item to turn that off.

## 1.9.6 — 23 May 2026

The broker's address, port, username and password can be typed into the plugin's settings window, as well as kept in `IndigoSecrets.py`.

## 1.9.0 to 1.9.5 — 22 May 2026

- New **Z2M Coordinator** device, one for each zigbee2mqtt, with **Create Coordinator Devices** to make it.
- New **Refresh Device Capabilities** menu item.
- Older sensors are given the right Indigo type, so HomeKit plugins see them as the right kind of accessory.

## 1.8.0 — 22 May 2026

Every device is given the right Indigo type — dimmer, outlet, door and window sensor, motion sensor, temperature sensor or blind — so Indigo shows the right icon. Temperature sensors and buttons show their most useful reading in the device list.

## 1.7.2 — 13 May 2026

A missing entry in `IndigoSecrets.py` no longer blanks the other broker details.

## 1.7 and 1.7.1 — 10 May 2026

Every reading a device sends comes into Indigo, and a device only shows the readings it actually has.

## 1.6 — 29 April 2026

New **Z2M Button / Scene** device kind, with the last press, the button number and a count of presses.

## 1.5 — 13 April 2026

SMLIGHT SLZB coordinator boxes are recognised as repeaters.

## 1.4 — 13 April 2026

New **Z2M Repeater** device kind, which shows online or offline.

## 1.3 — 11 April 2026

- New devices paired in zigbee2mqtt are created in Indigo by themselves, and renaming a device in zigbee2mqtt renames it in Indigo.
- A second zigbee2mqtt, such as one in a garage, can feed the same plugin.
- New contact, occupancy, water leak and temperature sensor kinds.

## 1.0 — 6 April 2026

The first release, with lights, relays, sensors and blinds.

Versions not listed here were not recorded.
