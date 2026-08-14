#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_helpers.py
# Description: Pure helpers with no plugin state: the log() wrapper and its level
#              mapping, colour-space and brightness conversions, last-seen
#              formatting, payload-boolean coercion and exposes traversal.
#              Extracted from plugin.py in v2.2.0 — it had reached 5,238 lines
#              and every new feature made it worse. Behaviour is unchanged; the
#              names are re-exported from plugin.py so existing imports and the
#              test suite keep working.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

try:
    import indigo  # noqa: F401  — soft, so this module imports outside the host
except ImportError:
    indigo = None

import colorsys
from datetime import datetime

# ── Pure helper functions (no Indigo dependency) ─────────────────────────────

import logging


_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=_lvl(level))


def _xy_to_rgb(x, y):
    """Convert CIE 1931 xy chromaticity to sRGB 0-100 integers.

    Pure-Python since v1.9.16 (colormath dropped): Wide-RGB-D65 matrix (the one
    Philips publish for Hue-class bulbs), negatives clamped, scaled so the
    dominant channel saturates (chromaticity-preserving — xy carries no
    brightness), then sRGB gamma-encoded to match what colormath used to report.
    """
    z = 1.0 - x - y
    Y = 1.0
    X = (Y / y) * x if y > 0 else 0
    Z = (Y / y) * z if y > 0 else 0
    r =  X * 1.656492 - Y * 0.354851 - Z * 0.255038
    g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
    b =  X * 0.051713 - Y * 0.121364 + Z * 1.011530
    r, g, b = (max(0.0, c) for c in (r, g, b))
    peak = max(r, g, b)
    if peak > 1.0:
        r, g, b = r / peak, g / peak, b / peak

    def _gamma(c):
        return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055

    r, g, b = (max(0.0, min(1.0, _gamma(c))) for c in (r, g, b))
    # round() not int() so a fully-saturated channel (0.999 after gamma) reports
    # 100 rather than truncating to 99; clamped for safety.
    return (min(100, round(r * 100)), min(100, round(g * 100)), min(100, round(b * 100)))


def _hs_to_rgb(hue_360, saturation_100):
    """Convert zigbee2mqtt hue (0-360) + saturation (0-100) to sRGB 0-100.

    v1.9.22: saturation divides by 100, not 255 — zigbee2mqtt publishes
    color_hs saturation on a 0-100 scale (herdsman-converters maps the ZCL
    0-254 range to 0-100 at publish time). The old /255 capped Indigo's
    reported saturation at ~39% of actual.

    Hue is wrapped and saturation clamped so a malformed payload (out-of-range
    hue/saturation) can't push colorsys into returning out-of-range channels and
    hence negative or >100 RGB. Mirrors the clamping the xy path already does.
    """
    h = (hue_360 % 360.0) / 360.0
    s = max(0.0, min(1.0, saturation_100 / 100.0))
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    # round() not int() so a fully-saturated channel reports 100 not 99.
    return (max(0, min(100, round(r * 100))),
            max(0, min(100, round(g * 100))),
            max(0, min(100, round(b * 100))))


def _brightness_255_to_100(val):
    """Convert MQTT brightness 0-255 to Indigo 0-100.

    round() not int() (v1.9.23): truncation made the readback one lower than
    the level just set (50% -> 127 -> 49). The old `>= 99 -> 100` fudge existed
    to make z2m's writable max (254) read as full — rounding does that
    naturally (254 -> 99.6 -> 100), so it's just a clamp now."""
    return min(100, round(val / 255 * 100))


def _brightness_100_to_255(val):
    """Convert Indigo 0-100 to MQTT brightness 0-255 (range 1-254)."""
    return max(1, min(254, int(val * 2.55)))


def _kelvin_to_mireds(kelvin):
    """Convert Kelvin to mireds (zigbee2mqtt color_temp)."""
    return round(1_000_000 / max(1, kelvin))


def _mireds_to_kelvin(mireds):
    """Convert mireds to Kelvin."""
    return round(1_000_000 / max(1, mireds))


def _format_last_seen(raw):
    """Format z2m's last_seen (ms-epoch int OR ISO-8601 string, depending on
    the bridge's last_seen config) as a local 'YYYY-MM-DD HH:MM:SS' string.
    Returns None when unparseable."""
    try:
        if isinstance(raw, (int, float)) and raw > 0:
            return datetime.fromtimestamp(raw / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(raw, str) and raw:
            iso = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _payload_bool(val):
    """Coerce a z2m binary payload value to bool, or None if unrecognisable.

    JSON true/false arrive as Python bools, but some devices publish string
    tokens — and raw bool() reads "false"/"OFF"/"0" as True. Numbers follow
    truthiness (0 -> False). Unrecognised strings return None so the caller
    can skip the write rather than guess.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        token = val.strip().lower()
        if token in ("true", "on", "yes", "1"):
            return True
        if token in ("false", "off", "no", "0", ""):
            return False
    return None


def _iter_features(exposes):
    """
    Yield (entry, is_top_level) for every item in exposes, plus recursively
    yield all nested features from any composite entries.
    """
    for entry in exposes:
        if not isinstance(entry, dict):
            continue    # malformed exposes entry — skip, don't abort the caller
        yield entry
        sub = entry.get("features", [])
        if sub:
            yield from _iter_features(sub)
