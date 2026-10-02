---
title: The plugin menu
nav_order: 8
---

# The plugin menu

These are under **Plugins → Zigbee2MQTT Bridge**. Most of them write their answer to the Indigo Event Log.

## Devices

| Menu item | What it does |
|---|---|
| **Discover & Create Devices** | Makes an Indigo device for every Zigbee device zigbee2mqtt knows about that does not have one yet, and puts them in the **Zigbee2MQTT** folder, along with a device for each zigbee2mqtt group of lights or switches. It never makes a second copy, so it is safe to run at any time. A device zigbee2mqtt has not finished setting up is skipped, and named in the log. |
| **Create Coordinator Devices** | Makes one **Z2M Coordinator** device for each zigbee2mqtt you connect, named such as **Z2M Bridge (zigbee2mqtt)**, if it does not have one already. |
| **Refresh Device List from MQTT** | Asks the MQTT broker to send zigbee2mqtt's list of devices again, so the plugin catches up without a restart. If no list arrives within half a minute, the log says so. |
| **Refresh Device Capabilities** | Looks again at what each of your existing Zigbee devices can do, and corrects what the plugin has stored — whether a bulb can change colour, say, and the Indigo type that goes with it. Your devices keep their names, and every trigger and control page pointing at them carries on working. Use it after a zigbee2mqtt update has changed how it describes a device. |
| **Report Orphaned Devices** | Lists any Indigo device whose Zigbee device zigbee2mqtt no longer knows about — removed, or paired again under a new identity. It only reports, it never deletes anything. |
| **Report Network Health** | Lists, for each zigbee2mqtt, how long it has been running, how hard its computer is working, and which devices have dropped off the network and joined again or taken a new network address, worst first. It needs zigbee2mqtt's health report, which arrives every ten minutes. |
| **Report Network Map...** | Has zigbee2mqtt ask every router which devices it can hear, then writes a report to the log: devices with no route or a weak one first, then each router with how many devices rely on it, then every device and the router it talks through, weakest first. A light that devices rely on is pointed out, because switching it off at the wall cuts them off. zigbee2mqtt asks the routers a second apart, so a large network takes a few minutes — mine took just over two. Run it now and then, not every hour. |

## Firmware

| Menu item | What it does |
|---|---|
| **Check for Firmware Updates** | Asks zigbee2mqtt to check every device that can take updates. It only looks, it installs nothing. Battery devices answer when they next wake. |
| **Report Firmware Status** | Lists every device that can take updates, its version, the newest version, and whether an update is waiting. |
| **Update Device Firmware...** | Lets you pick a device with an update waiting and install it, now or the next time the device asks for one — the better choice for a battery device. The [Firmware updates](firmware-updates.md) page explains what to expect. |
| **Cancel Firmware Update...** | Cancels a scheduled update, or stops one that is installing. |

## Looking after zigbee2mqtt

| Menu item | What it does |
|---|---|
| **Back Up zigbee2mqtt...** | Saves zigbee2mqtt's settings and list of devices — everything you would need to set it up again on new hardware — to the backup folder set in **Configure**, for one zigbee2mqtt or all of them. It takes up to a minute, and the log says where the file went. The file holds your Zigbee network's key, so it is saved where only your Mac account can read it. |
| **Check for Missing Routers...** | Asks zigbee2mqtt whether any router — a mains-powered device that passes messages on — has stopped answering, usually because it has been unplugged or switched off at the wall. The log names any it finds, and so does the coordinator device. It can take a minute or two on a big network. |
| **Set Up a Device Again...** | Asks zigbee2mqtt to run a device's setup again, as when it first paired. Try it on a device that has stopped reporting. A battery device must be awake: press its button or set off its sensor first. |
| **Restart zigbee2mqtt...** | Restarts the zigbee2mqtt you choose. Every device on it stops answering for about half a minute. |

## Pairing

| Menu item | What it does |
|---|---|
| **Enable Pairing (Permit Join, 254s)** | Lets new devices join, on every zigbee2mqtt you connect, for 254 seconds — a little over four minutes, the longest zigbee2mqtt allows. The coordinator device's **Permit Join** shows it has worked. |
| **Disable Pairing (Permit Join Off)** | Stops new devices joining, on every zigbee2mqtt you connect, straight away. |

## Log and help

| Menu item | What it does |
|---|---|
| **Toggle Timestamps in Log (on/off)** | Every line the plugin writes to the log starts with the time to the thousandth of a second, which helps when lining events up. This turns that on or off. It is on to start with and stays as you leave it. |
| **Test MQTT Connection** | Writes the plugin's version and details of your Mac and Indigo to the log, then checks that a broker is set, that the plugin is connected to it, that messages are arriving, and that each zigbee2mqtt says it is online. It ends with **Connection test PASSED**, or a line for each thing that failed. It is the thing to include if you ask for help on the Indigo forum. |
| **Show Plugin Info** | Writes the plugin's version and details of your Mac and Indigo to the log. |
