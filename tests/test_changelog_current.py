#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_changelog_current.py
# Description: docs/changelog.md (the published "Version history" page) must
#              lead with the version Info.plist ships.
#
#              test_version_consistency.py already ties plugin.py and the
#              README to Info.plist. The docs site is a separate page and is
#              the one a user reads, so it gets its own check: a bump that
#              forgets it leaves the site describing an older release.
# Author:      CliveS & Claude
# Date:        01-11-2026
# Version:     1.0

import plistlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLIST = REPO / "Zigbee2MQTTBridge.indigoPlugin" / "Contents" / "Info.plist"
CHANGELOG = REPO / "docs" / "changelog.md"

# "## 2.17.1 — 5 October 2026" (also accepts a plain hyphen or a "v" prefix)
HEADING_RE = re.compile(r"^##\s+v?(\d+(?:\.\d+)+)\b", re.MULTILINE)


def _plist_version():
    with open(PLIST, "rb") as f:
        return str(plistlib.load(f)["PluginVersion"])


def test_changelog_exists():
    assert CHANGELOG.exists(), "docs/changelog.md is missing"


def test_changelog_newest_entry_is_the_shipped_version():
    versions = HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert versions, "docs/changelog.md has no '## <version>' headings"
    assert versions[0] == _plist_version(), (
        f"docs/changelog.md leads with {versions[0]}, "
        f"Info.plist ships {_plist_version()}")


def test_changelog_has_no_duplicate_version_headings():
    versions = HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
    dupes = sorted({v for v in versions if versions.count(v) > 1})
    assert not dupes, f"version(s) listed twice in docs/changelog.md: {dupes}"
