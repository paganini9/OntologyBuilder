"""Probe: run every registered method's pipeline with the REAL hf_local backend
on its committed sample, in ONE process (model loads once), and report whether a
non-empty, valid graph comes out. Helps decide which methods already work on the
local model vs need prompt/parse fixes. Not a test (real output is non-deterministic).
"""
import importlib.util
import json
import sys
import traceback
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPL))
from backend import registry  # noqa: E402

OUT = IMPL / "runs" / "probe_hf"
OUT.mkdir(parents=True, exist_ok=True)


def load_pipeline(mid, d):
    spec = importlib.util.spec_from_file_location(
        "probe_" + mid.replace("-", "_"), IMPL / d / "pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    only = sys.argv[1:] or None
    for m in registry.methods():
        mid = m["id"]
        if only and mid not in only:
            continue
        d = m["paths"]["dir"]
        sample = IMPL / d / "samples"
        try:
            mod = load_pipeline(mid, d)
            res = mod.run(sample, OUT / mid, backend="hf_local")
            g = json.loads((OUT / mid / "ontology.json").read_text(encoding="utf-8"))
            n, e = len(g["nodes"]), len(g["edges"])
            status = "OK" if (n >= 1 and e >= 1) else "EMPTY"
            print(f"[{status:5}] {mid:26} backend={res.get('backend'):8} nodes={n} edges={e}")
        except Exception as exc:
            print(f"[ERROR] {mid:26} {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=1)


if __name__ == "__main__":
    main()
