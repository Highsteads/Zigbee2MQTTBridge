---
title: Getting started
nav_order: 2
---

# Getting started

This takes about ten minutes, and you only do it once.

## What you need

- Indigo 2023.2 or later.
- **zigbee2mqtt already running**, with your Zigbee devices paired to it. If you can see and switch your devices in zigbee2mqtt's own web page, you are ready.
- **An MQTT broker** that zigbee2mqtt is already sending its messages to, such as Mosquitto. You need its **network address** — the four numbers separated by dots, such as `192.168.1.10`, of the computer it runs on — and, if you set one up, its username and password. If the broker runs on the same Mac as Indigo, that Mac's own address is the one to use.
- zigbee2mqtt's **base topic** — the word it starts every message with. Unless you changed it when you set zigbee2mqtt up, it is `zigbee2mqtt`.

The plugin needs one extra piece of software, the MQTT library it uses to talk to the broker. Indigo downloads and installs it by itself the first time the plugin starts, so there is nothing for you to do.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/Zigbee2MQTTBridge/releases/latest) and download `Zigbee2MQTTBridge.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Zigbee2MQTTBridge.indigoPlugin`
3. Double-click `Zigbee2MQTTBridge.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes.

## 2. Tell the plugin where the broker is

Open **Plugins → Zigbee2MQTT Bridge → Configure**.

1. Type the broker's network address into **Broker Host**.
2. If your broker has a username and password, fill in **Username** and **Password**. If it has none, leave them blank.
3. Check **Topic Prefix** matches zigbee2mqtt's base topic. It is `zigbee2mqtt` to start with, which is right for most people.
4. If you run a second zigbee2mqtt, as I do for the garage, type its base topic into **Garage Topic Prefix**. Otherwise leave it blank.
5. Click **Save**.

The plugin connects on port 1883, the usual one for a broker. If yours uses a different port, type it into **Broker Port** in the same window. The [Settings](settings.md) page explains every setting.

## 3. Bring in your devices

Give the plugin a few seconds to connect and fetch zigbee2mqtt's list of devices. The Event Log shows a line such as **Bridge device cache updated: 52 device(s) total** when it has the list.

Then choose **Plugins → Zigbee2MQTT Bridge → Discover & Create Devices**.

The plugin makes an Indigo device for every Zigbee device that does not have one yet, names each one the same as in zigbee2mqtt, and puts them all in a **Zigbee2MQTT** folder in Indigo's device list. The Event Log lists each device it creates and finishes with a count, such as **Discover & Create complete: 52 created, 0 already existed**.

You can run it again at any time — it never makes a second copy of a device.

## 4. Add a device for zigbee2mqtt itself (optional)

Choose **Plugins → Zigbee2MQTT Bridge → Create Coordinator Devices**. This adds one device for each zigbee2mqtt you run, named **Z2M Bridge (zigbee2mqtt)**, which shows whether zigbee2mqtt is online, its version, whether pairing is open, and how hard the computer running it is working. The [Your devices](devices.md) page has the full list.

## 5. Check it works

Switch a light or plug from Indigo and it should change straight away. Switch it from zigbee2mqtt's own page, or at a wall switch, and Indigo should show the change within a second or two. Open a door with a contact sensor on it and the Indigo device should say **Open**.

If nothing appears, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.

## Adding more devices later

Pair the new device in zigbee2mqtt as you normally would, or open pairing from Indigo with **Plugins → Zigbee2MQTT Bridge → Enable Pairing (Permit Join, 254s)**. Once zigbee2mqtt has finished setting the new device up, the plugin creates its Indigo device by itself, in the same folder. If one is ever missed, **Discover & Create Devices** picks it up.
