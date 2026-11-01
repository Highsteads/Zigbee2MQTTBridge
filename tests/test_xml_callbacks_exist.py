#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_xml_callbacks_exist.py
# Description: Every method the XML files name must exist on the Plugin class.
#
#              Indigo resolves <CallbackMethod>, <ButtonMethod> and the
#              method="..." of a dynamic list by NAME at the moment the user
#              clicks or opens the dialog. A typo or a method renamed in a
#              refactor is invisible until then — the menu item simply does
#              nothing and an error lands in the Event Log. Since v2.2.0 the
#              plugin is split across mixins, so the check is made against the
#              assembled Plugin class (attributes resolve through the MRO
#              exactly as Indigo sees them), not against plugin.py's text.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SERVER_DIR = (Path(__file__).resolve().parent.parent
              / "Zigbee2MQTTBridge.indigoPlugin" / "Contents" / "Server Plugin")

XML_FILES = ("Actions.xml", "Devices.xml", "Events.xml",
             "MenuItems.xml", "PluginConfig.xml")

# Element text that names a plugin method.
METHOD_ELEMENTS = ("CallbackMethod", "ButtonMethod", "ValidationMethod")


def _referenced_methods():
    """(xml file, method name) for every method an XML file names."""
    found = []
    for name in XML_FILES:
        path = SERVER_DIR / name
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for el in root.iter():
            if el.tag in METHOD_ELEMENTS and (el.text or "").strip():
                found.append((name, el.text.strip()))
            # <List class="self" method="..."> — a dynamic list filled by
            # the plugin. class="indigo.*" lists are Indigo's own and carry
            # a filter, not a method.
            if el.tag == "List" and el.get("class") == "self" and el.get("method"):
                found.append((name, el.get("method")))
    return found


REFERENCED = _referenced_methods()


def test_the_xml_names_some_methods():
    """Guard against the scan silently finding nothing (a path change)."""
    assert len(REFERENCED) > 20, REFERENCED


@pytest.mark.parametrize("xml_file,method", REFERENCED,
                         ids=[f"{f}:{m}" for f, m in REFERENCED])
def test_every_xml_callback_exists_on_the_plugin(plugin_mod, xml_file, method):
    attr = getattr(plugin_mod.Plugin, method, None)
    assert attr is not None, (
        f"{xml_file} names '{method}', but the Plugin class has no such "
        f"method — Indigo would fail when the user uses it")
    assert callable(attr), f"{xml_file}: Plugin.{method} is not callable"
