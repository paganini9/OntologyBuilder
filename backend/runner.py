"""Sandboxed pipeline runner.

Each method's pipeline runs in a SUBPROCESS (not in-process) so a buggy or
slow pipeline cannot take down the API. Safeguards:
  - allowlist: method_id must exist in the registry (never run an arbitrary path)
  - timeout: hard wall-clock limit, process killed on overrun
  - jail: cwd is the impl root; outputs go under runs/<id>/<ts>/ only
  - no shell: args passed as a list, shell=False
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import registry

IMPL_ROOT = registry.IMPL_ROOT
RUNS_DIR = IMPL_ROOT / "runs"
DEFAULT_TIMEOUT = 120  # seconds


class RunnerError(RuntimeError):
    pass


def new_run_dir(method_id: str) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    d = RUNS_DIR / method_id / ts
    (d / "input").mkdir(parents=True, exist_ok=True)
    return d


def run_method(
    method_id: str,
    input_dir: Path,
    out_dir: Path,
    backend: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    if not registry.is_allowed(method_id):
        raise RunnerError(f"method not allowed: {method_id!r}")

    meta = registry.get(method_id)
    pipeline = IMPL_ROOT / meta["paths"]["dir"] / "pipeline.py"
    if not pipeline.exists():
        raise RunnerError(f"pipeline missing: {pipeline}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "log.txt"

    cmd = [sys.executable, str(pipeline), str(input_dir), str(out_dir)]
    if backend:
        cmd += ["--backend", backend]

    try:
        proc = subprocess.run(
            cmd, cwd=str(IMPL_ROOT), capture_output=True, text=True,
            timeout=timeout, shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(f"TIMEOUT after {timeout}s\n{exc}", encoding="utf-8")
        raise RunnerError(f"pipeline timed out after {timeout}s") from exc

    log_path.write_text(
        f"$ {' '.join(cmd)}\n\n[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr}",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RunnerError(f"pipeline exit {proc.returncode}: {proc.stderr[-2000:]}")

    manifest_file = out_dir / "manifest.json"
    if not manifest_file.exists():
        raise RunnerError("pipeline produced no manifest.json")
    return json.loads(manifest_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Run a registered method pipeline")
    ap.add_argument("method_id")
    ap.add_argument("input_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    a = ap.parse_args()
    out = Path(a.out) if a.out else new_run_dir(a.method_id)
    print(json.dumps(run_method(a.method_id, Path(a.input_dir), out,
                                a.backend, a.timeout), ensure_ascii=False))
