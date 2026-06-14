"""FastAPI backend.

Serves the method registry, runs a method's pipeline on user input (sandboxed via
runner.py), and serves the built KO/EN static sites. Local research tool: bind to
127.0.0.1 only.

Run:  python -m backend.app           (or)  uvicorn backend.app:app --host 127.0.0.1
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import registry, runner

IMPL_ROOT = registry.IMPL_ROOT
SITE = IMPL_ROOT / "site"

app = FastAPI(title="Ontology Construction Methods", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class RunRequest(BaseModel):
    input_text: str | None = None
    backend: str | None = None


def _method_public(m: dict) -> dict:
    return {
        "id": m["id"], "name": m["name"], "status": m.get("status"),
        "difficulty": m.get("difficulty"), "llm_dependency": m.get("llm_dependency"),
        "paper": m.get("paper"), "inputs_needed": m.get("inputs_needed", []),
        "produces": m.get("produces", []),
    }


@app.get("/api/methods")
def list_methods():
    return {"methods": [_method_public(m) for m in registry.methods()]}


@app.get("/api/methods/{method_id}")
def method_detail(method_id: str):
    m = registry.get(method_id)
    if not m:
        raise HTTPException(404, f"unknown method: {method_id}")
    d = IMPL_ROOT / m["paths"]["dir"]

    def _read(name):
        f = d / name
        return f.read_text(encoding="utf-8") if f.exists() else None

    docs = {"ko": _read("method.ko.md"), "en": _read("method.en.md")}
    sample = None
    inputs = m.get("inputs_needed", [])
    if inputs:
        sample = _read(f"samples/{inputs[0]}")
    meta = None
    if (d / "meta.json").exists():
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    return {**_method_public(m), "docs": docs, "sample_input": sample,
            "meta": meta, "implemented": (d / "pipeline.py").exists()}


@app.post("/api/methods/{method_id}/run")
def run(method_id: str, req: RunRequest):
    m = registry.get(method_id)
    if not m:
        raise HTTPException(404, f"unknown method: {method_id}")
    if not (IMPL_ROOT / m["paths"]["dir"] / "pipeline.py").exists():
        raise HTTPException(409, f"method not implemented yet: {method_id}")

    run_dir = runner.new_run_dir(method_id)
    input_dir = run_dir / "input"
    inputs = m.get("inputs_needed", [])
    primary = inputs[0] if inputs else "input.txt"

    if req.input_text is not None:
        (input_dir / primary).write_text(req.input_text, encoding="utf-8")
    else:  # fall back to the committed sample
        src = IMPL_ROOT / m["paths"]["dir"] / "samples" / primary
        if src.exists():
            shutil.copy(src, input_dir / primary)
        else:
            raise HTTPException(400, "no input_text and no sample available")

    try:
        manifest = runner.run_method(method_id, input_dir, run_dir, req.backend)
    except runner.RunnerError as exc:
        raise HTTPException(500, str(exc))

    def _load(name):
        f = run_dir / name
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    return {
        "manifest": manifest,
        "ontology": _load("ontology.json"),
        "steps": _load("steps.json"),
        "ttl": (run_dir / "ontology.ttl").read_text(encoding="utf-8")
        if (run_dir / "ontology.ttl").exists() else None,
        "run_id": run_dir.name,
    }


@app.get("/")
def root():
    return RedirectResponse("/ko/")


# Serve built static sites if present (build_site.py generates them).
for lang in ("ko", "en"):
    d = SITE / lang
    if d.is_dir():
        app.mount(f"/{lang}", StaticFiles(directory=str(d), html=True), name=lang)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
