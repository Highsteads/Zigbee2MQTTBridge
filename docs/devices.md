---
title: Your devices
nav_order: 3
---

# Your devices

Each Zigbee device becomes one Indigo device. The plugin picks the kind from what zigbee2mqtt says the device can do, so a bulb becomes a light, a door sensor becomes a contact sensor, and so on. This page explains each kind and what it shows.

Each kind is also given the matching Indigo type — dimmer, outlet, door and window sensor, motion sensor, temperature sensor, blind or lock — so Indigo shows the right icon and a HomeKit plugin offers the right kind of accessory.

## What every device shows

Every Zigbee device, whatever its kind, carries these:

| Shown as | What it means |
|---|---|
| **Availability** | **Online** or **Offline**, as zigbee2mqtt reports it. When zigbee2mqtt says a device is offline, the device also turns red in Indigo's device list, and the Event Log says so. It clears by itself when the device is heard from again. |
| **Link Quality** | How well the device's radio signal is coming through, from 0 to 255. Higher is better. |
| **LastSeen** | The date and time zigbee2mqtt last heard from the device, if zigbee2mqtt is set to report it. |
| **Messages / sec**, **Leave Count**, **Network Address Changes** | Figures from zigbee2mqtt's health report, which it sends every ten minutes. Leave Count goes up when a device drops off the network and joins again, and Network Address Changes when it takes a new place in the network. Both count from when zigbee2mqtt last started. |
| **Firmware State**, **Firmware Update Available**, **Installed Firmware**, **Latest Firmware**, **Update Progress %** | Whether a firmware update is waiting, and how one is going. See [Firmware updates](firmware-updates.md). |
| **Battery %** | On a battery device, its charge. The plugin also fills in Indigo's own battery level, so anything in Indigo that looks at battery levels sees it. A device that zigbee2mqtt says runs on mains shows **Mains** here instead of a flat battery. |

**Everything else a device reports comes in too.** Whatever a device sends that is not covered below — a plug's voltage, a sensor's sensitivity setting, a presence sensor's distance reading — appears as its own state on the device the first time the device sends it, named after zigbee2mqtt's own name for it — a plug's power-on setting, for example, appears as **PowerOnBehavior**.

## Z2M Light

For bulbs, lamps and LED strips.

You control it with Indigo's usual **Turn On**, **Turn Off**, **Toggle**, brightness, and, on bulbs that have them, colour and white temperature controls. The device list shows it on or off with its brightness.

| Shown as | What it means |
|---|---|
| **Color Mode** | Whether the bulb is showing a colour or a shade of white. Only on bulbs that can do either. |
| **Color Temp K** | The shade of white, in Kelvin — about 2700 is a warm white, about 6500 a cold daylight white. Only on bulbs that can change it. |

## Z2M Relay

For wall switches, smart plugs and in-wall switch modules. It switches on and off with Indigo's usual controls.

| Shown as | What it means |
|---|---|
| **Power W** | The power the plug is passing right now, in watts. Only on plugs that measure it. |
| **Energy kWh** | The energy used, in kilowatt hours. Only on plugs that measure it. |

A plug that measures power and energy also reports them into Indigo's own energy readings. Indigo's action to reset a device's energy total works too, even though the total itself lives on the plug: the plugin remembers the reading at the moment you reset it and counts on from there.

## Z2M Cover

For blinds, curtains and shutters.

**Turn On** opens it, **Turn Off** closes it, and the brightness level sets how far open it is, from 0 (closed) to 100 (fully open). The device list shows **Open** or **Closed**.

| Shown as | What it means |
|---|---|
| **Cover State** | What the blind last reported: open, closed or stopped. |
| **Tilt** | The angle of the slats, on blinds that have them. |

## Z2M Lock

For Zigbee door locks. Indigo's lock and unlock controls work as you would expect, and the device list shows **Locked** or **Unlocked**.

| Shown as | What it means |
|---|---|
| **Lock State** | The lock's own report of its bolt: locked, unlocked, or not fully locked. A lock that is not fully locked shows as **Unlocked** in the device list. |

## Z2M Thermostat / TRV

For radiator valves and other Zigbee heating controls. It is a real Indigo thermostat, so the room temperature, the heat setpoint and the mode appear in Indigo's usual thermostat controls, and you can change the setpoint and the mode from there. The modes it understands are heat, automatic and off.

| Shown as | What it means |
|---|---|
| **Running State** | Whether the valve is heating right now, as the valve reports it. |
| **Valve Position %** | How far open the valve is, on valves that report it. |

## Z2M Contact Sensor

For door and window sensors. The device list shows **Open** or **Closed**.

| Shown as | What it means |
|---|---|
| **Contact (closed=true)** | Ticked when the two halves of the sensor are together, meaning the door or window is shut. |

## Z2M Occupancy Sensor

For motion sensors and the newer radar presence sensors, which can tell someone is there even when they are sitting still. The device list shows **Detected** or **Clear**.

| Shown as | What it means |
|---|---|
| **Motion (PIR or mmWave)** | Someone has been detected by either kind of sensing. This is what the device list shows. |
| **PIR Occupancy** | Movement seen by an ordinary motion sensor. |
| **mmWave Presence** | Presence seen by a radar sensor. |
| **Illuminance lux**, **Temperature**, **Humidity %** | Light level, temperature and humidity, on sensors that measure them. |

## Z2M Water Leak Sensor

For water and flood sensors. The device list shows **OK**, or **Leak!** when it finds water.

| Shown as | What it means |
|---|---|
| **Water Leak** | Ticked while the sensor detects water. |
| **Temperature** | The temperature, on leak sensors that measure it. |

## Z2M Temperature Sensor

For temperature and humidity sensors and small weather sensors. The device list shows the temperature.

| Shown as | What it means |
|---|---|
| **Temperature C**, **Humidity %**, **Pressure hPa**, **Illuminance lux** | Whichever of these the sensor measures. |

## Z2M Sensor

For any sensor that does not fit one of the kinds above, such as smoke alarms and sensors that measure several different things. It carries whichever of these the device reports:

| Shown as | What it means |
|---|---|
| **Smoke** | Ticked while a smoke alarm is sounding. |
| **Water Leak**, **Motion**, **Contact** | As on the sensors above. |
| **Temperature**, **Humidity %**, **Pressure hPa**, **Illuminance lux** | As on the sensors above. |

The device list shows the most important of these: smoke first, then a water leak, then motion, then a door or window.

Every smoke alarm comes in as a **Z2M Sensor**, even one that also measures temperature and humidity, because this is the kind whose on and off follows the alarm. Versions before 2.11.0 made such an alarm a **Z2M Temperature Sensor**, whose on and off never moves. If you have one, the log shows an error each time it reports smoke. Its **Smoke** reading still works, so a trigger on that still fires. To make it a proper alarm, delete it and run **Discover & Create Devices**, but it gets a new device number, so anything pointing at it must be pointed at the new one.

## Z2M Button / Scene

For wireless buttons, remotes and scene switches. They send a press rather than holding a state, so the device shows the last thing that happened.

| Shown as | What it means |
|---|---|
| **Last Action** | The last press, such as **Single**, **Double**, **Hold** or **Release**, or a remote's own actions such as **Brightness Move Up** or **Arrow Left Click**. Anything the plugin does not have a name for shows as **Other**. This is what the device list shows. |
| **Last Button** | Which button was pressed, on a remote with several. |
| **Press Count** | Goes up by one with every press, so you can trigger on a second press that is the same as the first. |

The [Actions and triggers](actions-and-triggers.md) page shows how to run something on a particular press.

## Z2M Repeater

For Zigbee repeaters and range extenders, and for coordinator boxes such as the SMLIGHT SLZB-06 and SLZB-07 when they act as repeaters. A repeater only passes messages on, so the device list shows **Online** or **Offline** rather than on and off, and it takes no commands.

## Z2M Coordinator

One for each zigbee2mqtt you run, made with **Plugins → Zigbee2MQTT Bridge → Create Coordinator Devices**. The device list shows zigbee2mqtt's status, such as **online**.

| Shown as | What it means |
|---|---|
| **Status** | Whether zigbee2mqtt is online. |
| **Z2M Version**, **Coordinator Type** | The version of zigbee2mqtt and the kind of Zigbee radio it runs. |
| **Permit Join**, **Permit Join End** | Whether pairing is open, and when it closes. |
| **Network Channel**, **PAN ID**, **Extended PAN ID** | The radio channel and identity of your Zigbee network. |
| **Device Count** | How many devices zigbee2mqtt has. |
| **Restart Required** | Ticked when zigbee2mqtt says it needs restarting for a setting to take effect. |
| **Log Level** | How much zigbee2mqtt is writing to its own log. |
| **Last Update** | When the plugin last updated this device. |
| **Host Memory %**, **Host Load (1 min)** | How hard the computer running zigbee2mqtt is working. |
| **Z2M Memory MB**, **Z2M Uptime** | How much memory zigbee2mqtt is using, and how long it has been running. |
| **MQTT Queued**, **MQTT Published**, **MQTT Received** | How many messages zigbee2mqtt has waiting, has sent and has received. |
| **Health Reported** | When zigbee2mqtt last sent its health report, which it does every ten minutes. |
| **Last Event**, **Last Event Device**, **Last Event Time** | The last network event on this zigbee2mqtt — a device joining or leaving, say — which device it was about, and when. |

## Separate devices for extra readings

A presence sensor that also measures temperature, humidity and light keeps all of it on one device. If you would rather have, say, its temperature as a proper Indigo temperature sensor — to show on a control page, or to offer to HomeKit — you can split it out.

Double-click the device, and if it measures anything that can be split out, a **Separate Devices** section at the bottom lists it: **Temperature**, **Humidity**, **Illuminance** or **Pressure**. Tick one and click **Save**.

The plugin makes a new device with the original's name and the reading added, such as **Hall Sensor [Temperature]**, grouped with the original in the device list. The original device keeps everything it had, so every trigger, script and control page pointing at it carries on as before.

If you untick the box later, the plugin does not delete the new device, in case something points at it. It takes it out of the group and adds **[UNUSED** and the date to its name, so you can delete it yourself when you are sure.
