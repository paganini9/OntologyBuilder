"""LLM backend protocol shared by all ontology-construction methods.

A backend is a thin text-completion interface. Methods describe their task in a
prompt and parse the returned string. The MOCK backend makes the whole system
runnable with no API key and fully deterministic (so tests have golden files).
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def available(self) -> bool:
        """True if this backend can actually run (key present / model cached)."""
        ...

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> str:
        """Return the model completion as a raw string."""
        ...
