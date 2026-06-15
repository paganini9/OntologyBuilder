"""Local HuggingFace backend — real on-device inference (GPU if available).

`available()` is False when transformers/torch are missing -> MOCK fallback.
The first real run downloads the model into HF_HOME (gitignored). Uses the GPU
(device_map="auto") when CUDA is present, else CPU. Model id from HF_MODEL.
Used by methods marked llm_dependency = "hf-local" (e.g. hf-local-demo).
"""
from __future__ import annotations

import os
from typing import Optional

_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")


class HFLocalBackend:
    name = "hf_local"

    def __init__(self) -> None:
        self._pipe = None
        self._model_id = _MODEL

    def available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self):
        if self._pipe is None:
            import torch
            from transformers import pipeline

            use_cuda = torch.cuda.is_available()
            self._pipe = pipeline(
                "text-generation",
                model=self._model_id,
                device_map="auto" if use_cuda else None,
                torch_dtype="auto",
            )
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
        out = pipe(
            messages,
            max_new_tokens=512,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
            return_full_text=False,
        )
        gen = out[0]["generated_text"]
        if isinstance(gen, list):  # some versions return the chat turns
            return gen[-1].get("content", "")
        return str(gen)
