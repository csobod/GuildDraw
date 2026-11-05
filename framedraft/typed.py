"""How the canvas tools read a number the maker types.

A comma is taken as the decimal point, as a European keyboard writes one:
"12,5" was read as 125 mm by the type-to-lock buffers, which dropped the
comma, and refused outright by the HUD fields.
"""
import math

# A typed length past ten meters is no drawing's: a move of 1e300 was taken,
# the geometry left the canvas, and Fit silently did nothing (2.0.1).
_MAX_TYPED_MM = 10_000.0


def typed_char(text: str) -> str:
    """One typed character as a number buffer takes it (',' becomes '.')."""
    return "." if text == "," else text


def parse_typed(text: str) -> float | None:
    """The length in *text*, a comma taken as the decimal point; None when it
    is not a finite number or lies past ten meters either way."""
    try:
        v = float(text.strip().replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        return None
    return v if math.isfinite(v) and abs(v) <= _MAX_TYPED_MM else None
