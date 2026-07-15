#!/usr/bin/env python3
"""Freeze revision holdout SVGs with the exact pre-U11 renderer source."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = Path(__file__).with_name("visual_pilot_revision_cases.json")
EXPECTED_PURPOSES = {"comparison", "timeline", "metrics"}


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_prechange_renderer(corpus: dict[str, Any]):
    renderer = corpus["pre_change_renderer"]
    revision = renderer["commit"]
    source_path = renderer["path"]
    completed = subprocess.run(
        ["git", "show", f"{revision}:{source_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    module_name = "ghb_visual_pilot_prechange_renderer"
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    exec(compile(completed.stdout, f"{revision}:{source_path}", "exec"), module.__dict__)
    return module.LayoutSpec, module.render_layout, hashlib.sha256(completed.stdout.encode()).hexdigest()


def _validate(corpus: dict[str, Any], *, allow_missing_digests: bool = False) -> None:
    if corpus.get("schema") != "ghb.visual-pilot-revision-corpus.v1":
        raise ValueError("invalid-revision-corpus-schema")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != 3:
        raise ValueError("revision-corpus-requires-three-cases")
    ids = [case.get("case_id") for case in cases]
    if len(ids) != len(set(ids)) or not all(isinstance(case_id, str) and case_id for case_id in ids):
        raise ValueError("invalid-or-duplicate-revision-case-id")
    if {case.get("page_purpose") for case in cases} != EXPECTED_PURPOSES:
        raise ValueError("revision-corpus-purpose-coverage")
    for case in cases:
        slide = case.get("slide", {})
        if slide.get("layout_type") not in {"matrix", "timeline"}:
            raise ValueError(f"{case['case_id']}: revision family must be matrix or timeline")
        if not isinstance(slide.get("items"), list) or not 2 <= len(slide["items"]) <= 4:
            raise ValueError(f"{case['case_id']}: invalid revision items")
        digest = case.get("pre_change_evidence", {}).get("authored_svg_sha256")
        if not allow_missing_digests and (not isinstance(digest, str) or len(digest) != 64):
            raise ValueError(f"{case['case_id']}: frozen pre-change digest is required")


def _render_svg(case: dict[str, Any], index: int, layout_spec, render_layout) -> str:
    slide = case["slide"]
    title = _xml(slide["key_message"])
    fragment = render_layout(
        layout_spec(slide["layout_type"], slide["items"], x=100, y=240, width=1080, height=390)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <g id="bg"><rect width="1280" height="720" fill="#FFFFFF"/></g>
  <g id="bg-surface"><rect x="56" y="96" width="1168" height="608" rx="12" fill="#FFFFFF" fill-opacity="0.92" stroke="#E0E0E0"/></g>
  <g id="header"><rect x="88" y="132" width="6" height="40" fill="#AB1F29"/><text x="108" y="162" font-size="30" font-weight="bold" font-family="Arial Black, Microsoft YaHei, Arial, sans-serif" fill="#2B2B2B">{title}</text></g>
  {fragment}
  <g id="footer"><text x="1192" y="696" text-anchor="end" font-size="13" font-family="Microsoft YaHei, Arial, sans-serif" fill="#999999">R2-{index:02d}</text></g>
</svg>
'''


def build(output: Path, corpus: dict[str, Any], *, bootstrap: bool = False) -> dict[str, Any]:
    _validate(corpus, allow_missing_digests=bootstrap)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite revision holdout: {output}")
    layout_spec, render_layout, renderer_sha256 = _load_prechange_renderer(corpus)
    output.mkdir(parents=True)
    generated = []
    for index, case in enumerate(corpus["cases"], 1):
        encoded = _render_svg(case, index, layout_spec, render_layout).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        expected = case["pre_change_evidence"]["authored_svg_sha256"]
        if expected and digest != expected:
            raise ValueError(f"{case['case_id']}: pre-change SVG digest mismatch")
        path = output / f"{case['case_id']}.svg"
        path.write_bytes(encoded)
        generated.append({"case_id": case["case_id"], "authored_svg_sha256": digest})
    manifest = {
        "schema": "ghb.visual-pilot-revision-freeze.v1",
        "round_id": corpus["round_id"],
        "pre_change_renderer": corpus["pre_change_renderer"],
        "pre_change_renderer_sha256": renderer_sha256,
        "generated": generated,
        "network": "not-used",
        "model_adapter": "not-used",
    }
    (output / "freeze-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    result = build(args.output, corpus, bootstrap=args.bootstrap)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
