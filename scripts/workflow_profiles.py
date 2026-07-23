#!/usr/bin/env python3
"""Workflow profiles and the simplified Standard contract adapter.

Standard projects are authored through two small files (``brief.json`` and
``deck_plan.json``).  The existing converters and validators still consume the
legacy contract files, so this module deterministically projects the compact
authoring contract into those compatibility artifacts.  Generated projections
are explicitly marked and may be refreshed; hand-authored legacy files are
never overwritten.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOW_MODES = ("quick", "standard", "strict")
GENERATED_ORIGIN = "standard-projection"
CONTENT_PROFILES = frozenset({"consulting-evidence-cn-v1"})
CONSULTING_CLAIM_TYPES = frozenset({"fact", "inference", "recommendation"})
CONSULTING_SO_WHAT_TYPES = frozenset({"inference", "recommendation"})


class WorkflowProfileError(RuntimeError):
    """Raised when a simplified workflow contract is incomplete or unsafe."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowProfileError(f"cannot read valid JSON from {path}: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generated(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = _read_json(path)
    except WorkflowProfileError:
        return False
    return isinstance(payload, dict) and payload.get("origin") == GENERATED_ORIGIN


def write_workflow_config(project: Path, mode: str) -> Path:
    if mode not in WORKFLOW_MODES:
        raise WorkflowProfileError(f"unsupported workflow mode: {mode}")
    path = project / "workflow.json"
    _write_json(path, {"schema": "ghb.workflow.v1", "mode": mode})
    return path


def workflow_mode(project: Path, requested: str | None = None) -> str:
    if requested:
        if requested not in WORKFLOW_MODES:
            raise WorkflowProfileError(f"unsupported workflow mode: {requested}")
        return requested
    path = project / "workflow.json"
    if path.is_file():
        payload = _read_json(path)
        mode = payload.get("mode") if isinstance(payload, dict) else None
        if mode in WORKFLOW_MODES:
            return str(mode)
    return "standard"


def seed_simplified_contract(project: Path) -> list[Path]:
    """Create non-committal Standard templates without fabricating confirmation."""
    written: list[Path] = []
    brief = project / "brief.json"
    if not brief.exists():
        _write_json(
            brief,
            {
                "schema": "ghb.brief.v1",
                "status": "pending",
                "confirmation_source": None,
                "confirmed_at": None,
                "audience": None,
                "purpose": None,
                "duration_minutes": None,
                "page_count": None,
                "mode": "briefing",
                "visual_style": "professional-modern",
                "template": "GHB default",
                "assets": {"image_source": "none", "icon_set": "none"},
            },
        )
        written.append(brief)
    plan = project / "deck_plan.json"
    if not plan.exists():
        _write_json(
            plan,
            {
                "schema": "ghb.deck-plan.v1",
                "story": {"opening": None, "development": None, "ending": None},
                "style": {"tone": None, "density": "balanced", "variation": "high"},
                "slides": [],
            },
        )
        written.append(plan)
    return written


def _validate_brief(brief: Any, path: Path) -> dict[str, Any]:
    if not isinstance(brief, dict) or brief.get("schema") != "ghb.brief.v1":
        raise WorkflowProfileError(f"{path} must use schema ghb.brief.v1")
    if brief.get("status") != "confirmed":
        raise WorkflowProfileError(f"{path} must have status=confirmed before Standard build")
    required = ("audience", "purpose", "page_count", "mode", "visual_style")
    missing = [name for name in required if not str(brief.get(name) or "").strip()]
    if missing:
        raise WorkflowProfileError(f"{path} missing confirmed fields: {', '.join(missing)}")
    if brief.get("mode") not in {"instructional", "briefing", "narrative"}:
        raise WorkflowProfileError(f"{path} mode must be instructional, briefing, or narrative")
    if brief.get("confirmation_source") not in {"user", "fixture"}:
        raise WorkflowProfileError(f"{path} confirmation_source must be user or fixture")
    if not str(brief.get("confirmed_at") or "").strip():
        raise WorkflowProfileError(f"{path} confirmed_at is required")
    return brief


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _content_profile(plan: dict[str, Any], path: Path) -> str | None:
    style = plan.get("style")
    if not isinstance(style, dict):
        return None
    profile = style.get("content_profile")
    if profile in (None, ""):
        return None
    if not isinstance(profile, str) or profile not in CONTENT_PROFILES:
        raise WorkflowProfileError(f"{path} has unsupported content_profile: {profile!r}")
    return profile


def _validate_consulting_content(content: Any, slide: dict[str, Any], index: int, path: Path) -> None:
    if not isinstance(content, dict):
        raise WorkflowProfileError(f"{path} slide {index} consulting_content must be an object")
    claim_type = content.get("claim_type")
    if claim_type not in CONSULTING_CLAIM_TYPES:
        raise WorkflowProfileError(
            f"{path} slide {index} consulting_content.claim_type must be one of "
            f"{', '.join(sorted(CONSULTING_CLAIM_TYPES))}"
        )

    evidence = content.get("evidence")
    if evidence is not None and not isinstance(evidence, list):
        raise WorkflowProfileError(f"{path} slide {index} consulting_content.evidence must be a list")
    if claim_type == "fact" and not evidence:
        raise WorkflowProfileError(
            f"{path} slide {index} fact consulting_content requires at least one evidence item"
        )

    source_refs = slide.get("source_refs")
    if claim_type == "fact":
        if not isinstance(source_refs, list) or not source_refs or not all(
            _nonempty_text(ref) for ref in source_refs
        ):
            raise WorkflowProfileError(
                f"{path} slide {index} fact consulting_content requires non-empty source_refs"
            )
    known_source_refs = {str(ref).strip() for ref in source_refs or [] if _nonempty_text(ref)}

    for evidence_index, item in enumerate(evidence or [], start=1):
        if not isinstance(item, dict):
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.evidence {evidence_index} must be an object"
            )
        if not _nonempty_text(item.get("label")):
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.evidence {evidence_index} missing label"
            )
        value = item.get("value")
        if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.evidence {evidence_index} missing value"
            )
        source_ref = item.get("source_ref")
        if not _nonempty_text(source_ref):
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.evidence {evidence_index} missing source_ref"
            )
        if claim_type == "fact" and source_ref.strip() not in known_source_refs:
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.evidence {evidence_index} "
                "source_ref must match one source_refs entry"
            )

    so_what = content.get("so_what")
    if so_what is not None:
        if not isinstance(so_what, dict):
            raise WorkflowProfileError(f"{path} slide {index} consulting_content.so_what must be an object")
        if so_what.get("type") not in CONSULTING_SO_WHAT_TYPES:
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.so_what.type must be inference or recommendation"
            )
        if not _nonempty_text(so_what.get("text")):
            raise WorkflowProfileError(
                f"{path} slide {index} consulting_content.so_what missing text"
            )


def _validate_deck_plan(plan: Any, path: Path) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != "ghb.deck-plan.v1":
        raise WorkflowProfileError(f"{path} must use schema ghb.deck-plan.v1")
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise WorkflowProfileError(f"{path} slides must be a non-empty list")
    content_profile = _content_profile(plan, path)
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise WorkflowProfileError(f"{path} slide {index} must be an object")
        for field in ("page", "type", "message", "layout"):
            if slide.get(field) in (None, ""):
                raise WorkflowProfileError(f"{path} slide {index} missing {field}")
        if "consulting_content" in slide:
            if content_profile is None:
                raise WorkflowProfileError(
                    f"{path} slide {index} consulting_content requires style.content_profile"
                )
            _validate_consulting_content(slide["consulting_content"], slide, index, path)
    return plan


def _slide_id(slide: dict[str, Any], index: int) -> str:
    return str(slide.get("id") or f"body-{index:02d}")


def _rhythm(slide: dict[str, Any]) -> str:
    value = slide.get("rhythm")
    return value if value in {"anchor", "dense", "breathing"} else "anchor"


def _density(slide: dict[str, Any], plan: dict[str, Any]) -> str:
    value = slide.get("density")
    if value in {"breathing", "balanced", "dense"}:
        return str(value)
    style = plan.get("style") if isinstance(plan.get("style"), dict) else {}
    value = style.get("density")
    return str(value) if value in {"breathing", "balanced", "dense"} else "balanced"


def _purpose(value: Any) -> str:
    known = {
        "architecture", "process", "comparison", "timeline", "metrics", "summary",
        "hero", "section-anchor", "evidence", "case-study", "instruction", "decision",
        "risk", "screenshot", "data-story", "recommendation", "closing",
    }
    return str(value) if value in known else "summary"


def _projection_paths(project: Path) -> tuple[Path, ...]:
    return (
        project / "confirmation.json",
        project / "content_model.json",
        project / "layout_plan.json",
    )


def materialize_standard_contract(project: Path) -> list[Path]:
    """Project a confirmed brief/deck plan into legacy compatibility artifacts.

    If neither simplified file exists, this is a legacy Standard project and no
    action is taken.  If either exists, both are required.  Existing authored
    legacy contracts are protected unless they were generated by this adapter.
    """
    brief_path = project / "brief.json"
    plan_path = project / "deck_plan.json"
    if not brief_path.exists() and not plan_path.exists():
        return []
    if not brief_path.is_file() or not plan_path.is_file():
        raise WorkflowProfileError("Standard mode requires both brief.json and deck_plan.json")
    brief = _validate_brief(_read_json(brief_path), brief_path)
    plan = _validate_deck_plan(_read_json(plan_path), plan_path)
    content_profile = _content_profile(plan, plan_path)
    generated_projection = _generated(project / "confirmation.json")
    protected = [
        path
        for path in _projection_paths(project)
        if path.exists() and not generated_projection and not _generated(path)
    ]
    if protected:
        # A legacy project remains authoritative.  This avoids silently replacing
        # real authoring when compact files are added only for documentation.
        return []

    slides = plan["slides"]
    outline = [
        {"title": str(slide["message"]), "rhythm": _rhythm(slide)}
        for slide in slides
    ]
    decisions = {
        "audience": brief["audience"],
        "page_range": str(brief["page_count"]),
        "mode": brief["mode"],
        "outline": outline,
        "content_tradeoffs": {"expand": [], "omit": [], "combine": []},
        "visual_assets": brief.get("assets") or {"image_source": "none", "icon_set": "none"},
    }
    confirmation = {
        "schema": "ghb.confirmation.v1",
        "origin": GENERATED_ORIGIN,
        "status": "confirmed",
        "confirmation_source": brief["confirmation_source"],
        "confirmed_at": brief["confirmed_at"],
        "decision_digest": _digest(decisions),
        "decisions": decisions,
    }
    claims = []
    layout_rows = []
    for index, slide in enumerate(slides, start=1):
        slide_id = _slide_id(slide, index)
        claim_id = f"claim-{index:02d}"
        refs = slide.get("source_refs") if isinstance(slide.get("source_refs"), list) else []
        source_ref = str(refs[0]) if refs else "sources/source.md"
        items = slide.get("items") if isinstance(slide.get("items"), list) else []
        purpose = _purpose(slide.get("type"))
        density = _density(slide, plan)
        rhythm = _rhythm(slide)
        layout = str(slide.get("layout") or "editorial")
        claims.append(
            {
                "id": claim_id,
                "statement": str(slide["message"]),
                "must_include": True,
                "source_reference": source_ref,
            }
        )
        row = {
            "slide": int(slide.get("page") or index),
            "slide_id": slide_id,
            "purpose": purpose,
            "key_message": str(slide["message"]),
            "audience": brief["audience"],
            "content_density": density,
            "density": rhythm,
            "rhythm": rhythm,
            "layout_type": layout,
            "layout_archetype": layout,
            "visual_encoding": str(slide.get("visual_priority") or layout),
            "editable_elements": slide.get("editable_elements") or ["title", "body", "shapes"],
            "image_requirement": str(slide.get("image_requirement") or "none"),
            "source_reference": source_ref,
            "speaker_note": str(slide.get("speaker_note") or "Refer to the confirmed source."),
            "items": items,
            "reason": str(slide.get("reason") or "content-led page design"),
            "alternatives": slide.get("alternatives") or [],
            "claim_ids": [claim_id],
            "page_schema": {
                "schema": "ghb.page-schema.v1",
                "slide_id": slide_id,
                "page_purpose": purpose,
                "density": density,
                "rhythm_role": "anchor" if rhythm == "anchor" else "transition" if rhythm == "breathing" else "continuity",
                "emphasis": str(slide.get("emphasis") or "distributed"),
                "focal_target": slide.get("focal_target"),
                "layout_variant": layout if "/" in layout else f"{layout}/custom",
                "budgets": {
                    "max_text_chars": int(slide.get("max_text_chars") or 320),
                    "max_nodes": int(slide.get("max_nodes") or 10),
                },
            },
        }
        for passthrough in (
            "time_order", "order_signal", "sequence", "comparison_criteria", "axes", "loop_closure"
        ):
            if passthrough in slide:
                row[passthrough] = slide[passthrough]
        if content_profile is not None:
            row["content_profile"] = content_profile
        if "consulting_content" in slide:
            row["consulting_content"] = deepcopy(slide["consulting_content"])
        layout_rows.append(row)

    content_model = {
        "schema": "ghb.content-model.v1",
        "origin": GENERATED_ORIGIN,
        "claims": claims,
    }
    layout_envelope = layout_rows
    written: list[Path] = []
    for path, payload in (
        (project / "confirmation.json", confirmation),
        (project / "content_model.json", content_model),
        (project / "layout_plan.json", layout_envelope),
    ):
        _write_json(path, payload)
        written.append(path)

    design_spec = project / "design_spec.md"
    spec_lock = project / "spec_lock.md"
    design_is_projection = (
        not design_spec.exists()
        or design_spec.read_text(encoding="utf-8").startswith(
            ("<!-- origin: standard-projection -->", "# Standard Design Brief")
        )
    )
    if design_is_projection:
        content_profile_line = (
            f"- Content profile: {content_profile}\n" if content_profile is not None else ""
        )
        design_spec.write_text(
            "<!-- origin: standard-projection -->\n# Standard Design Brief\n\n"
            f"- Audience: {brief['audience']}\n"
            f"- Purpose: {brief['purpose']}\n"
            f"- Mode: {brief['mode']}\n"
            f"- Visual style: {brief['visual_style']}\n"
            f"{content_profile_line}"
            f"- Page count: {brief['page_count']}\n",
            encoding="utf-8",
        )
        written.append(design_spec)
    lock_is_projection = (
        not spec_lock.exists()
        or spec_lock.read_text(encoding="utf-8").startswith(
            ("# origin: standard-projection", "canvas: 1280x720")
        )
    )
    if lock_is_projection:
        spec_lock.write_text(
            "# origin: standard-projection\ncanvas: 1280x720\n"
            f"mode: {brief['mode']}\n"
            f"visual_style: {brief['visual_style']}\n"
            "colors: GHB template profile\n"
            "typography: Source Han Sans SC with Office-safe fallback\n"
            "safe_area: x=64..1216, y=170..680\n",
            encoding="utf-8",
        )
        written.append(spec_lock)
    return written


def confirmed_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
