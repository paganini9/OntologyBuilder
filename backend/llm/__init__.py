"""LLM backend factory.

Resolution order for the backend name:
    explicit arg  ->  LLM_BACKEND env  ->  "mock"

Any non-mock backend whose `available()` is False (missing key / SDK / model)
silently falls back to MOCK, so the implementation loop never stalls on a
missing credential. `mock_responder` is forwarded to the MOCK backend whether it
was chosen explicitly or via fallback, letting a method inject a deterministic
stand-in for the LLM.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from .base import LLMBackend
from .mock import MockBackend

log = logging.getLogger("llm")

_REAL = {
    "gemini": ("gemini", "GeminiBackend"),
    "anthropic": ("anthropic", "AnthropicBackend"),
    "hf_local": ("hf_local", "HFLocalBackend"),
}


def get_backend(
    name: Optional[str] = None,
    *,
    mock_responder: Optional[Callable[[str], str]] = None,
    mock_responses: Optional[dict] = None,
) -> LLMBackend:
    name = (name or os.getenv("LLM_BACKEND", "mock")).strip().lower()

    if name == "mock":
        return MockBackend(responder=mock_responder, responses=mock_responses)

    if name not in _REAL:
        log.warning("unknown backend %r -> MOCK", name)
        return MockBackend(responder=mock_responder, responses=mock_responses)

    module_name, cls_name = _REAL[name]
    try:
        module = __import__(f"backend.llm.{module_name}", fromlist=[cls_name])
        backend = getattr(module, cls_name)()
    except Exception as exc:  # import or construction failure
        log.warning("backend %s init failed (%s) -> MOCK", name, exc)
        return MockBackend(responder=mock_responder, responses=mock_responses)

    if not backend.available():
        log.warning("backend %s unavailable (no key/model) -> MOCK", name)
        return MockBackend(responder=mock_responder, responses=mock_responses)

    return backend


__all__ = ["get_backend", "LLMBackend", "MockBackend"]
