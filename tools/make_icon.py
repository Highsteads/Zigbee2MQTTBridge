#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    make_icon.py
# Description: Generate the Plugin Store icon for Zigbee2MQTTBridge.
#              Matches the house style set by HoneywellEnvisalink — rounded
#              square, deep blue gradient, cyan accents, title above and a
#              subtitle below a central motif.
#
#              The motif is a MESH, not the Zigbee logo: the logo is a
#              registered trademark and must not be reproduced, and a mesh is
#              the more honest picture anyway — this plugin surfaces routers
#              and repeaters, not just a hub with leaves hanging off it.
# Author:      CliveS & Claude Opus 5
# Date:        14-08-2026
# Version:     1.0

import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE   = 512
SS     = 4                      # supersample factor for clean curves
W      = SIZE * SS

NAVY_TOP    = (14, 42, 74)
NAVY_BOTTOM = (10, 26, 48)
CYAN        = (94, 214, 233)
CYAN_DIM    = (58, 150, 178)
WHITE       = (240, 248, 255)
EDGE        = (72, 132, 180)

FONT_DIRS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
]


def font(path_idx, px):
    return ImageFont.truetype(FONT_DIRS[path_idx], px)


def centred(draw, y, text, fnt, fill, tracking=0):
    """Draw horizontally-centred text, optionally letter-spaced."""
    if tracking:
        widths = [draw.textlength(ch, font=fnt) for ch in text]
        total  = sum(widths) + tracking * (len(text) - 1)
        x = (W - total) / 2
        for ch, adv in zip(text, widths):
            draw.text((x, y), ch, font=fnt, fill=fill)
            x += adv + tracking
    else:
        x = (W - draw.textlength(text, font=fnt)) / 2
        draw.text((x, y), text, font=fnt, fill=fill)


# ── Background: vertical gradient, then rounded-square mask ──────────────────
bg = Image.new("RGB", (W, W), NAVY_BOTTOM)
grad = ImageDraw.Draw(bg)
for y in range(W):
    t = y / (W - 1)
    grad.line(
        [(0, y), (W, y)],
        fill=tuple(int(NAVY_TOP[i] + (NAVY_BOTTOM[i] - NAVY_TOP[i]) * t)
                   for i in range(3)),
    )

# Soft glow behind the motif so the mesh sits on a lighter pool.
glow = Image.new("L", (W, W), 0)
ImageDraw.Draw(glow).ellipse(
    [W * 0.18, W * 0.30, W * 0.82, W * 0.80], fill=90)
glow = glow.filter(ImageFilter.GaussianBlur(W * 0.06))
bg = Image.composite(Image.new("RGB", (W, W), (26, 68, 110)), bg, glow)

card = bg.convert("RGBA")
d = ImageDraw.Draw(card)

# ── Mesh motif ───────────────────────────────────────────────────────────────
# One coordinator at the centre, a ring of routers, and — the point of a mesh —
# links between the routers themselves, not only back to the middle.
cx, cy = W / 2, W * 0.545
ring_r = W * 0.205
nodes  = [(cx + ring_r * math.cos(math.radians(a)),
           cy + ring_r * math.sin(math.radians(a)))
          for a in range(-90, 270, 60)]

link_w = int(W * 0.008)
for i, (nx, ny) in enumerate(nodes):
    d.line([(cx, cy), (nx, ny)], fill=CYAN_DIM + (200,), width=link_w)
# Ring links: every other pair, so it reads as a mesh without becoming a wheel.
for i in (0, 2, 4):
    d.line([nodes[i], nodes[(i + 1) % 6]], fill=CYAN_DIM + (150,),
           width=int(link_w * 0.8))

node_r = W * 0.036
for nx, ny in nodes:
    d.ellipse([nx - node_r, ny - node_r, nx + node_r, ny + node_r],
              fill=CYAN + (255,), outline=WHITE + (210,), width=int(W * 0.004))

# Coordinator: larger, white-cored, so the hub is unmistakable.
hub_r = W * 0.062
d.ellipse([cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
          fill=WHITE + (255,), outline=CYAN + (255,), width=int(W * 0.009))
inner = hub_r * 0.42
d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=NAVY_TOP + (255,))

# ── Text ─────────────────────────────────────────────────────────────────────
title = font(0, int(W * 0.098))
centred(d, W * 0.092, "ZIGBEE2MQTT", title, WHITE + (255,), tracking=W * 0.001)

rule_y = W * 0.222
d.line([(W * 0.265, rule_y), (W * 0.735, rule_y)],
       fill=CYAN + (220,), width=int(W * 0.007))

sub = font(1, int(W * 0.082))
centred(d, W * 0.835, "BRIDGE", sub, CYAN + (255,), tracking=W * 0.020)

# ── Rounded-square mask + edge ───────────────────────────────────────────────
mask = Image.new("L", (W, W), 0)
radius = int(W * 0.20)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=radius, fill=255)

icon = Image.new("RGBA", (W, W), (0, 0, 0, 0))
icon.paste(card, (0, 0), mask)

edge = ImageDraw.Draw(icon)
inset = int(W * 0.012)
edge.rounded_rectangle([inset, inset, W - 1 - inset, W - 1 - inset],
                       radius=radius - inset, outline=EDGE + (170,),
                       width=int(W * 0.008))

icon = icon.resize((SIZE, SIZE), Image.LANCZOS)
out = "/private/tmp/claude-501/-Library-Application-Support-Perceptive-Automation/12eae517-53e6-4a9f-b7a5-6dac7f165377/scratchpad/icon.png"
icon.save(out)
print("wrote", out, icon.size, icon.mode)
