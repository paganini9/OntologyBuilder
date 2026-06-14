"""Deterministic MOCK backend.

Two response strategies, in priority order:
1. `responder`  - a callable(prompt) -> str supplied by a method. This lets a
   method ship a deterministic, method-specific stand-in for the LLM (e.g. a
   rule-based CQ -> ontology-terms extractor). Real backends ignore it.
2. `responses`  - a dict of {hash(system+prompt): canned_string}. Useful when a
   method records exact prompt/response pairs in mock_responses.json.
3. generic fallback - extracts Capitalized noun-ish tokens as candidate classes
   and returns a minimal JSON object, so even unseen prompts yield ontology-ish
   output rather than crashing.

Determinism is the whole point: identical inputs -> identical outputs, so tests
can assert against committed golden files.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable, Optional


def _key(system: str, prompt: str) -> str:
    return hashlib.sha256((system + "\n###\n" + prompt).encode("utf-8")).hexdigest()


_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This",
}


def _generic_fallback(prompt: str, json_schema: Optional[dict]) -> str:
    # Candidate classes = capitalized words not in the stoplist; deterministic order.
    tokens = re.findall(r"\b[A-Z][a-zA-Z]+\b", prompt)
    seen: list[str] = []
    for t in tokens:
        if t not in _STOP and t not in seen:
            seen.append(t)
    classes = seen[:8]
    return json.dumps(
        {"classes": classes, "object_properties": [], "data_properties": [],
         "restrictions": []},
        ensure_ascii=False,
    )


class MockBackend:
    name = "mock"

    def __init__(
        self,
        responder: Optional[Callable[[str], str]] = None,
        responses: Optional[dict] = None,
    ) -> None:
        self._responder = responder
        self._responses = responses or {}

    def available(self) -> bool:
        return True

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> str:
        if self._responder is not None:
            return self._responder(prompt)
        k = _key(system, prompt)
        if k in self._responses:
            return self._responses[k]
        return _generic_fallback(prompt, json_schema)
