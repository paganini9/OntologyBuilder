"""Shared real-LLM extraction helpers.

Methods are written so the MOCK backend is deterministic (golden-tested). When a
REAL backend (hf_local / gemini / anthropic) is selected, the brittle per-method
mock parsing is bypassed in favour of these robust helpers: a well-specified
prompt + tolerant JSON extraction + URI-safe name sanitisation. This is the same
recipe proven in methods/hf-local-demo.

Usage in a pipeline (keeps mock path untouched):

    from backend.llm import get_backend
    from backend.llm.extract import is_mock, extract_triples

    llm = get_backend(backend, mock_responder=mock_responder)
    if is_mock(llm):
        ... existing deterministic per-step logic ...
    else:
        triples = extract_triples(llm, text)   # [{"subject","relation","object"}]
        ... build the same graph structure from triples ...
"""
from __future__ import annotations

import json
import re
from typing import Optional

_ARTICLES = {"the", "a", "an", "this", "that", "these", "those", "some", "any"}

_SYSTEM = (
    "You are an information-extraction system for building an ontology / knowledge "
    "graph. From the input, extract (subject, relation, object) triples. "
    'Return ONLY JSON of the form {"triples":[{"subject":"...","relation":"...",'
    '"object":"..."}]}. Use a short PascalCase noun for subject and object and a '
    "camelCase verb phrase for relation. No prose, no markdown fences."
)


def is_mock(llm) -> bool:
    return getattr(llm, "name", "") == "mock"


def san_entity(s: str) -> str:
    """URI-safe PascalCase class name (drop articles/punctuation/spaces)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(s)) if w]
    words = [w for w in words if w.lower() not in _ARTICLES] or words
    return "".join(w[:1].upper() + w[1:] for w in words)


def san_relation(r: str) -> str:
    """URI-safe camelCase relation name."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(r)) if w]
    if not words:
        return ""
    return words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])


def _emit(items) -> list[dict]:
    out = []
    for t in items:
        if not isinstance(t, dict):
            continue
        s = san_entity(t.get("subject", ""))
        r = san_relation(t.get("relation", ""))
        o = san_entity(t.get("object", ""))
        if s and r and o and s != o:
            out.append({"subject": s, "relation": r, "object": o})
    return out


def parse_triples(raw: str) -> list[dict]:
    """Tolerantly pull sanitised triples out of an LLM response.

    Tries a whole {"triples":[...]} parse first; if that fails (e.g. the response
    was truncated mid-JSON at the token cap), salvages every COMPLETE {...} object
    individually so partial output still yields usable triples.
    """
    if not raw:
        return []
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and obj.get("triples"):
                return _emit(obj["triples"])
        except json.JSONDecodeError:
            pass
    # salvage: every self-contained {...} (handles truncation / prose / fences)
    objs = []
    for chunk in re.findall(r"\{[^{}]*\}", raw):
        try:
            objs.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return _emit(objs)


def extract_triples(llm, text: str, *, system: Optional[str] = None) -> list[dict]:
    """Run the real LLM on `text` and return sanitised triples (possibly empty)."""
    raw = llm.complete(f"Input:\n{text}", system=system or _SYSTEM,
                       json_schema={"type": "object"}, temperature=0.0)
    return parse_triples(raw)
