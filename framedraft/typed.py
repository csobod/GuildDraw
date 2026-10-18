"""How the canvas tools read a number the maker types.

A comma is taken as the decimal point, as a European keyboard writes one:
"12,5" was read as 125 mm by the type-to-lock buffers, which dropped the
comma, and refused outright by the HUD fields.
"""
import math


def typed_char(text: str) -> str:
    """One typed character as a number buffer takes it (',' becomes '.')."""
    return "." if text == "," else text


def parse_typed(text: str) -> float | None:
    """The number in *text*, a comma taken as the decimal point; None when it
    is not a finite number."""
    try:
        v = float(text.strip().replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        return None
    return v if math.isfinite(v) else None
