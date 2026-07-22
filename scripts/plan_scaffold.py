#!/usr/bin/env python3
"""Deterministic planning scaffold for the GHB PPT pipeline.

Given a confirmed ``confirmation.json`` and a normalized ``sources/source.md``,
generate *draft* ``content_model.json``, ``layout_plan.json``,
``art_direction.json`` and ``visual_profile.json``. Drafts are marked with
``needs_review``/``draft``/``origin: scaffold`` so a release build blocks until an
author refines and removes the markers. This never calls a model; it only turns
already-confirmed decisions into a fillable starting point.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Density presets per confirmed presentation mode. Deliberately non-neutral so
# the scaffold is a real starting point rather than the init defaults.
_MODE_DENSITY = {
    "briefing": "dense",
    "instructional": "balanced",
    "narrative": "breathing",
}
_RHYTHM_TO_DENSITY = {"anchor": "balanced", "dense": "dense", "breathing": "breathing"}
_RHYTHM_TO_ROLE = {"anchor": "anchor", "dense": "continuity", "breathing": "transition"}


class ScaffoldError(RuntimeError):
    """Raised when required inputs are missing or invalid."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaffoldError(f"cannot read valid JSON from {path}: {exc}") from exc


def _slug(text: str, index: int) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", text).strip("-").lower()
    cleaned = cleaned[:24] or "slide"
    return f"s{index:02d}-{cleaned}"


def extract_claims(source_text: str, limit: int = 24) -> list[dict[str, Any]]:
    """Extract candidate claims from a Markdown source.

    Headings and bullet points become candidate claim statements. Every claim
    carries ``draft: true`` so it must be reviewed before build.
    """
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        bullet = re.match(r"^[-*+]\s+(.*)$", line)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        statement = None
        for candidate in (heading, bullet, numbered):
            if candidate:
                statement = candidate.group(1).strip()
                break
        if not statement:
            continue
        statement = statement[:120]
        key = statement.lower()
        if key in seen:
            continue
        seen.add(key)
        anchor = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", statement)[:24] or "source"
        claims.append(
            {
                "id": f"claim-{len(claims) + 1:02d}",
                "statement": statement,
                "must_include": False,
                "source_reference": f"sources/source.md#{anchor}",
                "draft": True,
            }
        )
        if len(claims) >= limit:
            break
    if not claims:
        claims.append(
            {
                "id": "claim-01",
                "statement": "TODO: 补充核心论点",
                "must_include": False,
                "source_reference": "sources/source.md",
                "draft": True,
            }
        )
    return claims


def build_content_model(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "ghb.content-model.v1",
        "origin": "scaffold",
        "needs_review": True,
        "claims": claims,
    }


def build_layout_plan(
    outline: list[dict[str, Any]],
    *,
    audience: str,
    mode: str,
    claim_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    default_density = _MODE_DENSITY.get(mode, "balanced")
    for index, item in enumerate(outline, start=1):
        title = str(item.get("title", "")).strip() or f"页面 {index}"
        rhythm = item.get("rhythm") if item.get("rhythm") in _RHYTHM_TO_ROLE else "anchor"
        density = _RHYTHM_TO_DENSITY.get(rhythm, default_density)
        slide_id = _slug(title, index)
        # Round-robin a single claim per page as a safe starting mapping.
        mapped = [claim_ids[(index - 1) % len(claim_ids)]] if claim_ids else []
        rows.append(
            {
                "slide_id": slide_id,
                "purpose": "summary",
                "key_message": title,
                "audience": audience,
                "content_density": density,
                "rhythm": rhythm,
                "layout_type": "editorial",
                "visual_encoding": "TODO: 声明版式的可视化编码",
                "editable_elements": ["title", "body"],
                "image_requirement": "none",
                "source_reference": "sources/source.md",
                "speaker_note": "",
                "items": [],
                "reason": "scaffold draft: refine layout choice from content semantics",
                "alternatives": [],
                "claim_ids": mapped,
                "needs_review": True,
                "page_schema": {
                    "schema": "ghb.page-schema.v1",
                    "slide_id": slide_id,
                    "page_purpose": "summary",
                    "density": density,
                    "rhythm_role": _RHYTHM_TO_ROLE.get(rhythm, "continuity"),
                    "emphasis": "distributed",
                    "focal_target": None,
                    "layout_variant": "editorial/default",
                    "budgets": {"max_text_chars": 240, "max_nodes": 8},
                },
            }
        )
    return rows


def build_art_direction(mode: str, outline: list[dict[str, Any]]) -> dict[str, Any]:
    anchor_ids = [
        _slug(str(item.get("title", "")).strip() or f"页面 {index}", index)
        for index, item in enumerate(outline, start=1)
        if item.get("rhythm") == "anchor"
    ]
    if not anchor_ids and outline:
        anchor_ids = [_slug(str(outline[0].get("title", "") or "页面 1"), 1)]
    breathing_variants = ["light", "contrast", "evidence"]
    return {
        "schema": "ghb.art-direction.v1",
        "origin": "scaffold",
        "needs_review": True,
        "design_mode": mode if mode in _MODE_DENSITY else "instructional",
        "visual_thesis": "TODO: 用一句话锁定整套演示的视觉命题",
        "narrative_arc": ["orient", "explain", "prove", "decide"],
        "page_families": ["editorial", "evidence", "comparison", "process", "decision"],
        "surface_strategy": {
            "variants": breathing_variants,
            "max_same_variant_streak": 2,
        },
        "focal_strategy": {"max_distributed_streak": 4},
        "anchor_slide_ids": anchor_ids,
        "imagery": {"strategy": "evidence-first", "max_images_per_page": 2},
    }


def build_visual_profile(mode: str) -> dict[str, Any]:
    density = _MODE_DENSITY.get(mode, "balanced")
    occupancy = {
        "dense": {"min": 0.5, "max": 0.82},
        "balanced": {"min": 0.42, "max": 0.78},
        "breathing": {"min": 0.32, "max": 0.68},
    }[density]
    return {
        "schema": "ghb.visual-profile.v1",
        "origin": "scaffold",
        "needs_review": True,
        "brand": {"primary": "#AB1F29", "text": "#2B2B2B", "surface": "#FFFFFF"},
        "typography": {
            "enforcement": "strict",
            "min_title_pt": 28,
            "min_body_pt": 18,
            "min_caption_pt": 12,
            "min_source_pt": 10,
            "min_footer_pt": 9,
            "min_title_body_ratio": 1.5,
        },
        "spacing": {"base_unit": 8, "min_component_gap": 16},
        "occupancy": {"body": occupancy},
        "composition": {"default_density": density, "default_emphasis": "ranked"},
        "focal": {"allowed_zones": ["left", "center", "right", "full"]},
        "deck_rhythm": {"default_role": "continuity", "max_same_role_streak": 3},
        "budgets": {"max_text_chars": 240, "max_nodes": 8},
    }


def _has_scaffold_marker(payload: Any) -> bool:
    if isinstance(payload, dict):
        if payload.get("needs_review") is True or payload.get("draft") is True:
            return True
        if payload.get("origin") == "scaffold":
            return True
        return any(_has_scaffold_marker(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_scaffold_marker(value) for value in payload)
    return False


def _is_protected(path: Path) -> bool:
    """Return True when an existing file holds real author work worth protecting.

    Init writes default ``art_direction.json``/``visual_profile.json`` and a prior
    ``plan`` writes scaffold drafts; both are safe to regenerate. Only a refined,
    non-scaffold artifact requires an explicit ``--force``.
    """
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if _has_scaffold_marker(payload):
        return False
    try:
        from scripts.validate_project_contract import (
            default_art_direction,
            default_visual_profile,
        )
    except Exception:
        return True
    if path.name == "art_direction.json" and payload == default_art_direction():
        return False
    if path.name == "visual_profile.json" and payload == default_visual_profile():
        return False
    return True


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def scaffold_project(
    project: Path,
    *,
    source: Path | None = None,
    confirmation: Path | None = None,
    force: bool = False,
) -> list[Path]:
    """Generate the four planning drafts. Returns the written paths."""
    project = project.resolve()
    if not project.is_dir():
        raise ScaffoldError(f"project directory not found: {project}")
    confirmation_path = confirmation or (project / "confirmation.json")
    if not confirmation_path.is_file():
        raise ScaffoldError(
            "confirmation.json is required before scaffolding; confirm the six decisions first"
        )
    confirmation_payload = _read_json(confirmation_path)
    decisions = (
        confirmation_payload.get("decisions")
        if isinstance(confirmation_payload, dict)
        else None
    )
    if not isinstance(decisions, dict):
        raise ScaffoldError("confirmation.json has no decisions object")
    outline = decisions.get("outline")
    if not isinstance(outline, list) or not outline:
        raise ScaffoldError("confirmation.json decisions.outline must be a non-empty list")
    mode = str(decisions.get("mode") or "instructional")
    audience = str(decisions.get("audience") or "")

    source_path = source or (project / "sources" / "source.md")
    source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    claims = extract_claims(source_text)
    claim_ids = [claim["id"] for claim in claims]

    targets = {
        project / "content_model.json": build_content_model(claims),
        project / "layout_plan.json": build_layout_plan(
            outline, audience=audience, mode=mode, claim_ids=claim_ids
        ),
        project / "art_direction.json": build_art_direction(mode, outline),
        project / "visual_profile.json": build_visual_profile(mode),
    }
    written: list[Path] = []
    for path, payload in targets.items():
        if not force and _is_protected(path):
            raise ScaffoldError(
                f"{path.name} already holds refined content; pass --force to overwrite with a fresh scaffold"
            )
        _write_json(path, payload)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--from-source", type=Path)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            print(f"[DRY-RUN] scaffold planning drafts under {args.project.resolve()}")
            return 0
        written = scaffold_project(
            args.project,
            source=args.from_source,
            confirmation=args.confirmation,
            force=args.force,
        )
    except ScaffoldError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"[OK] scaffolded {path}")
    print("[NOTE] drafts carry needs_review/draft/origin markers; refine and clear them before build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
