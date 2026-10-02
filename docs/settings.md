---
title: Settings
nav_order: 7
---

# Settings

## The plugin's settings

Open these with **Plugins → Zigbee2MQTT Bridge → Configure**. When you click **Save**, the plugin reconnects to the broker with the new settings.

### MQTT Broker

| Setting | What it does |
|---|---|
| **Broker Host** | The network address of your MQTT broker, such as `192.168.1.10`, or its name on your network. The plugin cannot connect until this is filled in, here or in the shared settings file described below. |
| **Broker Port** | The port the broker listens on, 1883 to start with, which is the usual one. If your broker listens on another port, type it here. A port in the shared settings file described below is used ahead of this one. |
| **Username** | The broker's username, if it has one. Leave it blank if your broker does not ask for one. |
| **Password** | The broker's password, if it has one. |

### Topic Configuration

| Setting | What it does |
|---|---|
| **Topic Prefix** | zigbee2mqtt's base topic — the word it starts every message with. It is `zigbee2mqtt` to start with, which matches zigbee2mqtt's own starting setting. It must match exactly, or the plugin hears nothing. It cannot be left blank. It can have several parts separated by `/`, such as `house/zigbee2mqtt`, but not `+` or `#`. |
| **Garage Topic Prefix** | If you run a second zigbee2mqtt, its base topic, such as `zigbee2mqtt_garage`. I use this for a second Zigbee radio in the garage. Leave it blank if you run only one. Devices on both come into the same plugin, and two devices with the same name on the two are kept apart. The two prefixes must be different, and one cannot start with the other, such as `zigbee2mqtt` and `zigbee2mqtt/garage`. |

### zigbee2mqtt Backups

| Setting | What it does |
|---|---|
| **Backup Folder** | Where **Back Up zigbee2mqtt** saves its files. Leave it blank for a folder called **Zigbee2MQTT Backups** in `/Library/Application Support/Perceptive Automation`, beside your Indigo folder, so Time Machine keeps a copy and an Indigo upgrade leaves it alone. A backup holds your Zigbee network's key, so do not choose a shared folder, and it refuses anything under **Web Assets**, which anyone on your network can download from. |
| **Backups to Keep** | For each zigbee2mqtt, how many backups to keep. It is 10 to start with. The oldest is deleted when a new one is saved, and only files this plugin made are ever deleted. |

### Advanced

| Setting | What it does |
|---|---|
| **Watchdog Silence Limit (s)** | How many seconds can pass with no message from the broker before the plugin checks the connection, and makes a new one if the check gets no answer. It is 300 — five minutes — to start with, and cannot be less than 60. Raise it on a small or quiet Zigbee network where several minutes can pass with no messages. [How it works](how-it-works.md) explains more. |
| **Log Routine Activity to the Event Log** | Every command the plugin sends, each status request, devices announcing themselves and the steps of connecting to the broker are written to the plugin's own log file. Tick this to see them in the Indigo Event Log as well. It is off to start with. Warnings and errors always appear in the Event Log whatever this is set to. |
| **Show Debug Info in Event Log** | Adds a great deal of detail to the Event Log, including the routine activity above. Only useful when chasing a problem. |

The plugin's own log file is in Indigo's **Logs** folder, in a folder named `com.clives.indigoplugin.z2mbridge`, and is called `plugin.log`. It is the place to look if a light did not respond, because it records every command the plugin sent.

### Keeping the broker details in one file

If you run several of my plugins, you can keep the broker's details in one shared file instead of typing them into this plugin. The file is called `IndigoSecrets.py` and lives in `/Library/Application Support/Perceptive Automation/`.

1. Find `IndigoSecrets_example.py` inside the plugin. In the Finder, right-click the `Zigbee2MQTTBridge.indigoPlugin` you downloaded, choose **Show Package Contents**, and look in **Contents → Server Plugin**.
2. Copy it to `/Library/Application Support/Perceptive Automation/` and rename the copy `IndigoSecrets.py`. If you already have an `IndigoSecrets.py` from another of my plugins, add the four lines below to it instead.
3. Open it in a text editor and fill in the four lines with your own details:

```
MQTT_BROKER   = "192.168.1.10"
MQTT_PORT     = 1883
MQTT_USERNAME = ""
MQTT_PASSWORD = ""
```

Leave the username and password as `""` if your broker has none.

When the file has a value, it is used, whatever the Configure window says. Any value the file leaves blank, or leaves out, is taken from the Configure window instead, and the port is 1883 only when neither gives one. The plugin reads the file when it starts, so after changing it, restart the plugin with **Plugins → Zigbee2MQTT Bridge → Reload**.

## Each device's settings

Open these by double-clicking a Zigbee device in Indigo. The plugin fills most of them in itself.

| Setting | What it does |
|---|---|
| **Friendly Name** | The device's name in zigbee2mqtt. It must match exactly, because that is how the plugin finds the device's messages. The plugin fills it in, and changes it by itself if you rename the device in zigbee2mqtt. |
| **IEEE Address** | The device's permanent identity number, which it was made with. It cannot be changed. |
| **Vendor**, **Model** | The make and model zigbee2mqtt reports. |
| **Capabilities** | A summary of what the plugin found the device can do. |

### Device Settings

Some devices have a **Device Settings** section at the bottom. It lists the settings that particular device keeps in its own memory and can report back — sensitivity, delays, how often it reports, and so on — with the allowed range for a number and, where the device has reported it, what it is set to now.

- Choose a value, or type one for a number, and click **Save**. The plugin sends it to the device, unless the device already has it.
- From then on, if the device ever reports something different — after a battery change, say — the plugin writes a warning to the Event Log and sends your value again.
- Leave a setting on **-- not managed --**, or blank, and the plugin leaves it alone. That is how every setting starts.
- A setting that belongs to a group shows the group's name first, such as **Color options: Execute if off**.
- Some number settings also have named choices, listed under the field. A Hue bulb's **Color temp startup**, for one, takes **warm** or **previous**, and **previous** brings the bulb back at the colour it had before the power went off. Type the name or the number.

A battery device only listens while it is awake. If it is asleep when you click **Save**, the plugin sends your setting again the next time the device reports and differs.

[How it works](how-it-works.md) explains why this exists.

### Separate Devices

Some sensors have a **Separate Devices** section, listing readings such as **Temperature** or **Humidity** that can be given a device of their own. Tick one and click **Save**. The [Your devices](devices.md) page explains what happens.

### Coordinator devices

A **Z2M Coordinator** device has one setting, **MQTT Prefix**, which says which zigbee2mqtt it shows. It must match **Topic Prefix** or **Garage Topic Prefix** in the plugin's settings. **Create Coordinator Devices** fills it in.
