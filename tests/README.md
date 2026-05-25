# Zigbee2MQTT Bridge — Test Suite

A pytest-based unit test suite for the plugin. Runs **without Indigo** — an
``indigo`` module stub stands in for the real one, so the suite executes
anywhere Python 3.10+ + pytest are available.

## Running

```bash
cd ~/Documents/GitHub/Zigbee2MQTTBridge
python3 -m pip install pytest         # one-off
python3 -m pytest tests/              # full run
python3 -m pytest tests/ -v           # verbose
python3 -m pytest tests/ -k brightness   # filter by name
```

Expected result: **226 passed**.

## Layout

```
tests/
├── README.md                           ← this file
├── conftest.py                         ← installs indigo stub, exposes fixtures
├── indigo_stub.py                      ← fake `indigo` module
├── test_pure_helpers.py                ← brightness / colour / mireds maths
├── test_device_type_detection.py       ← _detect_device_type matrix
├── test_capabilities.py                ← per-type capability flag detection
├── test_state_sanitiser.py             ← _sanitise_state_key + _is_valid_state_id
├── test_action_dispatch.py             ← actionControl* dispatch (Dimmer/Sensor/Universal)
├── test_state_processing.py            ← _process_*_state per device class
├── test_cover_button_repeater.py       ← cover / button / repeater / availability
├── test_message_routing.py             ← _process_message topic routing
├── test_misc.py                        ← prefix helpers, broker resolution
└── test_edge_cases.py                  ← payload robustness, reserved names, …
```

## Coverage

The suite exercises:

- **Pure helpers** — brightness conversions (both directions, round-trips,
  clamps), kelvin↔mireds, XY→RGB, HS→RGB
- **Device type detection** — every Devices.xml type (z2mLight, z2mRelay,
  z2mContactSensor, z2mOccupancySensor, z2mWaterLeakSensor,
  z2mTemperatureSensor, z2mCover, z2mButton, z2mRepeater, z2mSensor catch-all)
  plus priority rules (light > relay, cover > relay, button > relay,
  repeater model-name overrides exposes)
- **Capability detection** — per-type ``_detect_*_capabilities`` and the
  ``_compute_light_native_flags`` static method (incl. v1.9.3 regression:
  CT-only bulbs need ``SupportsColor=True``)
- **State sanitiser** — Indigo's three undocumented XML rules: no
  underscores, no leading non-letter, no XML-reserved prefix, and the
  reserved-name guard (batteryLevel, brightnessLevel etc.)
- **Action dispatch** — TurnOn/Off/Toggle/RequestStatus for relays, lights,
  covers; SetBrightness/BrightenBy/DimBy clamping; SetColorLevels (CT and
  RGB); the v1.9.8 ``actionControlSensor`` fix (uses ``.sensorAction``,
  not ``.deviceAction``)
- **State processing** — every payload shape for every device class:
  partial payloads, null fields, string-coerced numerics, multi-motion-key
  occupancy sensors, capability self-heal, contact polarity inversion,
  water-leak alarm mapping
- **MQTT routing** — primary vs garage prefix, bridge/devices, bridge/state
  (dict + bare string), bridge/info, availability, friendly_name-with-slash,
  unknown prefix filtering, malformed topic resilience
- **Edge cases / regressions** — non-dict payload guards, unknown device
  silent skip, null color_temp guard, action enum fallback, motion store
  isolation per device, exception_handler with missing traceback

## Adding tests

1. Pick the matching ``test_*.py`` file (or create a new one).
2. Use the ``plugin``, ``plugin_mod``, ``make_device``, ``make_action`` and
   ``fixtures`` fixtures from ``conftest.py``.
3. Patch ``plugin._publish`` when an action method would otherwise send to MQTT.
4. ``make_device(id, name, deviceTypeId, ...)`` registers the device in the
   stub ``indigo.devices`` registry, so plugin code that looks it up by id
   succeeds.

## Limitations

The suite covers the pure / mockable surface area. It does **not** test:

- Real MQTT round-trips (use the plugin against a live broker for that)
- ``runConcurrentThread`` queue draining
- ``stateListOrDisplayStateIdChanged`` interaction with Indigo's parser
- Auto-create flow (``indigo.device.create`` is not stubbed end-to-end)

Those are integration concerns better verified by restarting the live plugin
and watching the event log.
