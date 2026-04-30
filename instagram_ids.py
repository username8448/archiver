"""Validation helpers for Instagram public identifiers."""

from __future__ import annotations

import re

INSTAGRAM_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def normalize_instagram_shortcode(value: object) -> str:
    """Returns a safe Instagram shortcode path segment or raises ValueError."""
    shortcode = str(value or "").strip()
    if not INSTAGRAM_SHORTCODE_RE.fullmatch(shortcode):
        raise ValueError("Invalid Instagram shortcode")
    return shortcode
