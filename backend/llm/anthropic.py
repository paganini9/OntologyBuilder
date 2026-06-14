"""Anthropic Claude backend. Reads ANTHROPIC_API_KEY from the environment.

`available()` is False when the key or SDK is missing -> MOCK fallback.
Model id is read from ANTHROPIC_MODEL (default: current Claude family). When
wiring real usage, confirm the latest model id / params via the claude-api skill.
"""
from __future__ import annotations

import os
from typing import Optional

_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))


class AnthropicBackend:
    name = "anthropic"

    def __init__(self) -> None:
        self._key = os.getenv("ANTHROPIC_API_KEY") or ""
        self._client = None

    def available(self) -> bool:
        if not self._key:
            return False
        try:
            import anthropic  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._key)
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> str:
        client = self._ensure()
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=temperature,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        return "".join(parts)
