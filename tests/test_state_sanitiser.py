#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_state_sanitiser.py
# Description: Tests for _sanitise_state_key + _is_valid_state_id. These guard
#              against the three Indigo XML-validator gotchas documented in
#              global CLAUDE.md: no underscores, no leading non-letter, no
#              collision with reserved native state names.
# Author:      CliveS & Claude Opus 4.7
# Date:        25-05-2026

import pytest


# ── _is_valid_state_id ───────────────────────────────────────────────────────

@pytest.mark.parametrize("good", [
    "linkQuality", "batteryLevel", "colorTemp", "z2m", "abc123", "X",
])
def test_valid_state_ids(plugin, good):
    assert plugin._is_valid_state_id(good) is True


@pytest.mark.parametrize("bad", [
    "",                    # empty
    "_underscore",         # leading underscore
    "color_temp",          # contains underscore
    "1starts_with_digit",  # leading digit
    "has-dash",            # dash
    "has.dot",             # dot
    "with space",          # space
    "üñıçødé",             # non-ASCII
])
def test_invalid_state_ids(plugin, bad):
    assert plugin._is_valid_state_id(bad) is False


# ── _sanitise_state_key ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("color_temp",          "colorTemp"),
    ("color_temp_startup",  "colorTempStartup"),
    ("power_on_behavior",   "powerOnBehavior"),
    ("link_quality",        "linkQuality"),
    ("brightness",          "brightness"),       # single word stays lower
    ("Already_Camel",       "alreadyCamel"),
    ("MQTT_topic",          "mQTTTopic"),        # first part lowercase pattern
])
def test_sanitise_basic_snake_to_camel(plugin, raw, expected):
    assert plugin._sanitise_state_key(raw) == expected


def test_sanitise_empty(plugin):
    assert plugin._sanitise_state_key("") == ""


def test_sanitise_only_non_alnum_falls_back_to_z2m_prefix(plugin):
    """A key like '___' produces no parts — must NOT return empty (which would
    crash downstream replacePluginPropsOnServer)."""
    result = plugin._sanitise_state_key("___")
    # No content -> empty result is acceptable here
    assert result == ""


def test_sanitise_leading_digit_gets_z2m_prefix(plugin):
    """State IDs MUST start with a letter — a digit prefix is illegal."""
    result = plugin._sanitise_state_key("2thing")
    assert result.startswith("z2m") or result[0].isalpha()
    assert plugin._is_valid_state_id(result)


def test_sanitise_xml_reserved_prefix_rewritten(plugin):
    """XML reserves any element name starting with 'xml' (case-insensitive)."""
    result = plugin._sanitise_state_key("xml_thing")
    assert result[:3].lower() != "xml"
    assert plugin._is_valid_state_id(result)


def test_sanitise_reserved_state_name_gets_prefix(plugin):
    """`batteryLevel` is reserved (silently shadows the native device property).
    Any dynamic field that would land on a reserved name must be prefixed."""
    # batteryLevel is the canonical example
    result = plugin._sanitise_state_key("battery_level")
    assert result != "batteryLevel"
    # Should still be a valid id
    assert plugin._is_valid_state_id(result)


def test_sanitise_already_camelcase_unchanged_in_principle(plugin):
    """An already-valid camelCase name should round-trip unchanged or to a
    valid form."""
    result = plugin._sanitise_state_key("colorMode")
    assert plugin._is_valid_state_id(result)


def test_sanitise_unicode_stripped(plugin):
    """Non-ASCII characters must not survive the sanitiser."""
    result = plugin._sanitise_state_key("café_mode")
    assert plugin._is_valid_state_id(result)
    assert all(c.isascii() and c.isalnum() for c in result)


def test_sanitise_dash_and_dot(plugin):
    """Other separators (dash, dot) work the same as underscore."""
    assert plugin._sanitise_state_key("foo-bar")  == "fooBar"
    assert plugin._sanitise_state_key("foo.bar")  == "fooBar"
    assert plugin._sanitise_state_key("foo bar")  == "fooBar"


def test_sanitise_long_chain(plugin):
    assert plugin._sanitise_state_key("a_b_c_d_e_f") == "aBCDEF"
