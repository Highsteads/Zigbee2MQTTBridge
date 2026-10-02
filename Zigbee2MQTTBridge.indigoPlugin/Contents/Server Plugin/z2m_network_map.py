#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    z2m_network_map.py
# Description: Report Network Map (v2.17.0) — who each Zigbee device talks
#              through, how well, and what needs attention, in plain words.
#
#              zigbee2mqtt's web page draws the network as a picture; Home
#              Assistant's ZHA, Node-RED and Homey do much the same. In Indigo
#              the useful form is the answer to "why does that sensor keep
#              dropping out", written to the log.
#
#              Facts it rests on, from zigbee2mqtt 2.14.2 networkMap.ts and two
#              live scans here on 02-10-2026:
#              * bridge/request/networkmap {"type": "raw", "routes": true} is
#                answered on bridge/response/networkmap, transaction echoed,
#                with data.value = {nodes, links}. It is not retained.
#              * Each router (and the coordinator) is asked for its neighbour
#                table. Every entry becomes a link whose TARGET is the router
#                that was asked and whose SOURCE is the neighbour, so `lqi` is
#                how well the target hears the source (0-255). `relationship`
#                is the source's role to the target: 0 parent, 1 child,
#                2 sibling, 3 none (4+ are dropped by zigbee2mqtt).
#              * A device that does not pass messages on (an "EndDevice" —
#                mostly battery sensors) is never asked: its place shows as a
#                link where it is a router's CHILD.
#              * A router that does not answer has `failed` on its node and
#                none of its links.
#              * zigbee2mqtt waits a second between routers: the house network
#                (17 routers) took 130 s, the garage (2) took 4 s.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

import z2m_helpers

try:
    import indigo  # noqa: F401  — injected by the plugin host at runtime
except ImportError:
    indigo = None


def log(*args, **kwargs):
    return z2m_helpers.log(*args, **kwargs)


WEAK_LQI = 50      # out of 255; below this a link is worth knowing about
CHILD = 1


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def summarise_network_map(value, name_of, is_light=lambda ieee: False):
    """Turn a raw network map into what a person needs to know.

    name_of(ieee, zigbee2mqtt name) -> the name to show.
    is_light(ieee) -> True when that router is a light, which someone may
    switch off at the wall, taking its devices' route with it.

    Returns a dict:
      counts:       {"Coordinator": n, "Router": n, "EndDevice": n}
      no_route:     [name]                 devices no router lists as a child
      not_scanned:  [name]                 routers that did not answer
      weak:         [(name, via, lqi)]     devices on a link below WEAK_LQI
      devices:      [(name, via, lqi)]     every end device, weakest first
      routers:      [(name, dependants, coordinator hears it or None, is light,
                      answered the scan)]
    """
    nodes = {}
    for node in (value or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("ieeeAddr"):
            nodes[node["ieeeAddr"]] = node
    links = [l for l in (value or {}).get("links") or [] if isinstance(l, dict)]

    def name(ieee):
        return name_of(ieee, (nodes.get(ieee) or {}).get("friendlyName") or ieee)

    def lqi(link):
        try:
            return int(link.get("lqi", link.get("linkquality")))
        except (TypeError, ValueError):
            return 0

    counts = {"Coordinator": 0, "Router": 0, "EndDevice": 0}
    for node in nodes.values():
        if node.get("type") in counts:
            counts[node["type"]] += 1
    coordinator = next((i for i, n in nodes.items() if n.get("type") == "Coordinator"), None)

    # Each end device's best parent: the router that hears it best.
    parent = {}
    dependants = {}
    for link in links:
        src = (link.get("source") or {}).get("ieeeAddr")
        dst = (link.get("target") or {}).get("ieeeAddr")
        if link.get("relationship") != CHILD or src not in nodes:
            continue
        if nodes[src].get("type") != "EndDevice":
            continue
        if src not in parent or lqi(link) > parent[src][1]:
            parent[src] = (dst, lqi(link))
    for child, (via, _q) in parent.items():
        dependants[via] = dependants.get(via, 0) + 1

    devices, no_route = [], []
    for ieee, node in nodes.items():
        if node.get("type") != "EndDevice":
            continue
        if ieee in parent:
            via, quality = parent[ieee]
            devices.append((name(ieee), name(via), quality))
        else:
            no_route.append(name(ieee))
    devices.sort(key=lambda r: (r[2], r[0].lower()))
    weak = [row for row in devices if row[2] < WEAK_LQI]

    routers, not_scanned = [], []
    for ieee, node in nodes.items():
        if node.get("type") != "Router":
            continue
        if node.get("failed"):
            not_scanned.append(name(ieee))
        heard = [lqi(l) for l in links
                 if (l.get("target") or {}).get("ieeeAddr") == coordinator
                 and (l.get("source") or {}).get("ieeeAddr") == ieee]
        routers.append((name(ieee), dependants.get(ieee, 0),
                        max(heard) if heard else None, bool(is_light(ieee)),
                        not node.get("failed")))
    routers.sort(key=lambda r: (-r[1], r[0].lower()))

    return {"counts": counts, "no_route": sorted(no_route, key=str.lower),
            "not_scanned": sorted(not_scanned, key=str.lower), "weak": weak,
            "devices": devices, "routers": routers}


class NetworkMapMixin:
    """See the file header above."""

    def _start_network_maps(self, prefixes):
        asked = [p for p in prefixes
                 if self._bridge_request(p, "networkmap", {"type": "raw", "routes": True})]
        if asked:
            log(f"Asked zigbee2mqtt on {', '.join(repr(p) for p in asked)} to map the "
                f"Zigbee network. It asks every router in turn, a second apart, so it "
                f"takes a few minutes on a large network; the report follows in the log.")

    def menu_network_map(self, valuesDict=None, typeId=None):
        prefixes = self._chosen_prefixes((valuesDict or {}).get("bridge"))
        if not prefixes:
            log("No zigbee2mqtt chosen to map.", level="WARNING")
        else:
            self._start_network_maps(prefixes)
        return True

    def action_network_map(self, action):
        self._start_network_maps(self._chosen_prefixes(action.props.get("bridge")))

    def _map_name(self, ieee, fallback):
        with self.maps_lock:
            dev_id = self.ieee_map.get(ieee)
        if dev_id is not None:
            try:
                return indigo.devices[dev_id].name
            except KeyError:
                pass
        return str(fallback)

    def _map_is_light(self, ieee):
        with self.maps_lock:
            dev_id = self.ieee_map.get(ieee)
        try:
            return indigo.devices[dev_id].deviceTypeId == "z2mLight"
        except (KeyError, TypeError):
            return False

    def _report_network_map(self, prefix, data, ok, error, seconds=None):
        if not ok:
            log(f"zigbee2mqtt on '{prefix}' could not map the network: {error}",
                level="WARNING")
            return
        summary = summarise_network_map((data or {}).get("value"), self._map_name,
                                        self._map_is_light)
        counts = summary["counts"]
        took = f" The scan took {round(seconds)} seconds." if seconds else ""
        log(f"Zigbee network map for '{prefix}': the coordinator, "
            f"{_plural(counts['Router'], 'router')} that pass messages on, and "
            f"{_plural(counts['EndDevice'], 'device')} that only talk to a router "
            f"near them, mostly battery sensors.{took}")

        trouble = 0
        for name in summary["no_route"]:
            trouble += 1
            log(f"  {name}: no router lists it, so it has no route at the moment. "
                f"It may be offline, or have lost its place in the network.",
                level="WARNING")
        for name, via, quality in summary["weak"]:
            trouble += 1
            log(f"  {name}: talks through {via}, and the link is weak "
                f"({quality} out of 255). Moving one of them, or adding a router "
                f"between them, would help.", level="WARNING")
        for name in summary["not_scanned"]:
            trouble += 1
            log(f"  {name} did not answer the scan, so its links are missing from "
                f"this map.", level="WARNING")
        if not trouble:
            log("  Nothing needs attention: every device has a route and every "
                "link is reasonable.")

        log("  Routers, busiest first:")
        for name, count, heard, light, answered in summary["routers"]:
            if not answered:
                # Its own table is missing, so what relies on it is unknown —
                # "no devices rely on it" would be a guess dressed as a fact.
                log(f"    {name}: did not answer the scan, so what relies on it is "
                    f"not known.")
                continue
            parts = [f"{_plural(count, 'device')} {'relies' if count == 1 else 'rely'} on it"
                     if count else "no devices rely on it"]
            parts.append(f"the coordinator hears it at {heard} out of 255"
                         if heard else "it is out of the coordinator's direct reach")
            line = f"    {name}: " + ", and ".join(parts) + "."
            if light and count:
                line += (" It is a light — switch it off at the wall and those "
                         "devices must find another way.")
            log(line)

        log("  Devices, weakest link first:")
        for name, via, quality in summary["devices"]:
            log(f"    {name}: through {via}, at {quality} out of 255.")
