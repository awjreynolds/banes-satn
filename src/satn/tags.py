"""Canonical decoding for scalar and collection-valued source tags."""

from __future__ import annotations

import ast
from collections.abc import Iterable


def tag_values(value: object) -> list[str]:
    """Return deterministic text values after GeoJSON and OSM round-trips."""
    if value is None:
        return []
    if isinstance(value, str) and value.startswith(("[", "(", "{")):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, (list, tuple, set)):
                value = parsed
        except (SyntaxError, ValueError):
            pass
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return [str(item) for item in value]
    text = str(value).strip()
    return [] if text.lower() in {"", "nan", "none", "<na>"} else [text]
