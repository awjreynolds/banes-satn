"""Shared deterministic identifiers and topology coordinate keys."""

from __future__ import annotations

import hashlib


def stable_id(prefix: str, *parts: object) -> str:
    value = "::".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def coordinate_key(value: tuple[float, ...]) -> str:
    return f"{value[0]:.3f}:{value[1]:.3f}"
