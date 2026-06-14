"""Google Gemini backend. Reads GEMINI_API_KEY from the environment.

`available()` is False when the key or the SDK is missing, so get_backend()
falls back to MOCK and the loop never stalls. Keys are never written to disk.
"""
from __future__ import annotations

import os
from typing import Optional

_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


class GeminiBackend:
    name = "gemini"

    def __init__(self) -> None:
        self._key = os.getenv("GEMINI_API_KEY") or ""
        self._client = None

    def available(self) -> bool:
        if not self._key:
            return False
        try:
            import google.generativeai  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self):
        if self._client is None:
            import google.generativeai as genai

            genai.configure(api_key=self._key)
            self._client = genai.GenerativeModel(_MODEL)
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> str:
        model = self._ensure()
        full = (system + "\n\n" + prompt) if system else prompt
        cfg = {"temperature": temperature}
        if json_schema is not None:
            cfg["response_mime_type"] = "application/json"
        resp = model.generate_content(full, generation_config=cfg)
        return resp.text or ""
