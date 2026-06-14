"""Shared access to the method registry (registry/methods.json).

The registry is the single source of truth for loop control state. The runner
uses it as an allowlist (never run an arbitrary path); the FastAPI app and
build_site.py use it to list methods; the slash commands read/update it.
"""
from __future__ import annotations

import json
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = IMPL_ROOT / "registry" / "methods.json"

_ACTIVE = {"discovered", "analyzed", "queued"}


def load() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def methods() -> list[dict]:
    return load().get("methods", [])


def method_ids() -> set[str]:
    return {m["id"] for m in methods()}


def get(method_id: str) -> dict | None:
    return next((m for m in methods() if m["id"] == method_id), None)


def is_allowed(method_id: str) -> bool:
    """Allowlist check: id exists in the registry and its dir is present."""
    m = get(method_id)
    if not m:
        return False
    return (IMPL_ROOT / m["paths"]["dir"]).is_dir()


def next_easiest() -> dict | None:
    """Return the next method to implement, per the selection rule, or None."""
    cands = [
        m for m in methods()
        if m.get("status") in _ACTIVE
        and m.get("approved_by_user")
        and not m.get("blockers")
    ]
    if not cands:
        return None
    cands.sort(key=lambda m: (
        m["difficulty"]["score"],
        0 if m.get("llm_dependency") == "mock" else 1,
        len(m.get("inputs_needed", [])),
        m["difficulty"].get("rank", 999),
    ))
    return cands[0]
