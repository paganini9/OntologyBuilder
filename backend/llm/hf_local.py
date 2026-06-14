"""Local HuggingFace backend for methods that can run an open model offline.

`available()` is False when transformers/torch are not installed -> MOCK
fallback. The first real run downloads the model into HF_HOME (gitignored).
Model id from HF_MODEL (default: a small instruct model). Heavy: only used by
methods explicitly marked llm_dependency = "hf-local".
"""
from __future__ import annotations

import os
from typing import Optional

_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")


class HFLocalBackend:
    name = "hf_local"

    def __init__(self) -> None:
        self._pipe = None

    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self):
        if self._pipe is None:
            from transformers import pipeline

            self._pipe = pipeline("text-generation", model=_MODEL)
        return self._pipe

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        json_schema: Optional[dict] = None,
        temperature: float = 0.0,
    ) -> str:
        pipe = self._ensure()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        out = pipe(messages, max_new_tokens=1024, do_sample=temperature > 0)
        gen = out[0]["generated_text"]
        if isinstance(gen, list):  # chat format -> last assistant turn
            return gen[-1].get("content", "")
        return str(gen)
