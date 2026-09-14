"""Unified visual palette for NotebookLM-style presentations.

Single source of truth for colors, typography and layout constants used
by the PPTX renderer and the HTML preview. The palette follows the dark
AI EDU theme already used across the app.
"""

from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


def _rgb(hex_value: str) -> RGBColor:
    """Convert a '#RRGGBB' string to a python-pptx RGBColor."""
    value = hex_value.lstrip("#")
    return RGBColor(
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


# --- Backgrounds -------------------------------------------------------------

BACKGROUND_HEX = "#0B0C0F"         # deck background
SURFACE_HEX = "#111318"           # elevated panels / side rails
SURFACE_ELEVATED_HEX = "#171A20"  # hovered or active panels
CARD_HEX = "#1B1E24"              # cards, tiles, code blocks

# --- Text --------------------------------------------------------------------

TEXT_PRIMARY_HEX = "#FFFFFF"
TEXT_SECONDARY_HEX = "#B7BAC3"
TEXT_MUTED_HEX = "#7F838E"

# --- Accents -----------------------------------------------------------------

ACCENT_HEX = "#4F7CFF"            # primary interactive accent
ACCENT_HOVER_HEX = "#6D93FF"      # lighter accent for emphasis
ACCENT_SOFT_HEX = "#1B2A4A"       # soft accent fill for chips

# College brand accents.
ETEC_HEX = "#C8424A"
META_HEX = "#E78638"

# --- Borders / dividers ------------------------------------------------------

BORDER_HEX = "#2A2D35"
BORDER_HOVER_HEX = "#3A3E48"
DIVIDER_HEX = "#2E313A"

# --- Semantic status ---------------------------------------------------------

SUCCESS_HEX = "#48B883"
WARNING_HEX = "#E6A83C"
DANGER_HEX = "#D75A63"


# RGBColor constants for python-pptx.
BACKGROUND = _rgb(BACKGROUND_HEX)
SURFACE = _rgb(SURFACE_HEX)
SURFACE_ELEVATED = _rgb(SURFACE_ELEVATED_HEX)
CARD = _rgb(CARD_HEX)

TEXT_PRIMARY = _rgb(TEXT_PRIMARY_HEX)
TEXT_SECONDARY = _rgb(TEXT_SECONDARY_HEX)
TEXT_MUTED = _rgb(TEXT_MUTED_HEX)

ACCENT = _rgb(ACCENT_HEX)
ACCENT_HOVER = _rgb(ACCENT_HOVER_HEX)
ACCENT_SOFT = _rgb(ACCENT_SOFT_HEX)

ETEC = _rgb(ETEC_HEX)
META = _rgb(META_HEX)

BORDER = _rgb(BORDER_HEX)
BORDER_HOVER = _rgb(BORDER_HOVER_HEX)
DIVIDER = _rgb(DIVIDER_HEX)

SUCCESS = _rgb(SUCCESS_HEX)
WARNING = _rgb(WARNING_HEX)
DANGER = _rgb(DANGER_HEX)


# --- Typography --------------------------------------------------------------

FONT_FAMILY = "Inter"
FONT_FAMILY_FALLBACK = "Arial"
MONO_FONT = "Menlo"

TITLE_SIZE = Pt(40)
SUBTITLE_SIZE = Pt(20)
HEADING_SIZE = Pt(28)
BODY_SIZE = Pt(18)
SMALL_SIZE = Pt(14)
CODE_SIZE = Pt(16)


# --- Layout ------------------------------------------------------------------

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
MARGIN = Inches(0.5)
GUTTER = Inches(0.25)


# --- Helpers -----------------------------------------------------------------

ACCENTS = (ACCENT, ETEC, META, SUCCESS, WARNING)


def college_accent(college: str) -> RGBColor:
    """Return the brand accent color for a college."""
    return META if str(college or "").upper() == "META" else ETEC


def accent_for(index: int) -> RGBColor:
    """Return a rotating accent color for multi-item layouts."""
    return ACCENTS[index % len(ACCENTS)]


__all__ = [
    "BACKGROUND_HEX", "SURFACE_HEX", "SURFACE_ELEVATED_HEX", "CARD_HEX",
    "TEXT_PRIMARY_HEX", "TEXT_SECONDARY_HEX", "TEXT_MUTED_HEX",
    "ACCENT_HEX", "ACCENT_HOVER_HEX", "ACCENT_SOFT_HEX",
    "ETEC_HEX", "META_HEX",
    "BORDER_HEX", "BORDER_HOVER_HEX", "DIVIDER_HEX",
    "SUCCESS_HEX", "WARNING_HEX", "DANGER_HEX",
    "BACKGROUND", "SURFACE", "SURFACE_ELEVATED", "CARD",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
    "ACCENT", "ACCENT_HOVER", "ACCENT_SOFT",
    "ETEC", "META",
    "BORDER", "BORDER_HOVER", "DIVIDER",
    "SUCCESS", "WARNING", "DANGER",
    "FONT_FAMILY", "FONT_FAMILY_FALLBACK", "MONO_FONT",
    "TITLE_SIZE", "SUBTITLE_SIZE", "HEADING_SIZE",
    "BODY_SIZE", "SMALL_SIZE", "CODE_SIZE",
    "SLIDE_WIDTH", "SLIDE_HEIGHT", "MARGIN", "GUTTER",
    "ACCENTS", "college_accent", "accent_for",
]