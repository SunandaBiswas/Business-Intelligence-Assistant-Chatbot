"""
Colour palettes for the Excel reports, and a small on-screen preview of each.

A palette is a dict of hex colours (no '#'):
  title_bg / title_fg   the title bar        head_bg / head_fg   the header row
  band                  every second row     total_bg / total_fg Grand Total row and column
  border / outline      thin cell borders / the medium outline around the table
  scale_lo / scale_hi   the two ends of the optional colour scale on the values
"""
import io

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

TEXT = "1F2933"


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "%02X%02X%02X" % tuple(int(round(v)) for v in rgb)


def _mix(a, b, t):
    """Blend colour a towards colour b by t (0 = a, 1 = b)."""
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def _luminance(h):
    r, g, b = (v / 255 for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _text_on(bg):
    return "FFFFFF" if _luminance(bg) < 0.5 else TEXT


def make_palette(dark, mid, accent=None):
    """A full palette from a dark colour (title), a mid colour (header) and an optional accent (totals)."""
    return {
        "title_bg": dark, "title_fg": _text_on(dark),
        "head_bg": mid, "head_fg": _text_on(mid),
        "band": _mix(mid, "FFFFFF", 0.93),
        "total_bg": accent or _mix(mid, "FFFFFF", 0.80), "total_fg": TEXT,
        "border": _mix(mid, "FFFFFF", 0.55), "outline": dark,
        "scale_lo": _mix(mid, "FFFFFF", 0.93), "scale_hi": _mix(mid, "FFFFFF", 0.30),
    }


def palette_from_base(base):
    """One colour in, a matching executive palette out (title = darker shade, header = the colour)."""
    base = base.lstrip("#").upper()
    return make_palette(_mix(base, "000000", 0.38), base)


CLASSIC = {"classic": True, "title_bg": "BFBFBF", "title_fg": "000000", "head_bg": None, "head_fg": "000000",
           "band": None, "total_bg": None, "total_fg": "000000", "border": "000000", "outline": "000000",
           "scale_lo": "F2F2F2", "scale_hi": "A6A6A6"}

PALETTES = {
    "Green Delta": make_palette("0A5A2F", "0B7D40", accent="FFF1B8"),
    "Executive navy": make_palette("1F3864", "2F5597"),
    "Slate & teal": make_palette("263238", "00796B"),
    "Ocean blue": make_palette("0B3C5D", "1D6A96"),
    "Burgundy": make_palette("5B1A2B", "8E2C48"),
    "Charcoal & gold": make_palette("2B2B2B", "4A4A4A", accent="F3E3A6"),
    "Royal purple": make_palette("3B2A6B", "5B4B9A"),
    "Classic grey (like the demo)": CLASSIC,
}
CUSTOM = "Custom colour"


def classic_style():
    return {"palette": CLASSIC, "banding": False, "gridlines": True, "colour_scale": False}


# ------------------------------------------------------------------ preview image
@st.cache_data(show_spinner=False)
def preview_png(palette):
    """A small picture of how a table in this palette will look (title, header, two rows, total)."""
    w, h, rows = 440, 176, 4
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=13)
    bold = ImageFont.load_default(size=14)
    colx = [8, 140, 235, 330, w - 8]
    top, th, rh = 8, 34, 28
    outline = "#" + palette["outline"]
    border = "#" + palette["border"]

    def fill(box, colour):
        if colour:
            d.rectangle(box, fill="#" + colour)

    fill((colx[0], top, colx[-1], top + th), palette["title_bg"])
    d.text((w / 2, top + th / 2), "Report title", fill="#" + palette["title_fg"], font=bold, anchor="mm")
    y = top + th
    labels = [["Class Code", "2025", "2026", "Grand Total"],
              ["GHI", "8,860,514", "86,065", "8,946,579"],
              ["MAR", "4,120,300", "512,880", "4,633,180"],
              ["Grand Total", "12,980,814", "598,945", "13,579,759"]]
    for i in range(rows):
        if i == 0:
            fill((colx[0], y, colx[-1], y + rh), palette["head_bg"])
        elif i == rows - 1:
            fill((colx[0], y, colx[-1], y + rh), palette["total_bg"])
        elif i % 2 == 0 and palette.get("band") and not palette.get("classic"):
            fill((colx[0], y, colx[-1], y + rh), palette["band"])
        for j in range(4):
            text = labels[i][j]
            head = i == 0
            total = i == rows - 1 or j == 3
            colour = "#" + (palette["head_fg"] if head else palette["total_fg"] if total else TEXT)
            if j == 0:
                d.text((colx[0] + 8, y + rh / 2), text, fill=colour, font=bold if (head or total) else font, anchor="lm")
            else:
                d.text((colx[j + 1] - 8, y + rh / 2), text, fill=colour, font=bold if (head or total) else font, anchor="rm")
        y += rh
    for i in range(rows + 1):                                   # thin grid, then the medium outline
        yy = top + th + i * rh
        d.line((colx[0], yy, colx[-1], yy), fill=border, width=1)
    for x in colx[:-1] + [colx[-1]]:
        d.line((x, top + th, x, y), fill=border, width=1)
    d.rectangle((colx[0], top, colx[-1], y), outline=outline, width=3)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
