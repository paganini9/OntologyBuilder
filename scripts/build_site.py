"""Build the KO and EN static sites from a single source.

Reads registry/methods.json + each method's docs/samples, and the _src template +
locales, then writes self-contained site/ko/ and site/en/. Run after any method
is added or changed:  python scripts/build_site.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[1]
SRC = IMPL_ROOT / "site" / "_src"
REG = IMPL_ROOT / "registry" / "methods.json"
LANGS = ["ko", "en"]


def method_summary(m: dict) -> dict:
    return {
        "id": m["id"], "name": m["name"], "status": m.get("status"),
        "difficulty": m.get("difficulty"), "llm_dependency": m.get("llm_dependency"),
        "paper": m.get("paper"), "inputs_needed": m.get("inputs_needed", []),
        "produces": m.get("produces", []),
    }


def method_detail(m: dict) -> dict:
    d = IMPL_ROOT / m["paths"]["dir"]
    read = lambda n: (d / n).read_text(encoding="utf-8") if (d / n).exists() else None
    inputs = m.get("inputs_needed", [])
    sample = read(f"samples/{inputs[0]}") if inputs else None
    return {
        **method_summary(m),
        "docs": {"ko": read("method.ko.md"), "en": read("method.en.md")},
        "sample_input": sample,
        "implemented": (d / "pipeline.py").exists(),
    }


def render(tmpl: str, mapping: dict) -> str:
    for k, v in mapping.items():
        tmpl = tmpl.replace("{{" + k + "}}", v)
    return tmpl


def overview_for(lang: str, methods: list[dict], comp: dict) -> dict:
    """Join registry rows with comparison.json into a per-language table.

    Every published/implemented method appears automatically; qualitative
    columns come from comparison.json when present (else blank), so newly added
    methods show up in the table even before their comparison row is filled in.
    """
    cols = comp.get("columns", {}).get(lang, {})
    rows = comp.get("rows", {})
    table = []
    for m in methods:
        c = rows.get(m["id"], {})
        cell = lambda k: (c.get(k, {}) or {}).get(lang, "")
        table.append({
            "id": m["id"], "name": m["name"],
            "status": m.get("status"),
            "difficulty": m.get("difficulty", {}).get("score"),
            "llm": m.get("llm_dependency"),
            "input": cell("input"), "mechanism": cell("mechanism"),
            "output_unit": cell("output_unit"), "paradigm": cell("paradigm"),
            "distinct": cell("distinct"),
        })
    return {"columns": cols, "rows": table}


def build():
    reg = json.loads(REG.read_text(encoding="utf-8"))
    methods = reg.get("methods", [])
    summaries = [method_summary(m) for m in methods]
    comp_path = SRC / "comparison.json"
    comp = json.loads(comp_path.read_text(encoding="utf-8")) if comp_path.exists() else {}
    tmpl = (SRC / "index.html.tmpl").read_text(encoding="utf-8")

    for lang in LANGS:
        strings = json.loads((SRC / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        out = IMPL_ROOT / "site" / lang
        # clean only generated content, keep folder
        for sub in ("assets", "data"):
            if (out / sub).exists():
                shutil.rmtree(out / sub)
        (out / "data").mkdir(parents=True, exist_ok=True)
        shutil.copytree(SRC / "assets", out / "assets")

        site_json = {"lang": lang, "strings": strings, "methods": summaries}
        other = "en" if lang == "ko" else "ko"
        html = render(tmpl, {
            "LANG": lang,
            "TITLE": strings["title"],
            "SUBTITLE": strings["subtitle"],
            "OTHER_HREF": f"../{other}/",
            "LANG_SWITCH": strings["langSwitch"],
            "METHODS_HEADER": strings["methods"],
            "SELECT_HINT": strings["selectMethod"],
            "SITE_JSON": json.dumps(site_json, ensure_ascii=False),
        })
        (out / "index.html").write_text(html, encoding="utf-8")
        (out / "data" / "methods.json").write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "data" / "overview.json").write_text(
            json.dumps(overview_for(lang, methods, comp), ensure_ascii=False, indent=2),
            encoding="utf-8")
        for m in methods:
            (out / "data" / f"method-{m['id']}.json").write_text(
                json.dumps(method_detail(m), ensure_ascii=False, indent=2),
                encoding="utf-8")
        print(f"built site/{lang} ({len(methods)} methods)")


if __name__ == "__main__":
    build()
