---
title: When something goes wrong
nav_order: 9
---

# When something goes wrong

Each section starts with what you see, then what it means and what to do. A good first step for almost anything is **Plugins → Zigbee2MQTT Bridge → Test MQTT Connection**, which says in one go whether the plugin is connected and whether zigbee2mqtt is online.

## The log says "MQTT broker not configured yet"

The plugin does not know where your broker is. Fill in **Broker Host** in **Plugins → Zigbee2MQTT Bridge → Configure** and click **Save**, or put the address in `IndigoSecrets.py` as the [Settings](settings.md) page describes.

## The log says "MQTT broker unreachable"

The plugin cannot reach the broker at the address it has.

- Check **Broker Host** is the right address, and that the broker is running.
- If your broker uses a port other than 1883, check **Broker Port** in **Configure**, and the `MQTT_PORT` line if you keep the broker's details in the shared settings file — see [Settings](settings.md).
- The plugin keeps trying by itself, and connects as soon as the broker answers.

If the broker turns away the username or password, the log says **MQTT connect failed** with the broker's reason instead. Check them in **Configure**, or in `IndigoSecrets.py` if you use it, because the file wins over the Configure window.

## Discover & Create Devices says "No bridge device data yet"

The plugin has not yet had zigbee2mqtt's list of devices.

- Wait a few seconds after the plugin starts, then try again.
- Choose **Plugins → Zigbee2MQTT Bridge → Refresh Device List from MQTT** to ask for it.
- Check **Topic Prefix** in **Configure** matches zigbee2mqtt's base topic exactly. If they differ, the plugin connects to the broker but hears nothing from zigbee2mqtt.

## A device was skipped as "not yet interviewed"

zigbee2mqtt has not finished setting the device up after pairing, so the plugin does not yet know what kind of device it is. Wake it — press its button, or set off its sensor — and let zigbee2mqtt finish. The plugin creates the device by itself once zigbee2mqtt has done so, or you can run **Discover & Create Devices** again.

## A device shows "offline" in red

zigbee2mqtt has not heard from it for longer than it allows, and has marked it offline.

- For a battery device, check the battery.
- Check it has power, and is not too far from the nearest mains-powered Zigbee device, which passes messages on.
- A device that drops off and comes back often shows up in **Plugins → Zigbee2MQTT Bridge → Report Network Health**.

The red clears by itself when the device is heard from again.

## A light or plug does not respond

- Look in the Event Log for a line saying the command was **not delivered**. If there is one, the plugin could not reach the broker — see the sections above.
- If there is no such line, the command reached zigbee2mqtt. Check whether the device responds from zigbee2mqtt's own web page. If it does not, the trouble is between zigbee2mqtt and the device, often power or range.
- The plugin's own log file records every command it sent. The [Settings](settings.md) page says where it is.

## A device has come in as the wrong kind

Choose **Plugins → Zigbee2MQTT Bridge → Refresh Device Capabilities**, which looks again at what each device can do and corrects what it can without replacing the device.

If it is still wrong, you can delete the Indigo device and run **Discover & Create Devices** to make it again. That gives it a new identity in Indigo, so any trigger, script or control page that used the old one has to be pointed at the new one.

## A button trigger does not run on a second press

A trigger on **Button Action** runs when the kind of press changes, so the second of two identical presses does not run it. Trigger on **Press Count** changing instead, which goes up with every press. The [Actions and triggers](actions-and-triggers.md) page shows how.

## A setting sent to a battery device does not take

Battery devices only listen while they are awake. Press the device's button or set off its sensor, then send the setting again. If you set it in the device's **Device Settings** section instead, the plugin sends it again by itself each time the device reports something different.

## The log keeps saying "MQTT silent" and "rebuilding connection"

On a small or quiet Zigbee network, five minutes can pass with no messages at all, and the plugin takes the quiet for a lost connection. Raise **Watchdog Silence Limit (s)** in **Configure** — 900, fifteen minutes, is a reasonable start.

## Report Network Health says "No health data yet"

zigbee2mqtt sends its health report every ten minutes, so wait for the next one. If none ever arrives, check that the health report is switched on in zigbee2mqtt's own settings.

## Still stuck?

Choose **Plugins → Zigbee2MQTT Bridge → Test MQTT Connection**, copy the lines it writes to the Event Log, and post them on the [Indigo forum](https://forums.indigodomo.com) with a description of what you see. You can also [raise an issue on GitHub](https://github.com/Highsteads/Zigbee2MQTTBridge/issues).
