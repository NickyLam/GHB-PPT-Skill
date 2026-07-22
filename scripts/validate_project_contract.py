#!/usr/bin/env python3
"""Validate the human-confirmation and authoring contract before SVG build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIRMATION_FIELDS = (
    "audience",
    "page_range",
    "mode",
    "outline",
    "content_tradeoffs",
    "visual_assets",
)
MODES = {"instructional", "briefing", "narrative"}
SOURCES = {"user", "fixture"}
PAGE_PURPOSES = {
    "architecture",
    "process",
    "comparison",
    "timeline",
    "metrics",
    "summary",
    "hero",
    "section-anchor",
    "evidence",
    "case-study",
    "instruction",
    "decision",
    "risk",
    "screenshot",
    "data-story",
    "recommendation",
    "closing",
}
PAGE_DENSITIES = {"breathing", "balanced", "dense"}
RHYTHM_ROLES = {"anchor", "continuity", "transition"}
EMPHASIS_INTENTS = {"single-focal", "ranked", "distributed"}
ROOT = Path(__file__).resolve().parents[1]
LAYOUT_REQUIRED_FIELDS = (
    "slide_id",
    "purpose",
    "key_message",
    "audience",
    "content_density",
    "rhythm",
    "layout_type",
    "visual_encoding",
    "editable_elements",
    "image_requirement",
    "source_reference",
    "speaker_note",
    "items",
    "reason",
    "alternatives",
    "claim_ids",
)


def fixture_confirmation_allowed(project: Path) -> bool:
    project = project.resolve()
    for trusted_root in (ROOT / "examples", ROOT / "tests" / "fixtures"):
        try:
            project.relative_to(trusted_root.resolve())
        except ValueError:
            continue
        return True
    return os.environ.get("GHB_PPT_TEST_FIXTURE") == "1"


def issue(code: str, message: str, path: Path | None = None) -> dict[str, str]:
    result = {"severity": "error", "code": code, "message": message}
    if path is not None:
        result["path"] = str(path)
    return result


def default_visual_profile() -> dict[str, Any]:
    """Return the neutral GHB v1 scaffold; it contains no page-specific decisions."""
    return {
        "schema": "ghb.visual-profile.v1",
        "brand": {
            "primary": "#AB1F29",
            "text": "#2B2B2B",
            "surface": "#FFFFFF",
        },
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
        "occupancy": {"body": {"min": 0.42, "max": 0.78}},
        "composition": {
            "default_density": "balanced",
            "default_emphasis": "ranked",
        },
        "focal": {"allowed_zones": ["left", "center", "right", "full"]},
        "deck_rhythm": {"default_role": "continuity", "max_same_role_streak": 3},
        "budgets": {"max_text_chars": 240, "max_nodes": 8},
    }


def default_art_direction() -> dict[str, Any]:
    """Return a scaffold that must be completed after content confirmation."""
    return {
        "schema": "ghb.art-direction.v1",
        "design_mode": "instructional",
        "visual_thesis": None,
        "narrative_arc": ["orient", "explain", "prove", "decide"],
        "page_families": ["editorial", "evidence", "comparison", "process", "decision"],
        "surface_strategy": {
            "variants": ["light", "contrast", "evidence"],
            "max_same_variant_streak": 2,
        },
        "focal_strategy": {
            "max_distributed_streak": 4,
        },
        "anchor_slide_ids": [],
        "imagery": {
            "strategy": "evidence-first",
            "max_images_per_page": 2,
        },
    }


def validate_art_direction(path: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    payload = read_json(path, issues)
    if not isinstance(payload, dict):
        return issues or [issue("invalid-art-direction", "art_direction.json must be an object", path)]
    if payload.get("schema") != "ghb.art-direction.v1":
        issues.append(issue(
            "invalid-art-direction-schema",
            "schema major must be ghb.art-direction.v1",
            path,
        ))
    surface = payload.get("surface_strategy")
    variants = surface.get("variants") if isinstance(surface, dict) else None
    focal = payload.get("focal_strategy")
    imagery = payload.get("imagery")
    anchors = payload.get("anchor_slide_ids")
    incomplete = (
        payload.get("design_mode") not in MODES
        or not _nonempty(payload.get("visual_thesis"))
        or not isinstance(payload.get("narrative_arc"), list)
        or len(payload.get("narrative_arc", [])) < 3
        or any(not isinstance(item, str) or not item.strip() for item in payload.get("narrative_arc", []))
        or not isinstance(payload.get("page_families"), list)
        or len(payload.get("page_families", [])) < 3
        or any(not isinstance(item, str) or not item.strip() for item in payload.get("page_families", []))
        or not isinstance(variants, list)
        or any(not isinstance(item, str) or not item.strip() for item in variants)
        or len(set(variants)) < 2
        or not isinstance(surface.get("max_same_variant_streak") if isinstance(surface, dict) else None, int)
        or (surface.get("max_same_variant_streak", 0) if isinstance(surface, dict) else 0) <= 0
        or not isinstance(focal, dict)
        or not isinstance(focal.get("max_distributed_streak"), int)
        or focal.get("max_distributed_streak", 0) <= 0
        or not isinstance(anchors, list)
        or not anchors
        or any(not isinstance(item, str) or not item.strip() for item in anchors)
        or not isinstance(imagery, dict)
        or imagery.get("strategy") not in {"none", "evidence-first", "editorial", "data-led"}
        or not isinstance(imagery.get("max_images_per_page"), int)
        or not 0 <= imagery.get("max_images_per_page", -1) <= 2
    )
    if incomplete:
        issues.append(issue(
            "incomplete-art-direction",
            "art direction requires a visual thesis, narrative arc, page families, surface rhythm, anchors, and imagery policy",
            path,
        ))
    return issues


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate_visual_profile(path: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    payload = read_json(path, issues)
    if not isinstance(payload, dict):
        return issues or [issue("invalid-visual-profile", "visual_profile.json must be an object", path)]
    if payload.get("schema") != "ghb.visual-profile.v1":
        issues.append(issue(
            "invalid-visual-profile-schema",
            "schema major must be ghb.visual-profile.v1",
            path,
        ))
    brand = payload.get("brand")
    expected_brand = {"primary": "#AB1F29", "text": "#2B2B2B", "surface": "#FFFFFF"}
    if not isinstance(brand, dict) or any(brand.get(key) != value for key, value in expected_brand.items()):
        issues.append(issue("invalid-visual-profile-brand", "brand must preserve the GHB primary, text, and surface constants", path))

    typography = payload.get("typography")
    typography_fields = (
        "min_title_pt",
        "min_body_pt",
        "min_caption_pt",
        "min_source_pt",
        "min_footer_pt",
        "min_title_body_ratio",
    )
    if not isinstance(typography, dict) or typography.get("enforcement") != "strict" or any(
        not _positive_number(typography.get(field))
        for field in typography_fields
    ) or (
        isinstance(typography, dict)
        and _positive_number(typography.get("min_title_pt"))
        and _positive_number(typography.get("min_body_pt"))
        and not (
            typography["min_title_pt"] >= typography["min_body_pt"]
            >= typography["min_caption_pt"] >= typography["min_source_pt"]
            >= typography["min_footer_pt"]
        )
    ):
        issues.append(issue(
            "invalid-visual-profile-typography",
            "strict typography role floors and title/body ratio must be positive and ordered",
            path,
        ))

    spacing = payload.get("spacing")
    if not isinstance(spacing, dict) or any(
        not _positive_number(spacing.get(field)) for field in ("base_unit", "min_component_gap")
    ):
        issues.append(issue("invalid-visual-profile-spacing", "spacing requires positive base_unit and min_component_gap", path))

    occupancy = payload.get("occupancy")
    body = occupancy.get("body") if isinstance(occupancy, dict) else None
    if not isinstance(body, dict) or not all(
        isinstance(body.get(field), (int, float)) and not isinstance(body.get(field), bool)
        for field in ("min", "max")
    ) or not (0 <= body["min"] < body["max"] <= 1):
        issues.append(issue("invalid-visual-profile-occupancy", "occupancy.body must satisfy 0 <= min < max <= 1", path))

    composition = payload.get("composition")
    if not isinstance(composition, dict) or composition.get("default_density") not in PAGE_DENSITIES or composition.get("default_emphasis") not in EMPHASIS_INTENTS:
        issues.append(issue("invalid-visual-profile-composition", "composition defaults must use the v1 density and emphasis vocabulary", path))

    focal = payload.get("focal")
    zones = focal.get("allowed_zones") if isinstance(focal, dict) else None
    if not isinstance(zones, list) or not zones or any(not _nonempty(zone) for zone in zones):
        issues.append(issue("invalid-visual-profile-focal", "focal.allowed_zones must be a non-empty string list", path))

    rhythm = payload.get("deck_rhythm")
    if not isinstance(rhythm, dict) or rhythm.get("default_role") not in RHYTHM_ROLES or not _positive_number(rhythm.get("max_same_role_streak")):
        issues.append(issue("invalid-visual-profile-rhythm", "deck_rhythm requires a v1 default_role and positive max_same_role_streak", path))

    budgets = payload.get("budgets")
    if not isinstance(budgets, dict) or any(
        not isinstance(budgets.get(field), int) or isinstance(budgets.get(field), bool) or budgets[field] <= 0
        for field in ("max_text_chars", "max_nodes")
    ):
        issues.append(issue("invalid-visual-profile-budgets", "budgets require positive integer max_text_chars and max_nodes", path))
    return issues


def _layout_variant_matches(layout: Any, variant: str) -> bool:
    family = variant.split("/", 1)[0]
    if layout == "matrix":
        return family in {"matrix", "comparison"}
    return family == layout


def validate_page_schema(
    schema: Any,
    *,
    row: dict[str, Any],
    path: Path,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    label = str(row.get("slide_id") or row.get("slide") or "unknown")
    if not isinstance(schema, dict):
        return [issue("missing-page-schema", f"slide {label}: page_schema must be a nested object", path)]
    if schema.get("schema") != "ghb.page-schema.v1":
        issues.append(issue("invalid-page-schema-schema", f"slide {label}: schema major must be ghb.page-schema.v1", path))
    if schema.get("slide_id") != row.get("slide_id"):
        issues.append(issue("page-schema-slide-id-drift", f"slide {label}: page_schema.slide_id must match the layout row", path))
    if schema.get("page_purpose") not in PAGE_PURPOSES:
        issues.append(issue("invalid-page-schema-purpose", f"slide {label}: page_purpose is not in the supported presentation taxonomy", path))
    if schema.get("density") not in PAGE_DENSITIES:
        issues.append(issue("invalid-page-schema-density", f"slide {label}: density must be breathing, balanced, or dense", path))
    legacy_density = row.get("density") or row.get("content_density")
    migrated_density = {"anchor": "balanced", "breathing": "breathing", "dense": "dense"}.get(legacy_density)
    if migrated_density is not None and schema.get("density") in PAGE_DENSITIES and schema.get("density") != migrated_density:
        issues.append(issue("page-schema-density-drift", f"slide {label}: page density does not match the explicit legacy migration mapping", path))
    if schema.get("rhythm_role") not in RHYTHM_ROLES:
        issues.append(issue("invalid-page-schema-rhythm", f"slide {label}: rhythm_role must be anchor, continuity, or transition", path))
    emphasis = schema.get("emphasis")
    if emphasis not in EMPHASIS_INTENTS:
        issues.append(issue("invalid-page-schema-emphasis", f"slide {label}: emphasis must use the v1 vocabulary", path))
    if emphasis == "single-focal" and not (_nonempty(schema.get("focal_target")) or _nonempty(schema.get("focal_zone"))):
        issues.append(issue("page-schema-missing-focal-target", f"slide {label}: single-focal emphasis requires focal_target or focal_zone", path))
    focal_zone = schema.get("focal_zone")
    allowed_zones = profile.get("focal", {}).get("allowed_zones", []) if isinstance(profile, dict) else []
    if focal_zone is not None and (not isinstance(focal_zone, str) or focal_zone not in allowed_zones):
        issues.append(issue("invalid-page-schema-focal-zone", f"slide {label}: focal_zone must be allowed by the visual profile", path))

    variant = schema.get("layout_variant")
    layout = row.get("layout_archetype") or row.get("layout_type")
    variant_is_well_formed = (
        isinstance(variant, str)
        and "/" in variant
        and all(part.strip() for part in variant.split("/", 1))
    )
    if not variant_is_well_formed:
        issues.append(issue("invalid-page-schema-layout-variant", f"slide {label}: layout_variant must be <family>/<variant>", path))
    elif not _layout_variant_matches(layout, variant):
        issues.append(issue("page-schema-layout-variant-drift", f"slide {label}: layout_variant {variant!r} does not match {layout!r}", path))

    budgets = schema.get("budgets")
    max_profile = profile.get("budgets") if isinstance(profile, dict) and isinstance(profile.get("budgets"), dict) else {}
    if not isinstance(budgets, dict) or any(
        not isinstance(budgets.get(field), int)
        or isinstance(budgets.get(field), bool)
        or budgets[field] <= 0
        or (isinstance(max_profile.get(field), int) and budgets[field] > max_profile[field])
        for field in ("max_text_chars", "max_nodes")
    ):
        issues.append(issue("invalid-page-schema-budgets", f"slide {label}: budgets must be positive integers within profile maxima", path))
    else:
        items = row.get("items") if isinstance(row.get("items"), list) else []
        if len(items) > budgets["max_nodes"]:
            issues.append(issue("page-schema-node-budget-exceeded", f"slide {label}: item count exceeds max_nodes", path))
        text_chars = len(str(row.get("key_message") or row.get("message") or "")) + sum(len(str(item)) for item in items)
        if text_chars > budgets["max_text_chars"]:
            issues.append(issue("page-schema-text-budget-exceeded", f"slide {label}: authored message and items exceed max_text_chars", path))

    bounds = schema.get("bounds_override")
    if bounds is not None:
        valid = isinstance(bounds, dict) and all(_positive_number(bounds.get(field)) for field in ("width", "height")) and all(
            isinstance(bounds.get(field), (int, float)) and not isinstance(bounds.get(field), bool) and bounds[field] >= 0
            for field in ("x", "y")
        )
        if valid:
            valid = bounds["x"] + bounds["width"] <= 1280 and bounds["y"] + bounds["height"] <= 720
        if not valid:
            issues.append(issue("invalid-page-schema-bounds-override", f"slide {label}: bounds_override must fit the 1280x720 canvas", path))
    return issues


def find_scaffold_markers(project: Path) -> list[str]:
    """Return relative paths of scaffold drafts that must be finalized before release.

    ``plan`` writes deterministic drafts marked with ``needs_review``/``draft``/
    ``origin: scaffold``. These are fine for iteration but must be cleared before a
    release build so a scaffold cannot masquerade as finished authoring.
    """
    project = project.resolve()
    markers: list[str] = []
    for relative in (
        "content_model.json",
        "layout_plan.json",
        "art_direction.json",
        "visual_profile.json",
    ):
        path = project / relative
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _payload_has_scaffold_marker(payload):
            markers.append(relative)
    return markers


def _payload_has_scaffold_marker(payload: Any) -> bool:
    if isinstance(payload, dict):
        if payload.get("needs_review") is True or payload.get("draft") is True:
            return True
        if payload.get("origin") == "scaffold":
            return True
        return any(_payload_has_scaffold_marker(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_payload_has_scaffold_marker(value) for value in payload)
    return False


def read_json(path: Path, issues: list[dict[str, str]]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(issue("invalid-json", f"cannot read valid JSON: {exc}", path))
        return None


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value) or value == []
    return value is not None


def confirmation_digest(decisions: dict[str, Any]) -> str:
    canonical = json.dumps(decisions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_confirmation(project: Path) -> list[dict[str, str]]:
    path = project / "confirmation.json"
    if not path.is_file():
        return [issue(
            "missing-confirmation",
            "confirmation.json is required; record all six user decisions before authoring",
            path,
        )]
    issues: list[dict[str, str]] = []
    payload = read_json(path, issues)
    if not isinstance(payload, dict):
        return issues or [issue("invalid-confirmation", "confirmation must be a JSON object", path)]
    if payload.get("schema") != "ghb.confirmation.v1":
        issues.append(issue("invalid-confirmation-schema", "schema must be ghb.confirmation.v1", path))
    if payload.get("status") != "confirmed":
        issues.append(issue("unconfirmed-project", "status must be confirmed", path))
    if payload.get("confirmation_source") not in SOURCES:
        issues.append(issue(
            "invalid-confirmation-source",
            "confirmation_source must be user or fixture",
            path,
        ))
    elif payload.get("confirmation_source") == "fixture" and not fixture_confirmation_allowed(project):
        issues.append(issue(
            "fixture-confirmation-outside-test-context",
            "fixture confirmation is restricted to repository examples/tests or GHB_PPT_TEST_FIXTURE=1 test runs",
            path,
        ))
    if not _nonempty(payload.get("confirmed_at")):
        issues.append(issue("missing-confirmed-at", "confirmed_at is required", path))
    else:
        try:
            datetime.fromisoformat(str(payload["confirmed_at"]).replace("Z", "+00:00"))
        except ValueError:
            issues.append(issue("invalid-confirmed-at", "confirmed_at must be an ISO-8601 timestamp", path))
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        issues.append(issue("incomplete-confirmation", "decisions must contain all six decisions", path))
        return issues
    expected_digest = confirmation_digest(decisions)
    if payload.get("decision_digest") != expected_digest:
        issues.append(issue(
            "confirmation-digest-mismatch",
            "decision_digest is missing or does not match the confirmed decisions; reconfirm after edits",
            path,
        ))
    missing = [name for name in CONFIRMATION_FIELDS if not _nonempty(decisions.get(name))]
    if missing:
        issues.append(issue(
            "incomplete-confirmation",
            f"missing or empty decisions: {', '.join(missing)}",
            path,
        ))
    if decisions.get("mode") not in MODES:
        issues.append(issue("invalid-mode", f"mode must be one of {sorted(MODES)}", path))
    outline = decisions.get("outline")
    if not isinstance(outline, list) or not outline or any(
        not isinstance(row, dict) or not _nonempty(row.get("title")) or row.get("rhythm") not in {"anchor", "dense", "breathing"}
        for row in outline
    ):
        issues.append(issue(
            "invalid-outline-confirmation",
            "outline must contain title and anchor/dense/breathing rhythm for every body slide",
            path,
        ))
    tradeoffs = decisions.get("content_tradeoffs")
    if not isinstance(tradeoffs, dict) or any(key not in tradeoffs for key in ("expand", "omit", "combine")):
        issues.append(issue(
            "invalid-content-tradeoffs",
            "content_tradeoffs must explicitly contain expand, omit, and combine lists",
            path,
        ))
    assets = decisions.get("visual_assets")
    if not isinstance(assets, dict) or not _nonempty(assets.get("image_source")) or not _nonempty(assets.get("icon_set")):
        issues.append(issue(
            "invalid-visual-assets",
            "visual_assets must explicitly contain image_source and icon_set",
            path,
        ))
    return issues


def _plan_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("slides"), list):
        return [row for row in payload["slides"] if isinstance(row, dict)]
    return []


def validate_layout_semantics(path: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    payload = read_json(path, issues)
    if payload is None:
        return issues
    raw_rows = payload if isinstance(payload, list) else payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
        return issues + [issue("invalid-layout-plan", "layout plan must be a list of slide objects", path)]
    rows = _plan_rows(payload)
    if not rows:
        return issues + [issue("empty-layout-plan", "layout_plan.json has no slide records", path)]
    for index, row in enumerate(rows, start=1):
        missing = [field for field in LAYOUT_REQUIRED_FIELDS if not _nonempty(row.get(field))]
        if missing:
            issues.append(issue(
                "incomplete-layout-row",
                f"slide {index} missing required fields: {', '.join(missing)}",
                path,
            ))
        layout = row.get("layout_archetype") or row.get("layout_type")
        label = row.get("slide_id") or row.get("slide") or index
        if layout == "timeline" and not _nonempty(row.get("order_signal")):
            issues.append(issue(
                "timeline-missing-order",
                f"slide {label}: timeline requires order_signal with dates, phases, or sequence rationale",
                path,
            ))
        elif layout == "matrix":
            axes = row.get("axes")
            if not isinstance(axes, dict) or not _nonempty(axes.get("x")) or not _nonempty(axes.get("y")):
                issues.append(issue("matrix-missing-axes", f"slide {label}: matrix requires x/y axes", path))
        elif layout == "swimlane":
            owners = row.get("owners")
            if not isinstance(owners, list) or len(owners) < 2:
                issues.append(issue("swimlane-missing-owners", f"slide {label}: swimlane requires at least two owners", path))
        elif layout == "flywheel" and not _nonempty(row.get("loop_closure")):
            issues.append(issue("flywheel-missing-loop", f"slide {label}: flywheel requires loop_closure", path))
        elif layout == "comparison":
            criteria = row.get("comparison_criteria")
            if not isinstance(criteria, list) or not criteria:
                issues.append(issue("comparison-missing-criteria", f"slide {label}: comparison requires shared criteria", path))
    return issues


def validate_content_model(path: Path, layout_path: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    payload = read_json(path, issues)
    if not isinstance(payload, dict):
        return issues or [issue("invalid-content-model", "content_model.json must be an object", path)]
    if payload.get("schema") != "ghb.content-model.v1":
        issues.append(issue("invalid-content-model-schema", "schema must be ghb.content-model.v1", path))
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        issues.append(issue("empty-content-model", "content_model.json requires claims", path))
        return issues
    claim_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict) or not _nonempty(claim.get("id")) or not _nonempty(claim.get("statement")):
            issues.append(issue("invalid-claim", "every claim requires id and statement", path))
            continue
        claim_id = str(claim["id"])
        if claim_id in claim_ids:
            issues.append(issue("duplicate-claim-id", f"duplicate claim id: {claim_id}", path))
        claim_ids.add(claim_id)
        if claim.get("must_include") is True and not _nonempty(claim.get("source_reference")):
            issues.append(issue("untraceable-required-claim", f"claim {claim['id']} requires source_reference", path))
    if layout_path.is_file():
        layout_payload = read_json(layout_path, issues)
        rows = _plan_rows(layout_payload)
        invalid_rows = [
            row.get("slide_id") or row.get("slide")
            for row in rows
            if not isinstance(row.get("claim_ids"), list) or not row.get("claim_ids")
        ]
        if invalid_rows:
            issues.append(issue(
                "invalid-page-claim-mapping",
                f"every page requires a non-empty claim_ids list; invalid slides: {invalid_rows}",
                layout_path,
            ))
        used = {
            str(claim_id)
            for row in rows
            for claim_id in (row.get("claim_ids") if isinstance(row.get("claim_ids"), list) else [])
        }
        required = {str(claim["id"]) for claim in claims if isinstance(claim, dict) and claim.get("must_include") is True and claim.get("id")}
        missing = sorted(required - used)
        if missing:
            issues.append(issue("unmapped-required-claims", f"required claims missing from layout plan: {', '.join(missing)}", layout_path))
        unknown = sorted(used - claim_ids)
        if unknown:
            issues.append(issue("unknown-claim-reference", f"layout plan references unknown claims: {', '.join(unknown)}", layout_path))
    return issues


def validate_confirmation_plan_alignment(project: Path) -> list[dict[str, str]]:
    confirmation_path = project / "confirmation.json"
    layout_path = project / "layout_plan.json"
    if not confirmation_path.is_file() or not layout_path.is_file():
        return []
    issues: list[dict[str, str]] = []
    confirmation = read_json(confirmation_path, issues)
    layout = read_json(layout_path, issues)
    if not isinstance(confirmation, dict):
        return issues
    decisions = confirmation.get("decisions")
    outline = decisions.get("outline") if isinstance(decisions, dict) else None
    rows = _plan_rows(layout)
    if not isinstance(outline, list) or not rows:
        return issues
    confirmed_titles = [str(row.get("title", "")).strip() for row in outline if isinstance(row, dict)]
    planned_titles = [
        str(row.get("key_message") or row.get("message") or row.get("title") or "").strip()
        for row in rows
    ]
    if len(confirmed_titles) != len(planned_titles) or confirmed_titles != planned_titles:
        issues.append(issue(
            "confirmation-plan-drift",
            "confirmed outline titles/count no longer match layout_plan.json; reconfirm the revised plan",
            layout_path,
        ))
    confirmed_rhythms = [row.get("rhythm") for row in outline if isinstance(row, dict)]
    planned_rhythms = [row.get("rhythm") or row.get("density") or row.get("content_density") for row in rows]
    if len(confirmed_rhythms) == len(planned_rhythms) and confirmed_rhythms != planned_rhythms:
        issues.append(issue(
            "confirmation-plan-drift",
            "confirmed outline rhythm no longer matches layout_plan.json; reconfirm the revised plan",
            layout_path,
        ))
    audience = decisions.get("audience") if isinstance(decisions, dict) else None
    if any(row.get("audience") != audience for row in rows):
        issues.append(issue(
            "confirmation-plan-drift",
            "layout plan audience no longer matches the confirmed audience",
            layout_path,
        ))
    svg_count = len(list((project / "svg_output").glob("*.svg")))
    if svg_count and svg_count != len(outline):
        issues.append(issue(
            "confirmation-plan-drift",
            f"authored SVG count ({svg_count}) no longer matches confirmed outline count ({len(outline)})",
            project / "svg_output",
        ))
    return issues


def validate_project_contract(
    project: Path,
    *,
    confirmation_only: bool = False,
    skip_required_files: bool = False,
    require_visual_contract: bool = False,
) -> list[dict[str, str]]:
    project = project.resolve()
    issues = validate_confirmation(project)
    if confirmation_only:
        return issues
    required = (
        "sources/source.md",
        "design_spec.md",
        "spec_lock.md",
        "content_model.json",
        "layout_plan.json",
    )
    if not skip_required_files:
        for relative in required:
            path = project / relative
            if not path.is_file():
                issues.append(issue("missing-project-artifact", f"required project artifact missing: {relative}", path))
        svg_dir = project / "svg_output"
        if not svg_dir.is_dir() or not any(svg_dir.glob("*.svg")):
            issues.append(issue("missing-authored-svg", "svg_output must contain authored SVG files", svg_dir))
    layout_path = project / "layout_plan.json"
    profile_path = project / "visual_profile.json"
    art_direction_path = project / "art_direction.json"
    profile: dict[str, Any] | None = None
    art_direction: dict[str, Any] | None = None
    if profile_path.is_file():
        issues.extend(validate_visual_profile(profile_path))
        profile_payload = read_json(profile_path, issues)
        profile = profile_payload if isinstance(profile_payload, dict) else None
    elif require_visual_contract:
        issues.append(issue(
            "missing-visual-profile",
            "visual_profile.json is required by the explicit visual-contract gate",
            profile_path,
        ))
    if art_direction_path.is_file():
        issues.extend(validate_art_direction(art_direction_path))
        art_payload = read_json(art_direction_path, issues)
        art_direction = art_payload if isinstance(art_payload, dict) else None
        confirmation_path = project / "confirmation.json"
        if art_direction is not None and confirmation_path.is_file():
            try:
                confirmation_payload = json.loads(confirmation_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                confirmation_payload = None
            decisions = (
                confirmation_payload.get("decisions")
                if isinstance(confirmation_payload, dict)
                else None
            )
            confirmed_mode = decisions.get("mode") if isinstance(decisions, dict) else None
            if confirmed_mode in MODES and art_direction.get("design_mode") != confirmed_mode:
                issues.append(issue(
                    "art-direction-mode-drift",
                    "art_direction.json design_mode no longer matches the confirmed presentation mode",
                    art_direction_path,
                ))
    elif require_visual_contract:
        issues.append(issue(
            "missing-art-direction",
            "art_direction.json is required by the visual-contract gate",
            art_direction_path,
        ))
    if layout_path.is_file():
        issues.extend(validate_layout_semantics(layout_path))
        issues.extend(validate_confirmation_plan_alignment(project))
        layout_payload = read_json(layout_path, issues)
        visual_rows = _plan_rows(layout_payload)
        slide_ids = [row.get("slide_id") for row in visual_rows if _nonempty(row.get("slide_id"))]
        if len(slide_ids) != len(set(slide_ids)):
            issues.append(issue("duplicate-slide-id", "layout_plan.json slide_id values must be unique", layout_path))
        if art_direction is not None:
            anchors = art_direction.get("anchor_slide_ids")
            if isinstance(anchors, list):
                missing_anchors = sorted(
                    anchor
                    for anchor in anchors
                    if isinstance(anchor, str) and anchor not in set(slide_ids)
                )
                if missing_anchors:
                    issues.append(issue(
                        "art-direction-anchor-missing-slide",
                        f"art direction anchor IDs are absent from layout_plan.json: {missing_anchors}",
                        art_direction_path,
                    ))
        for row in visual_rows:
            if "page_schema" in row or require_visual_contract:
                issues.extend(validate_page_schema(
                    row.get("page_schema"), row=row, path=layout_path, profile=profile
                ))
    elif require_visual_contract:
        issues.append(issue(
            "missing-layout-plan",
            "layout_plan.json is required by the explicit visual-contract gate",
            layout_path,
        ))
    content_model = project / "content_model.json"
    if content_model.is_file():
        issues.extend(validate_content_model(content_model, layout_path))
    if not confirmation_only:
        markers = find_scaffold_markers(project)
        if markers:
            issues.append(issue(
                "plan-draft-not-finalized",
                "scaffold drafts still carry needs_review/draft/origin markers; finalize "
                f"and remove them before build: {', '.join(markers)}",
                project,
            ))
    return issues


def validate_plan(project: Path) -> list[dict[str, str]]:
    """Guidance-level check run by ``check-plan`` before authoring SVGs.

    Structural drift (dangling claim references, missing anchors) is reported as
    ``error``; unfinalized scaffold drafts are reported as ``advisory`` so an
    author can iterate. A release build still blocks on the drafts via
    :func:`validate_project_contract`.
    """
    project = project.resolve()
    issues: list[dict[str, str]] = []
    layout_path = project / "layout_plan.json"
    content_path = project / "content_model.json"
    if content_path.is_file() and layout_path.is_file():
        drift = [
            item
            for item in validate_content_model(content_path, layout_path)
            if item.get("code")
            in {"unknown-claim-reference", "invalid-page-claim-mapping", "unmapped-required-claims"}
        ]
        for item in drift:
            issues.append(issue("plan-contract-drift", item["message"], layout_path))
    art_path = project / "art_direction.json"
    if art_path.is_file() and layout_path.is_file():
        art_payload = read_json(art_path, issues)
        layout_payload = read_json(layout_path, issues)
        anchors = art_payload.get("anchor_slide_ids") if isinstance(art_payload, dict) else None
        slide_ids = {
            row.get("slide_id")
            for row in _plan_rows(layout_payload)
            if _nonempty(row.get("slide_id"))
        }
        if isinstance(anchors, list):
            missing = sorted(
                anchor
                for anchor in anchors
                if isinstance(anchor, str) and anchor and anchor not in slide_ids
            )
            if missing:
                issues.append(issue(
                    "plan-contract-drift",
                    f"art direction anchor IDs are absent from layout_plan.json: {missing}",
                    art_path,
                ))
    for relative in find_scaffold_markers(project):
        result = {
            "severity": "advisory",
            "code": "plan-draft-not-finalized",
            "message": f"{relative} still carries scaffold markers; refine and remove them before build",
            "path": str(project / relative),
        }
        issues.append(result)
    if layout_path.is_file():
        layout_payload = read_json(layout_path, issues)
        for row in _plan_rows(layout_payload):
            fit = score_layout_fit(row)
            if fit is not None and fit["score"] < 70:
                issues.append({
                    "severity": "advisory",
                    "code": "layout-fit-score-low",
                    "message": (
                        f"slide {row.get('slide_id') or row.get('slide')}: "
                        f"{fit['archetype']} fit score {fit['score']}/100; "
                        f"{fit['suggestion']}"
                    ),
                    "path": str(layout_path),
                    "score": str(fit["score"]),
                })
    return issues


def score_layout_fit(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return an explainable semantic-fit score for constrained archetypes."""

    schema = row.get("page_schema") if isinstance(row.get("page_schema"), dict) else {}
    variant = str(schema.get("layout_variant") or row.get("layout_archetype") or "")
    archetype = variant.split("/", 1)[0]
    if archetype == "comparison":
        archetype = "matrix"
    if archetype == "timeline":
        sequence = row.get("time_order") or row.get("sequence")
        if isinstance(sequence, list) and len(sequence) >= 2:
            return {"archetype": archetype, "score": 100, "suggestion": "time order is explicit"}
        return {
            "archetype": archetype,
            "score": 35,
            "suggestion": "declare at least two ordered time/sequence markers or choose a non-timeline layout",
        }
    if archetype == "matrix":
        criteria = row.get("comparison_criteria")
        axes = row.get("axes")
        if isinstance(criteria, list) and len(criteria) >= 2:
            return {"archetype": archetype, "score": 100, "suggestion": "shared comparison criteria are explicit"}
        if isinstance(axes, dict) and all(str(axes.get(key) or "").strip() for key in ("x", "y")):
            return {"archetype": archetype, "score": 100, "suggestion": "both matrix axes are explicit"}
        return {
            "archetype": archetype,
            "score": 40,
            "suggestion": "declare two shared comparison criteria or explicit x/y axes",
        }
    if archetype == "flywheel":
        closure = row.get("loop_closure")
        if isinstance(closure, str) and closure.strip():
            return {"archetype": archetype, "score": 100, "suggestion": "loop closure is explicit"}
        return {
            "archetype": archetype,
            "score": 30,
            "suggestion": "state how the last stage feeds the first, or choose a linear process layout",
        }
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--confirmation-only", action="store_true")
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Run the guidance-level plan check (advisory scaffold drafts, structural drift)",
    )
    parser.add_argument(
        "--require-visual-contract",
        action="store_true",
        help="Require visual_profile.json and a valid nested page_schema on every layout row",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.plan_only:
        issues = validate_plan(args.project)
        blocking = [item for item in issues if item.get("severity") != "advisory"]
        payload = {"passed": not blocking, "issues": issues}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("PASS" if not blocking else "FAIL")
            for item in issues:
                level = item.get("severity", "error").upper()
                print(f"{level} [{item['code']}] {item['message']}")
        return 0 if not blocking else 1
    issues = validate_project_contract(
        args.project,
        confirmation_only=args.confirmation_only,
        require_visual_contract=args.require_visual_contract,
    )
    payload = {"passed": not issues, "issues": issues}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("PASS" if not issues else "FAIL")
        for item in issues:
            print(f"ERROR [{item['code']}] {item['message']}")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
