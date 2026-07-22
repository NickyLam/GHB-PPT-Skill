#!/usr/bin/env python3
"""Unified, checkpointed entry point for the GHB PPT pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PM = ROOT / "scripts" / "ppt_master"
DEFAULT_TEMPLATE = ROOT / "templates" / "GHB_PPT_模板.pptx"
REQUIRED_DIRS = ("sources", "analysis", "images", "svg_output", "svg_final", "notes", "exports")

sys.path.insert(0, str(ROOT))
from scripts.remove_svg_background import (  # noqa: E402
    BackgroundRemovalError,
    remove_project_backgrounds,
)
from scripts.render_ghb_pptx import render_pptx  # noqa: E402
from scripts.review_visual_quality import (  # noqa: E402
    AdapterConfig,
    PageEvidence,
    RemoteAuthorization,
    ReviewContractError,
    review_visual_quality,
)
from scripts.evidence_manifest import (  # noqa: E402
    EvidenceItem,
    FreshnessResult,
    create_manifest,
    evaluate_freshness,
    write_manifest_atomic,
)
from scripts.font_policy import (  # noqa: E402
    LEGACY_CJK_FONT,
    PRIMARY_CJK_FONT,
    detect_cjk_fonts,
    preferred_cjk_font,
    resolve_font_file,
)


class PipelineError(RuntimeError):
    """Actionable failure from a pipeline stage."""


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass
class RunRecord:
    command: str
    started_at: str
    keep_intermediate: bool = False
    status: str = "running"
    stages: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    error: str | None = None


class RunContext:
    def __init__(
        self,
        project: Path,
        command: str,
        *,
        dry_run: bool = False,
        keep_intermediate: bool = False,
    ) -> None:
        self.project = project.resolve()
        self.dry_run = dry_run
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.run_dir = self.project / ".ghb" / "runs" / stamp
        self.record = RunRecord(
            command=command,
            started_at=datetime.now(timezone.utc).isoformat(),
            keep_intermediate=keep_intermediate,
        )
        if not dry_run:
            self.run_dir.mkdir(parents=True, exist_ok=False)
            self._write_record()

    def _write_record(self) -> None:
        (self.run_dir / "run.json").write_text(
            json.dumps(asdict(self.record), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def plan(self, stage: str, detail: str) -> None:
        print(f"[DRY-RUN] {stage}: {detail}")

    def run(self, stage: str, command: list[str]) -> CommandResult:
        if self.dry_run:
            self.plan(stage, " ".join(command))
            return CommandResult(command, 0, "", "", 0.0)
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        result = CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=round(time.monotonic() - started, 3),
        )
        self.record.stages.append({"stage": stage, **asdict(result)})
        self._write_record()
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
        if completed.returncode:
            raise PipelineError(f"stage {stage!r} failed with exit code {completed.returncode}")
        return result

    def output(self, path: Path) -> None:
        value = str(path.resolve())
        if value not in self.record.outputs:
            self.record.outputs.append(value)
        if not self.dry_run:
            self._write_record()

    def checkpoint(
        self,
        stage: str,
        outputs: list[Path],
        *,
        pptx_path: Path | None = None,
        final_report_path: Path | None = None,
        final_markdown_path: Path | None = None,
    ) -> None:
        if self.dry_run:
            return
        state_dir = self.project / ".ghb"
        state_dir.mkdir(parents=True, exist_ok=True)
        items = build_evidence_items(
            self.project,
            run_id=self.run_dir.name,
            stage=stage,
            include_final=stage in {"build", "report"},
            pptx_path=pptx_path or next(
                (path for path in outputs if path.suffix.lower() == ".pptx"),
                None,
            ),
            final_report_path=final_report_path,
            final_markdown_path=final_markdown_path,
        )
        manifest = create_manifest(
            project_id=self.project.name,
            run_id=self.run_dir.name,
            items=items,
        )
        payload = {
            "last_successful_stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "run": str(self.run_dir),
            "outputs": [str(path.resolve()) for path in outputs],
            "evidence_manifest": manifest,
        }
        (state_dir / "state.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if stage in {"build", "report"}:
            write_manifest_atomic(state_dir / "evidence-manifest.json", manifest)

    def finish(self) -> None:
        self.record.status = "succeeded"
        if not self.dry_run:
            self._write_record()

    def fail(self, exc: BaseException) -> None:
        self.record.status = "failed"
        self.record.error = str(exc)
        if not self.dry_run:
            self._write_record()


def ensure_project(project: Path, *, create: bool = False, dry_run: bool = False) -> None:
    if create:
        if project.exists() and not project.is_dir():
            raise PipelineError(f"project path is not a directory: {project}")
        if not dry_run:
            project.mkdir(parents=True, exist_ok=True)
            for name in REQUIRED_DIRS:
                (project / name).mkdir(exist_ok=True)
            confirmation = project / "confirmation.json"
            if not confirmation.exists():
                confirmation.write_text(
                    json.dumps(
                        {
                            "schema": "ghb.confirmation.v1",
                            "status": "pending",
                            "confirmation_source": None,
                            "confirmed_at": None,
                            "decision_digest": None,
                            "decisions": {
                                "audience": None,
                                "page_range": None,
                                "mode": None,
                                "outline": [],
                                "content_tradeoffs": {
                                    "expand": [],
                                    "omit": [],
                                    "combine": [],
                                },
                                "visual_assets": {
                                    "image_source": None,
                                    "icon_set": None,
                                },
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
            visual_profile = project / "visual_profile.json"
            if not visual_profile.exists():
                from scripts.validate_project_contract import default_visual_profile

                visual_profile.write_text(
                    json.dumps(default_visual_profile(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            art_direction = project / "art_direction.json"
            if not art_direction.exists():
                from scripts.validate_project_contract import default_art_direction

                art_direction.write_text(
                    json.dumps(default_art_direction(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        return
    if not project.is_dir():
        raise PipelineError(f"project directory not found: {project}")


def _load_json_evidence(path: Path) -> Any:
    if not path.is_file():
        return {"status": "missing"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "error": type(exc).__name__}


def _file_digest(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _svg_bundle(project: Path, directory: str) -> dict[str, Any]:
    files = []
    for path in sorted((project / directory).glob("*.svg")):
        files.append(
            {
                "path": str(path.relative_to(project)),
                "sha256": _file_digest(path),
            }
        )
    return {
        "schema": "ghb.svg-bundle-evidence.v2",
        "stage": "authored" if directory == "svg_output" else "finalized",
        "files": files,
    }


def _render_environment(render_payload: Any) -> dict[str, Any]:
    return {
        "schema": "ghb.render-environment.v1",
        "renderer": render_payload.get("renderer") if isinstance(render_payload, dict) else None,
        "renderer_available": bool(shutil.which("soffice") or shutil.which("libreoffice")),
        "rasterizer_available": bool(shutil.which("pdftoppm")),
        "dpi": render_payload.get("dpi") if isinstance(render_payload, dict) else None,
        "font": render_payload.get("font") if isinstance(render_payload, dict) else None,
    }


def _render_evidence(project: Path, payload: Any) -> dict[str, Any]:
    render_dir = project / "render"
    outputs = []
    if isinstance(payload, dict):
        for value in payload.get("outputs", []):
            if not isinstance(value, str):
                continue
            path = Path(value)
            if not path.is_absolute():
                path = render_dir / path
            outputs.append({"name": path.name, "sha256": _file_digest(path)})
    return {
        "schema": "ghb.render-evidence.v1",
        "report": payload,
        "outputs": outputs,
    }


def build_evidence_items(
    project: Path,
    *,
    run_id: str,
    stage: str = "build",
    include_final: bool = False,
    pptx_path: Path | None = None,
    final_report_path: Path | None = None,
    final_markdown_path: Path | None = None,
) -> list[EvidenceItem]:
    """Describe current pipeline evidence using U8's canonical dependency identities."""

    project = project.resolve()
    profile = project / "visual_profile.json"
    art_direction = project / "art_direction.json"
    layout = project / "layout_plan.json"
    rules = ROOT / "references" / "visual-quality-rules.md"
    items = [
        EvidenceItem("visual-profile", "json", _load_json_evidence(profile), profile if profile.is_file() else None),
        EvidenceItem(
            "art-direction",
            "json",
            _load_json_evidence(art_direction),
            art_direction if art_direction.is_file() else None,
        ),
        EvidenceItem("layout-plan", "json", _load_json_evidence(layout), layout if layout.is_file() else None),
        EvidenceItem(
            "rule-contract",
            "markdown",
            {"schema": "ghb.visual-rule-contract.v1", "sha256": _file_digest(rules)},
            rules if rules.is_file() else None,
        ),
    ]
    stage_order = {
        "check-svg": 1,
        "check-project": 0,
        "build-cover": 0,
        "build-content": 2,
        "merge": 3,
        "validate": 4,
        "render": 5,
        "build": 6,
    }
    level = stage_order.get(stage, 0)
    if level >= 1 or include_final:
        items.append(EvidenceItem(
            "authored-svg-bundle",
            "svg-bundle",
            _svg_bundle(project, "svg_output"),
        ))
    if level >= 2 or include_final:
        items.append(EvidenceItem(
            "finalized-svg-bundle",
            "svg-bundle",
            _svg_bundle(project, "svg_final"),
        ))
    pptx = (pptx_path or project / "exports" / "final.pptx").resolve()
    if level >= 3 or include_final:
        items.append(
            EvidenceItem(
                "pptx",
                "pptx",
                {"schema": "ghb.pptx-evidence.v1", "sha256": _file_digest(pptx)},
                pptx if pptx.is_file() else None,
            )
        )
    deterministic_report_path = project / "reports" / "quality-pre-render.json"
    final_report_path = (
        final_report_path or project / "reports" / "quality-report.json"
    ).resolve()
    final_markdown_path = (
        final_markdown_path or project / "reports" / "quality-report.md"
    ).resolve()
    if level >= 4 or include_final:
        items.append(
            EvidenceItem(
                "deterministic-report",
                "json",
                _load_json_evidence(deterministic_report_path),
                deterministic_report_path if deterministic_report_path.is_file() else None,
            )
        )
    render_path = project / "render" / "render-report.json"
    render_payload = (
        _load_json_evidence(render_path) if level >= 5 or include_final else None
    )
    if level >= 5 or include_final:
        items.extend(
            [
                EvidenceItem(
                    "render-environment",
                    "environment",
                    _render_environment(render_payload),
                ),
                EvidenceItem(
                    "render-evidence",
                    "json",
                    _render_evidence(project, render_payload),
                    render_path if render_path.is_file() else None,
                ),
            ]
        )
    if include_final:
        render_status = render_payload.get("status") if isinstance(render_payload, dict) else None
        policy_path = project / ".ghb" / "adapter-policy.json"
        review_path = project / "reports" / "visual-review.json"
        policy_payload = _load_json_evidence(policy_path)
        review_payload = _load_json_evidence(review_path)
        review_outcome = (
            str(review_payload.get("outcome"))
            if isinstance(review_payload, dict) and review_payload.get("outcome")
            else ("skipped" if render_status == "passed" else "unavailable")
        )
        items.extend(
            [
                EvidenceItem(
                    "adapter-policy",
                    "optional-review-policy",
                    policy_payload,
                    policy_path if policy_path.is_file() else None,
                ),
                EvidenceItem(
                    "adapter-review",
                    "optional-review",
                    review_payload,
                    review_path if review_path.is_file() else None,
                ),
                EvidenceItem(
                    "final-report",
                    "json",
                    {
                        "report": _load_json_evidence(final_report_path),
                        "markdown_sha256": _file_digest(final_markdown_path),
                        "review_outcome": review_outcome,
                    },
                    final_report_path if final_report_path.is_file() else None,
                ),
            ]
        )
    return items


def evidence_freshness(
    project: Path,
    manifest: dict[str, Any],
    *,
    run_id: str,
    include_final: bool = True,
    pptx_path: Path | None = None,
    final_report_path: Path | None = None,
    final_markdown_path: Path | None = None,
) -> FreshnessResult:
    return evaluate_freshness(
        manifest,
        project_id=project.resolve().name,
        run_id=run_id,
        current_items=build_evidence_items(
            project,
            run_id=run_id,
            stage="build" if include_final else "validate",
            include_final=include_final,
            pptx_path=pptx_path,
            final_report_path=final_report_path,
            final_markdown_path=final_markdown_path,
        ),
    )


def _report_input_freshness(result: FreshnessResult) -> FreshnessResult:
    """Exclude the report being regenerated while preserving every upstream gate."""

    return FreshnessResult(
        states={
            identity: state
            for identity, state in result.states.items()
            if identity != "final-report"
        },
        issues=tuple(
            issue for issue in result.issues if issue.get("identity") != "final-report"
        ),
    )


def _review_input_freshness(result: FreshnessResult) -> FreshnessResult:
    required = {
        "visual-profile", "art-direction", "layout-plan", "rule-contract",
        "authored-svg-bundle", "finalized-svg-bundle", "pptx",
        "render-environment", "render-evidence", "deterministic-report",
    }
    return FreshnessResult(
        states={identity: state for identity, state in result.states.items() if identity in required},
        issues=tuple(issue for issue in result.issues if issue.get("identity") in required),
    )


def _with_fresh_review(result: FreshnessResult | None = None) -> FreshnessResult:
    return FreshnessResult(
        states={
            **(result.states if result is not None else {}),
            "adapter-policy": "fresh",
            "adapter-review": "fresh",
        },
        issues=result.issues if result is not None else (),
    )


def _manifest_review_freshness(project: Path, pptx_path: Path) -> FreshnessResult:
    """Validate persisted review evidence against the manifest that produced it."""

    manifest_path = project / ".ghb" / "evidence-manifest.json"
    if not manifest_path.is_file():
        issue = {
            "identity": "adapter-review",
            "code": "missing-evidence-manifest",
        }
        return FreshnessResult(
            states={"adapter-policy": "stale", "adapter-review": "stale"},
            issues=(issue,),
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = str(manifest.get("run_id", ""))
        return _report_input_freshness(
            evidence_freshness(
                project,
                manifest,
                run_id=run_id,
                include_final=True,
                pptx_path=pptx_path,
            )
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        issue = {
            "identity": "adapter-review",
            "code": "invalid-evidence-manifest",
        }
        return FreshnessResult(
            states={"adapter-policy": "stale", "adapter-review": "stale"},
            issues=(issue,),
        )


def _checkpoint_pptx(project: Path) -> Path | None:
    state_path = project / ".ghb" / "state.json"
    payload = _load_json_evidence(state_path)
    if not isinstance(payload, dict):
        return None
    if payload.get("last_successful_stage") not in {"build", "report"}:
        return None
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        return None
    for value in outputs:
        if isinstance(value, str) and Path(value).suffix.lower() == ".pptx":
            return Path(value).resolve()
    return None


def timestamped_candidates(requested: Path) -> set[Path]:
    pattern = f"{requested.stem}_????????_??????{requested.suffix}"
    return {path.resolve() for path in requested.parent.glob(pattern)}


def locate_new_timestamped_output(requested: Path, before: set[Path]) -> Path:
    created = sorted(timestamped_candidates(requested) - before)
    if len(created) != 1:
        raise PipelineError(
            f"expected exactly one new timestamped output for {requested.name}, found {len(created)}"
        )
    return created[0]


def replace_output(source: Path, destination: Path, run: RunContext) -> None:
    if run.dry_run:
        run.plan("output", f"replace {destination} with {source}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        previous_dir = run.run_dir / "previous-outputs"
        previous_dir.mkdir(exist_ok=True)
        shutil.copy2(destination, previous_dir / destination.name)
    os.replace(source, destination)


def _write_cover_plan(
    path: Path,
    title: str,
    subtitle: str,
    date: str,
    *,
    cover_slots: dict[str, str] | None = None,
) -> None:
    slots = cover_slots or {
        "title": "s01_sh8",
        "subtitle": "s01_sh6",
        "date": "s01_sh4",
    }
    payload = {
        "schema": "template_fill_pptx_plan.v1",
        "slides": [
            {
                "source_slide": 1,
                "purpose": "封面",
                "replacements": [
                    {"slot_id": slots["title"], "text": title},
                    {"slot_id": slots["subtitle"], "text": subtitle},
                    {"slot_id": slots["date"], "text": date},
                ],
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_cover(
    run: RunContext,
    *,
    template: Path,
    output: Path,
    plan: Path | None,
    title: str | None,
    subtitle: str | None,
    date: str | None,
) -> Path:
    if not template.is_file():
        raise PipelineError(f"template not found: {template}")
    analysis = run.project / "analysis" / "slide_library.json"
    template_profile_path = run.project / "analysis" / "template_profile.json"
    resolved_plan = plan or run.project / "analysis" / "cover_fill_plan.json"
    run.run("analyze-template", [sys.executable, str(PM / "template_fill_pptx.py"), "analyze", str(template), "-o", str(analysis)])
    if not run.dry_run:
        from scripts.template_profile import write_template_profile

        write_template_profile(analysis, template, template_profile_path)
    if plan is None:
        if not all((title, subtitle, date)):
            raise PipelineError("build-cover needs --plan or all of --title/--subtitle/--date")
        if run.dry_run:
            run.plan("cover-plan", f"write {resolved_plan}")
        else:
            profile = _load_json_evidence(template_profile_path)
            profile_slots = profile.get("cover_slots") if isinstance(profile, dict) else None
            if not (
                isinstance(profile_slots, dict)
                and all(isinstance(profile_slots.get(key), str) for key in ("title", "subtitle", "date"))
            ):
                profile_slots = None
            _write_cover_plan(
                resolved_plan,
                title or "",
                subtitle or "",
                date or "",
                cover_slots=profile_slots,
            )
    elif not plan.is_file():
        raise PipelineError(f"cover plan not found: {plan}")

    run.run("check-cover-plan", [sys.executable, str(PM / "template_fill_pptx.py"), "check-plan", str(analysis), str(resolved_plan)])
    before = timestamped_candidates(output) if not run.dry_run else set()
    run.run(
        "apply-cover",
        [sys.executable, str(PM / "template_fill_pptx.py"), "apply", str(template), str(resolved_plan), "-o", str(output), "--transition", "none"],
    )
    if not run.dry_run:
        produced = locate_new_timestamped_output(output, before)
        replace_output(produced, output, run)
    run.run("fix-cover-font", [sys.executable, str(ROOT / "scripts" / "fix_cover_font.py"), str(output)])
    run.output(output)
    run.checkpoint("build-cover", [output])
    return output


def run_svg_gate(run: RunContext, *, stage: str) -> Path:
    report = run.project / "reports" / f"svg-{stage}.json"
    run.run(
        f"svg-{stage}",
        [
            sys.executable,
            str(ROOT / "scripts" / "ghb_svg_quality.py"),
            str(run.project),
            "--stage", stage,
            "--output", str(report),
        ],
    )
    run.output(report)
    return report


def check_project_contract(run: RunContext, *, require_visual_contract: bool = False) -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_project_contract.py"),
        str(run.project),
    ]
    if require_visual_contract:
        command.append("--require-visual-contract")
    run.run(
        "project-contract",
        command,
    )


def check_svg(run: RunContext) -> None:
    check_project_contract(run, require_visual_contract=True)
    run_svg_gate(run, stage="authored")


def check_plan(run: RunContext) -> None:
    run.run(
        "plan-contract",
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_project_contract.py"),
            str(run.project),
            "--plan-only",
        ],
    )


def build_content(run: RunContext, *, output: Path) -> Path:
    check_svg(run)
    backup_dir = run.run_dir / "finalized-svg-with-preview-background"
    total_notes = run.project / "notes" / "total.md"
    if total_notes.exists() or run.dry_run:
        run.run("split-notes", [sys.executable, str(PM / "total_md_split.py"), str(run.project)])
    run.run("finalize-svg", [sys.executable, str(PM / "finalize_svg.py"), str(run.project)])
    if run.dry_run:
        run.plan(
            "remove-background",
            f"validate/remove GHB preview backgrounds from svg_final; backup -> {backup_dir}",
        )
    else:
        try:
            results = remove_project_backgrounds(
                run.project,
                svg_dir_name="svg_final",
                backup_dir=backup_dir,
            )
        except (OSError, BackgroundRemovalError) as exc:
            raise PipelineError(str(exc)) from exc
        run.record.stages.append(
            {"stage": "remove-background", "results": [asdict(result) for result in results]}
        )
        run._write_record()

    run_svg_gate(run, stage="finalized")
    run.run(
        "svg-to-pptx",
        [
            sys.executable,
            str(PM / "svg_to_pptx.py"),
            str(run.project),
            "-s",
            "final",
            "-o",
            str(output),
            "--animation",
            "none",
            "--transition",
            "none",
        ],
    )
    run.output(output)
    run.checkpoint("build-content", [output])
    return output


def merge_deck(
    run: RunContext,
    *,
    content: Path,
    template: Path,
    cover: Path,
    output: Path,
    content_layout: int,
    no_ending: bool,
    ending_slide: int | None,
) -> Path:
    for label, path in (("content", content), ("template", template), ("cover", cover)):
        if not path.is_file() and not run.dry_run:
            raise PipelineError(f"{label} PPTX not found: {path}")
    command = [
        sys.executable,
        str(ROOT / "scripts" / "merge_template_master.py"),
        "--content", str(content),
        "--template", str(template),
        "--cover", str(cover),
        "--content-layout", str(content_layout),
        "--output", str(output),
    ]
    if no_ending:
        command.append("--no-ending")
    elif ending_slide is not None:
        command.extend(["--ending-slide", str(ending_slide)])
    run.run("merge", command)
    run.output(output)
    run.checkpoint("merge", [output])
    return output


def _profiled_merge_values(
    project: Path,
    *,
    content_layout: int | None,
    ending_slide: int | None,
) -> tuple[int, int | None]:
    """Resolve merge defaults from template_profile while honoring explicit CLI values."""

    profile = _load_json_evidence(project / "analysis" / "template_profile.json")
    if not isinstance(profile, dict) or profile.get("schema") != "ghb.template-profile.v1":
        return content_layout or 2, ending_slide
    resolved_layout = content_layout
    if resolved_layout is None:
        candidate = profile.get("content_layout_index")
        resolved_layout = candidate if isinstance(candidate, int) and candidate > 0 else 2
    resolved_ending = ending_slide
    if resolved_ending is None:
        candidate = profile.get("ending_slide_index")
        resolved_ending = candidate if isinstance(candidate, int) and candidate > 0 else None
    return resolved_layout, resolved_ending


def _resolve_embed_font_paths(explicit: list[Path]) -> list[Path]:
    """Resolve fonts to embed: explicit paths win, else the installed CJK font."""
    if explicit:
        return [path.resolve() for path in explicit]
    fc_list = shutil.which("fc-list")
    if not fc_list:
        raise PipelineError(
            "--embed-fonts needs a font file; fc-list is unavailable, pass --embed-font PATH"
        )
    completed = subprocess.run([fc_list], capture_output=True, text=True, errors="replace")
    cjk = detect_cjk_fonts(completed.stdout.lower())
    target = preferred_cjk_font(cjk)
    font_file = resolve_font_file(target, completed.stdout) if target else None
    if not font_file:
        raise PipelineError(
            "--embed-fonts could not resolve an installed CJK font file; pass --embed-font PATH"
        )
    return [Path(font_file)]


def embed_deck(run: RunContext, *, pptx: Path, font_paths: list[Path]) -> Path:
    """Embed subsetted fonts into ``pptx`` in place and record a report."""
    from scripts.embed_fonts import FontEmbedError, embed_fonts

    report_path = run.project / "reports" / "font-embed-report.json"
    if run.dry_run:
        resolved = ", ".join(str(path) for path in font_paths) or "auto-resolved CJK font"
        print(f"[DRY-RUN] embed fonts into {pptx} ({resolved})")
        return pptx
    fonts = _resolve_embed_font_paths(font_paths)
    try:
        report = embed_fonts(pptx, font_paths=fonts, output_path=pptx, subset=True)
    except FontEmbedError as exc:
        raise PipelineError(f"font embedding failed: {exc}") from exc
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    run.output(report_path)
    run.checkpoint("embed-fonts", [pptx, report_path])
    return pptx


def validate_deck(
    run: RunContext,
    *,
    pptx: Path,
    body_count: int | None,
    expect_ending: bool,
    json_output: Path,
    markdown_output: Path,
    render_dir: Path | None = None,
    freshness: FreshnessResult | None = None,
    review_report_path: Path | None = None,
    review_required: bool = False,
    quality_policy: str = "draft",
    warning_waivers: Path | None = None,
    target_renderer: str = "auto",
) -> tuple[Path, Path]:
    if not pptx.is_file() and not run.dry_run:
        raise PipelineError(f"final PPTX not found: {pptx}")
    if body_count is None:
        body_count = len(list((run.project / "svg_output").glob("*.svg")))
    readback_output = markdown_output.parent / "ppt-readback.md"
    run.run(
        "ppt-readback",
        [
            sys.executable,
            str(PM / "source_to_md" / "ppt_to_md.py"),
            str(pptx),
            "--output", str(readback_output),
        ],
    )
    run.output(readback_output)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_ghb_pptx.py"),
        str(pptx),
        "--body-count", str(body_count),
        "--source-svg-dir", str(run.project / "svg_output"),
        "--json-output", str(json_output),
        "--markdown-output", str(markdown_output),
        "--readback-markdown", str(readback_output),
    ]
    layout_plan = run.project / "layout_plan.json"
    if layout_plan.exists() or run.dry_run:
        command.extend(["--layout-plan", str(layout_plan)])
    visual_profile = run.project / "visual_profile.json"
    if visual_profile.exists() or run.dry_run:
        command.extend(["--visual-profile", str(visual_profile)])
    font_embed_report = run.project / "reports" / "font-embed-report.json"
    if font_embed_report.exists() or run.dry_run:
        command.extend(["--font-embed-report", str(font_embed_report)])
    command.append("--expect-ending" if expect_ending else "--no-ending")
    if render_dir is not None:
        command.extend(["--render-dir", str(render_dir)])
    if review_report_path is not None:
        command.extend(["--review-report", str(review_report_path)])
    if review_required:
        command.append("--review-required")
    command.extend(["--quality-policy", quality_policy])
    command.extend(["--target-renderer", target_renderer])
    if warning_waivers is not None:
        command.extend(["--warning-waivers", str(warning_waivers)])
    if freshness is not None:
        freshness_path = run.run_dir / "freshness.json"
        freshness_payload = {
            "status": "fresh" if freshness.fresh else "stale",
            "states": freshness.states,
            "issues": list(freshness.issues),
        }
        if run.dry_run:
            run.plan("freshness", f"write {freshness_path}")
        else:
            freshness_path.write_text(
                json.dumps(freshness_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        command.extend(["--freshness-json", str(freshness_path)])
    for svg_report in (
        run.project / "reports" / "svg-authored.json",
        run.project / "reports" / "svg-finalized.json",
    ):
        if svg_report.is_file() or run.dry_run:
            command.extend(["--svg-report", str(svg_report)])
    notes_dir = run.project / "notes"
    if any(path.name != "total.md" for path in notes_dir.glob("*.md")):
        command.append("--expect-body-notes")
    run.run("validate", command)
    run.output(json_output)
    run.output(markdown_output)
    run.checkpoint("validate", [pptx, readback_output, json_output, markdown_output])
    return json_output, markdown_output


def render_deck(
    run: RunContext,
    *,
    pptx: Path,
    output_dir: Path,
    dpi: int = 144,
) -> Path:
    if not pptx.is_file() and not run.dry_run:
        raise PipelineError(f"PPTX not found: {pptx}")
    run.run(
        "render",
        [
            sys.executable,
            str(ROOT / "scripts" / "render_ghb_pptx.py"),
            str(pptx),
            "--output-dir", str(output_dir),
            "--dpi", str(dpi),
        ],
    )
    run.output(output_dir / "render-report.json")
    run.output(output_dir / "contact-sheet.png")
    run.checkpoint(
        "render",
        [pptx, output_dir / "render-report.json", output_dir / "contact-sheet.png"],
    )
    return output_dir


def record_unavailable_render(
    run: RunContext,
    *,
    pptx: Path,
    output_dir: Path,
    dpi: int,
) -> None:
    """Replace any older success evidence when this run has no renderer."""

    if run.dry_run:
        run.plan("render", "record unavailable render evidence")
        return
    report = render_pptx(pptx, output_dir, dpi=dpi)
    if report.status != "unavailable":
        raise PipelineError(
            f"expected unavailable render evidence, got {report.status}"
        )
    run.record.stages.append(
        {
            "stage": "render",
            "status": "unavailable",
            "warning": report.errors[0] if report.errors else "renderer unavailable",
        }
    )
    run.output(output_dir / "render-report.json")
    run._write_record()


def record_review_state(run: RunContext, *, render_available: bool) -> str:
    """Record the deterministic U5 contract while the optional U10 action is absent."""

    outcome = "skipped" if render_available else "unavailable"
    if not run.dry_run:
        run.record.stages.append(
            {
                "stage": "optional-review",
                "status": outcome,
                "outcome": outcome,
                "implementation": "absent",
            }
        )
        run._write_record()
    return outcome


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _operator_local_file(path: Path, project: Path, *, label: str) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    lexical = Path(os.path.abspath(candidate))
    try:
        metadata = lexical.lstat()
    except OSError as exc:
        raise PipelineError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PipelineError(f"{label} must be a regular non-symlink file")
    project_root = project.resolve()
    for checked in (lexical, lexical.resolve(strict=True)):
        try:
            checked.relative_to(project_root)
        except ValueError:
            continue
        raise PipelineError(f"{label} must be operator-local and outside the project")
    return lexical.resolve(strict=True)


def load_review_config(path: Path, project: Path) -> tuple[AdapterConfig, dict[str, Any]]:
    """Load one explicit operator-local registration without accepting secret values."""

    resolved = _operator_local_file(path, project, label="review config")
    payload = _load_json_evidence(resolved)
    allowed = {
        "schema", "executable", "capability", "model_id", "tool_contract",
        "trusted_direct", "launcher", "launcher_supplies_os_sandbox",
        "credential_env_names", "deadline_seconds",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise PipelineError("invalid review operator config fields")
    if payload.get("schema") != "ghb.visual-review-operator-config.v1":
        raise PipelineError("unsupported review operator config schema")
    credentials = payload.get("credential_env_names", [])
    launcher = payload.get("launcher", [])
    if not isinstance(credentials, list) or any(not isinstance(item, str) for item in credentials):
        raise PipelineError("credential_env_names must contain variable names only")
    if not isinstance(launcher, list) or any(not isinstance(item, str) for item in launcher):
        raise PipelineError("launcher must be a string list")
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", item) for item in credentials):
        raise PipelineError("credential_env_names must contain trusted variable names only")
    if any(
        re.search(r"(?:token|secret|password|credential|api[-_]?key)", item, re.I)
        for item in launcher[1:]
    ):
        raise PipelineError("launcher arguments contain prohibited sensitive material")
    trusted_direct = payload.get("trusted_direct", True)
    launcher_supplies_os_sandbox = payload.get("launcher_supplies_os_sandbox", False)
    if not isinstance(trusted_direct, bool) or not isinstance(
        launcher_supplies_os_sandbox, bool
    ):
        raise PipelineError("review trust and sandbox flags must be JSON booleans")
    deadline_seconds = payload.get("deadline_seconds", 30.0)
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(float(deadline_seconds))
        or not 0.05 <= float(deadline_seconds) <= 300
    ):
        raise PipelineError("review deadline_seconds must be a finite number from 0.05 to 300")
    required = ("executable", "capability", "model_id", "tool_contract")
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
        raise PipelineError("review operator config is missing required registration fields")
    config = AdapterConfig(
        executable=Path(payload["executable"]),
        capability=payload["capability"],
        model_id=payload["model_id"],
        tool_contract=payload["tool_contract"],
        trusted_direct=trusted_direct,
        launcher=tuple(launcher),
        launcher_supplies_os_sandbox=launcher_supplies_os_sandbox,
        credential_env_names=tuple(credentials),
        deadline_seconds=float(deadline_seconds),
    )
    executable = Path(payload["executable"]).expanduser().resolve()
    policy = {
        "schema": "ghb.visual-review-adapter-policy.v1",
        "status": "configured",
        "capability": config.capability,
        "model_id": config.model_id,
        "tool_contract": config.tool_contract,
        "trusted_direct": config.trusted_direct,
        "executable_sha256": _file_digest(executable),
        "launcher": Path(launcher[0]).name if launcher else None,
        "launcher_args_sha256": (
            hashlib.sha256(
                json.dumps(launcher[1:], ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            if launcher
            else None
        ),
        "credentials": [
            {"name": name, "present": name in os.environ}
            for name in config.credential_env_names
        ],
    }
    return config, policy


def _load_review_authorization(path: Path | None, project: Path) -> RemoteAuthorization | None:
    if path is None:
        return None
    resolved = _operator_local_file(path, project, label="review authorization")
    payload = _load_json_evidence(resolved)
    allowed = {"schema", "provider", "destination", "retention", "slide_ids"}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise PipelineError("invalid remote review authorization")
    if payload.get("schema") != "ghb.visual-review-disclosure.v1":
        raise PipelineError("unsupported remote review authorization schema")
    slide_ids = payload.get("slide_ids")
    if not isinstance(slide_ids, list) or any(not isinstance(item, str) for item in slide_ids):
        raise PipelineError("remote review authorization requires exact slide membership")
    for field_name in ("provider", "destination", "retention"):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value or len(value) > 512:
            raise PipelineError(
                "remote review authorization fields must be bounded non-empty strings"
            )
    return RemoteAuthorization(
        payload["provider"], payload["destination"], payload["retention"], tuple(slide_ids),
    )


def _inactive_review_report(outcome: str, *, deterministic_status: str) -> dict[str, Any]:
    return {
        "schema": "ghb.visual-review-report.v1",
        "outcome": outcome,
        "deterministic_status": deterministic_status,
        "completion_status": "skipped" if outcome == "skipped" else "failed",
        "freshness": "unavailable" if outcome == "unavailable" else "fresh",
        "findings": [],
        "dimension_reviewability": [],
        "limitations": [] if outcome == "skipped" else ["fresh-render-evidence-unavailable"],
        "provenance": {"adapter": "absent"},
    }


def write_inactive_review_state(
    project: Path, *, outcome: str, deterministic_status: str, required: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = _inactive_review_report(outcome, deterministic_status=deterministic_status)
    policy = {
        "schema": "ghb.visual-review-adapter-policy.v1",
        "status": "absent",
        "required": required,
    }
    _write_json_atomic(project / "reports" / "visual-review.json", report)
    _write_json_atomic(project / ".ghb" / "adapter-policy.json", policy)
    return report, policy


def _review_failure(code: str, *, deterministic_status: str) -> dict[str, Any]:
    return {
        "schema": "ghb.visual-review-report.v1",
        "outcome": "error",
        "deterministic_status": deterministic_status,
        "completion_status": "failed",
        "freshness": "fresh",
        "findings": [],
        "dimension_reviewability": [],
        "limitations": [code],
        "provenance": {},
        "error": {"code": code, "message": "optional review did not complete"},
    }


def _record_optional_review_result(run: RunContext, report: dict[str, Any]) -> None:
    run.record.stages.append({"stage": "optional-review", "status": report["outcome"]})
    run.output(run.project / "reports" / "visual-review.json")


def _record_unavailable_review(
    run: RunContext, *, deterministic_status: str, required: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    report, policy = write_inactive_review_state(
        run.project,
        outcome="unavailable",
        deterministic_status=deterministic_status,
        required=required,
    )
    _record_optional_review_result(run, report)
    return report, policy


def run_optional_review(
    run: RunContext,
    *,
    pptx: Path,
    render_dir: Path,
    deterministic_report: Path,
    config_path: Path | None,
    authorization_path: Path | None,
    required: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run U4 only after verifying the current render envelope and deterministic report."""

    if run.dry_run:
        run.plan("optional-review", "verify fresh render, invoke configured adapter, persist advisory projection")
        return (
            _inactive_review_report("skipped", deterministic_status="passed"),
            {"schema": "ghb.visual-review-adapter-policy.v1", "status": "dry-run"},
        )
    output = run.project / "reports" / "visual-review.json"
    policy_path = run.project / ".ghb" / "adapter-policy.json"
    render_payload = _load_json_evidence(render_dir / "render-report.json")
    deterministic_payload = _load_json_evidence(deterministic_report)
    deterministic_status = str(
        deterministic_payload.get("quality", {})
        .get("deterministic_outcome", {})
        .get("status", "failed")
    ) if isinstance(deterministic_payload, dict) else "failed"
    expected_pptx_digest = _file_digest(pptx)
    if (
        not isinstance(render_payload, dict)
        or render_payload.get("schema") != "ghb.render-report.v1"
        or render_payload.get("status") != "passed"
        or render_payload.get("pptx_sha256") != expected_pptx_digest
        or not deterministic_report.is_file()
    ):
        return _record_unavailable_review(
            run, deterministic_status=deterministic_status, required=required
        )
    page_paths = []
    for value in render_payload.get("outputs", []):
        if not isinstance(value, str):
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = render_dir / candidate
        if candidate.name.startswith("slide-") and candidate.suffix.lower() == ".png":
            page_paths.append(candidate.resolve())
    if not page_paths or len(page_paths) != int(render_payload.get("page_count", 0)):
        return _record_unavailable_review(
            run, deterministic_status=deterministic_status, required=required
        )
    pages = []
    layout_rows = _load_json_evidence(run.project / "layout_plan.json")
    if not isinstance(layout_rows, list):
        layout_rows = []
    svg_summaries: dict[str, list[dict[str, Any]]] = {}
    for report_name in ("svg-authored.json", "svg-finalized.json"):
        svg_payload = _load_json_evidence(run.project / "reports" / report_name)
        if not isinstance(svg_payload, dict):
            continue
        for item in svg_payload.get("files", []):
            if not isinstance(item, dict):
                continue
            slide_id = item.get("slide_id")
            if isinstance(slide_id, str):
                svg_summaries.setdefault(slide_id, []).append({
                    "stage": svg_payload.get("stage"),
                    "error_count": len(item.get("errors", [])),
                    "warning_count": len(item.get("warnings", [])),
                    "visual_findings": item.get("visual_findings", []),
                })
    quality_payload = (
        deterministic_payload.get("quality", {})
        if isinstance(deterministic_payload, dict)
        else {}
    )
    structure_findings = [
        item
        for item in [
            *quality_payload.get("blocking_findings", []),
            *quality_payload.get("advisory_findings", []),
        ]
        if isinstance(item, dict)
    ]
    for index, page in enumerate(page_paths, 1):
        try:
            from PIL import Image

            with Image.open(page) as image:
                width, height = image.size
        except (OSError, ValueError):
            return _record_unavailable_review(
                run, deterministic_status=deterministic_status, required=required
            )
        layout_row = (
            layout_rows[index - 2]
            if 1 < index <= len(layout_rows) + 1
            and isinstance(layout_rows[index - 2], dict)
            else None
        )
        logical_slide_id = (
            layout_row.get("slide_id") if isinstance(layout_row, dict) else None
        )
        physical_slide_id = f"slide-{index:02d}"
        page_findings = [
            item
            for item in structure_findings
            if item.get("slide_id") in {physical_slide_id, logical_slide_id}
            or item.get("slide") == index
        ]
        context = {
            # Project only visual authoring fields. Source paths, speaker notes,
            # and claim provenance are not needed to review the rendered page
            # and must not become an accidental remote-adapter disclosure.
            "layout_plan": _review_layout_context(layout_row),
            "svg_metadata": svg_summaries.get(str(logical_slide_id), []),
            "structure_findings": _review_structure_context(page_findings),
        }
        pages.append(
            PageEvidence(
                slide_id=physical_slide_id,
                role=(
                    "cover"
                    if index == 1
                    else str(
                        (layout_row or {}).get("page_schema", {}).get(
                            "page_purpose", "body"
                        )
                    )
                ),
                image_path=page,
                width=width,
                height=height,
                run_id=run.run_dir.name,
                sha256=_file_digest(page) or "",
                context=context,
            )
        )
    try:
        if config_path is None:
            config = None
            policy = {"schema": "ghb.visual-review-adapter-policy.v1", "status": "absent"}
        else:
            config, policy = load_review_config(config_path, run.project)
        authorization = _load_review_authorization(authorization_path, run.project)
    except (PipelineError, ReviewContractError):
        policy = {
            "schema": "ghb.visual-review-adapter-policy.v1",
            "status": "invalid",
            "required": required,
        }
        report = _review_failure(
            "adapter-security-or-contract", deterministic_status=deterministic_status
        )
        _write_json_atomic(output, report)
        _write_json_atomic(policy_path, policy)
        _record_optional_review_result(run, report)
        return report, policy
    policy["required"] = required
    deterministic_findings = []
    quality = deterministic_payload.get("quality", {}) if isinstance(deterministic_payload, dict) else {}
    for finding in [*quality.get("blocking_findings", []), *quality.get("advisory_findings", [])]:
        if not isinstance(finding, dict) or not finding.get("code"):
            continue
        slide = finding.get("slide_id") or finding.get("slide") or "slide-01"
        if isinstance(slide, int):
            slide = f"slide-{slide:02d}"
        deterministic_findings.append({
            "code": str(finding["code"]),
            "severity": "error" if finding.get("severity") == "error" else "warning",
            "slide_id": str(slide),
            "evidence": finding.get("evidence", {}),
            "expected": finding.get("expected", {}),
            "suggested_action": str(finding.get("suggested_action") or finding.get("message") or "Review deterministic evidence."),
        })
    try:
        report = review_visual_quality(
            config=config,
            pages=pages,
            project_root=run.project,
            run_id=run.run_dir.name,
            deterministic_status=deterministic_status,
            deterministic_findings=deterministic_findings,
            target_font_available=render_payload.get("font", {}).get("status") == "available",
            approved_slide_ids={page.slide_id for page in pages},
            protected_paths=[pptx, deterministic_report, render_dir / "render-report.json"],
            remote_authorization=authorization,
            output_path=output,
        )
    except ReviewContractError:
        report = _review_failure("adapter-security-or-contract", deterministic_status=deterministic_status)
        _write_json_atomic(output, report)
    _write_json_atomic(policy_path, policy)
    _record_optional_review_result(run, report)
    return report, policy


def _review_layout_context(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    allowed = {
        "slide",
        "slide_id",
        "purpose",
        "key_message",
        "density",
        "rhythm",
        "layout_type",
        "layout_archetype",
        "visual_encoding",
        "page_schema",
    }
    return {key: row[key] for key in allowed if key in row}


def _review_structure_context(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        "code",
        "severity",
        "slide",
        "slide_id",
        "evidence",
        "expected",
        "suggested_action",
    }
    return [
        {key: finding[key] for key in allowed if key in finding}
        for finding in findings
        if isinstance(finding, dict)
    ]


def validation_error_codes(report_path: Path) -> set[str]:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read failed validation report {report_path}: {exc}") from exc
    return {
        str(issue.get("code"))
        for issue in payload.get("issues", [])
        if issue.get("severity") == "error" and issue.get("code")
    }


COMPLETED_REVIEW_OUTCOMES = frozenset({"passed"})


def require_completed_review(report: dict[str, Any], *, required: bool) -> None:
    if required and report.get("outcome") not in COMPLETED_REVIEW_OUTCOMES:
        raise PipelineError("required optional review did not complete")


def skill_drift_payload(
    repository_skill: Path,
    *,
    candidates: list[Path] | None = None,
) -> dict[str, Any]:
    """Compare installed Skill entrypoints without mutating either location."""
    repository_digest = _file_digest(repository_skill) if repository_skill.is_file() else None
    if candidates is None:
        home = Path.home()
        candidates = [
            home / ".agents" / "skills" / "ghb-ppt-skill" / "SKILL.md",
            home / ".codex" / "skills" / "ghb-ppt-skill" / "SKILL.md",
        ]
    installed: list[dict[str, Any]] = []
    for candidate in candidates:
        exists = candidate.is_file()
        digest = _file_digest(candidate) if exists else None
        installed.append({
            "path": str(candidate),
            "exists": exists,
            "sha256": digest,
            "matches_repository": bool(
                repository_digest and digest and digest == repository_digest
            ),
        })
    return {
        "repository": {
            "path": str(repository_skill),
            "exists": repository_skill.is_file(),
            "sha256": repository_digest,
        },
        "installed": installed,
        "drift_detected": any(
            item["exists"] and not item["matches_repository"] for item in installed
        ),
    }


def _font_embedding_payload(target_cjk_font: str | None, fc_list_output: str) -> dict[str, Any]:
    """Report whether the target CJK font can be embedded on this machine.

    Used by ``doctor``; never raises. Resolves the font file via ``fc-list`` and
    probes ``OS/2.fsType`` when ``fontTools`` is available.
    """
    payload: dict[str, Any] = {
        "target_font": target_cjk_font,
        "font_file": None,
        "fonttools": False,
        "fsType": None,
        "embeddable": None,
        "note": None,
    }
    if target_cjk_font is None:
        payload["note"] = "no supported CJK font installed; nothing to embed"
        return payload
    font_file = resolve_font_file(target_cjk_font, fc_list_output)
    payload["font_file"] = font_file
    if not font_file:
        payload["note"] = "font is installed but its file could not be resolved from fc-list"
        return payload
    try:
        from scripts.embed_fonts import probe_embeddability
    except ImportError:  # pragma: no cover - embed_fonts always ships alongside
        payload["note"] = "embed_fonts module unavailable"
        return payload
    probe = probe_embeddability(Path(font_file))
    payload.update(
        fonttools=bool(probe["fonttools"]),
        fsType=probe["fsType"],
        embeddable=probe["embeddable"],
        note=probe["note"],
    )
    return payload


def doctor_payload(template: Path) -> dict[str, Any]:
    imports: dict[str, bool] = {}
    for module in ("pptx", "PIL", "requests"):
        try:
            __import__(module)
        except ImportError:
            imports[module] = False
        else:
            imports[module] = True

    font_output = ""
    font_output_raw = ""
    fc_list = shutil.which("fc-list")
    if fc_list:
        completed = subprocess.run([fc_list], capture_output=True, text=True, errors="replace")
        font_output_raw = completed.stdout
        font_output = font_output_raw.lower()
    cjk_fonts = detect_cjk_fonts(font_output)
    fonts = {
        **cjk_fonts,
        "Arial Black": "arial black" in font_output,
        "Arial": "arial" in font_output,
    }
    target_cjk_font = preferred_cjk_font(cjk_fonts)
    font_embedding = _font_embedding_payload(target_cjk_font, font_output_raw)
    renderers = {
        "soffice": shutil.which("soffice"),
        "libreoffice": shutil.which("libreoffice"),
        "pdftoppm": shutil.which("pdftoppm"),
        "keynote": str(Path("/Applications/Keynote.app")) if Path("/Applications/Keynote.app").exists() else None,
        "powerpoint": str(Path("/Applications/Microsoft PowerPoint.app")) if Path("/Applications/Microsoft PowerPoint.app").exists() else None,
    }
    permission_paths = {
        "skill_root": ROOT,
        "system_temp": Path(tempfile.gettempdir()),
    }
    permissions = {
        name: {
            "path": str(path.resolve()),
            "exists": path.exists(),
            "readable": os.access(path, os.R_OK),
            "writable": os.access(path, os.W_OK),
        }
        for name, path in permission_paths.items()
    }
    errors: list[str] = []
    warnings: list[str] = []
    skill_sync = skill_drift_payload(ROOT / "SKILL.md")
    if not template.is_file():
        errors.append(f"template missing: {template}")
    if not skill_sync["repository"]["exists"]:
        errors.append(f"repository Skill entrypoint missing: {skill_sync['repository']['path']}")
    for installed in skill_sync["installed"]:
        if installed["exists"] and not installed["matches_repository"]:
            warnings.append(
                "installed Skill drift detected: "
                f"{installed['path']} differs from repository SKILL.md"
            )
    for module, available in imports.items():
        if not available:
            errors.append(f"Python dependency missing: {module}")
    if target_cjk_font is None:
        warnings.append(
            f"Neither {PRIMARY_CJK_FONT} nor {LEGACY_CJK_FONT} is installed; "
            "LibreOffice/Keynote CJK rendering may substitute or lose glyphs"
        )
    for name, permission in permissions.items():
        if not permission["exists"] or not permission["readable"]:
            errors.append(f"required directory is unavailable: {name} ({permission['path']})")
        if name == "system_temp" and not permission["writable"]:
            errors.append(f"temporary directory is not writable: {permission['path']}")
    if not any(renderers[name] for name in ("soffice", "libreoffice", "keynote", "powerpoint")):
        warnings.append("no PPT renderer detected; visual validation will use SVG/OOXML fallback only")
    elif (renderers["soffice"] or renderers["libreoffice"]) and not renderers["pdftoppm"]:
        warnings.append("LibreOffice is available but pdftoppm is missing; per-page PNG rendering is unavailable")
    return {
        "passed": not errors,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "template": str(template.resolve()),
        "dependencies": imports,
        "fonts": fonts,
        "target_cjk_font": target_cjk_font,
        "font_embedding": font_embedding,
        "renderers": renderers,
        "permissions": permissions,
        "skill_sync": skill_sync,
        "errors": errors,
        "warnings": warnings,
    }


def _project_output(project: Path, value: Path | None, default_name: str) -> Path:
    return value.resolve() if value else (project / "exports" / default_name).resolve()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check dependencies, fonts, template, and renderers")
    doctor.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    doctor.add_argument("--json", action="store_true")

    init = sub.add_parser("init", help="Create a deterministic GHB project directory")
    init.add_argument("--project", type=Path, required=True)
    init.add_argument("--dry-run", action="store_true")

    plan = sub.add_parser(
        "plan",
        help="Scaffold draft content-model/layout/art-direction/visual-profile from a confirmed brief",
    )
    plan.add_argument("--project", type=Path, required=True)
    plan.add_argument("--from-source", type=Path, help="Markdown source (default sources/source.md)")
    plan.add_argument("--confirmation", type=Path, help="confirmation.json (default project/confirmation.json)")
    plan.add_argument("--force", action="store_true", help="Overwrite existing planning drafts")
    plan.add_argument("--dry-run", action="store_true")

    analyze = sub.add_parser("analyze-template", help="Analyze a PPTX template")
    analyze.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    analyze.add_argument("--project", type=Path)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--dry-run", action="store_true")

    def add_project(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument(
            "--keep-intermediate",
            action="store_true",
            help="Explicitly retain intermediates and failed evidence (already the safe default)",
        )

    cover = sub.add_parser("build-cover", help="Build and font-normalize the GHB cover")
    add_project(cover)
    cover.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    cover.add_argument("--output", type=Path)
    cover.add_argument("--plan", type=Path)
    cover.add_argument("--title")
    cover.add_argument("--subtitle")
    cover.add_argument("--date")

    check = sub.add_parser("check-svg", help="Run authored SVG quality gates")
    add_project(check)

    check_plan_parser = sub.add_parser(
        "check-plan",
        help="Guidance-level plan check: scaffold drafts (advisory) and contract drift (error)",
    )
    add_project(check_plan_parser)

    contract = sub.add_parser(
        "check-project",
        help="Enforce confirmation, content-model, layout-plan, and authored-file contracts",
    )
    add_project(contract)
    contract.add_argument(
        "--require-visual-contract",
        action="store_true",
        default=True,
        help="Require the visual profile, art direction, and every page schema (default)",
    )

    content = sub.add_parser("build-content", help="Finalize SVG and export editable content PPTX")
    add_project(content)
    content.add_argument("--output", type=Path)

    merge = sub.add_parser("merge", help="Merge cover, editable body, master, and ending")
    add_project(merge)
    merge.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    merge.add_argument("--content", type=Path)
    merge.add_argument("--cover", type=Path)
    merge.add_argument("--output", type=Path)
    merge.add_argument("--content-layout", type=int)
    ending = merge.add_mutually_exclusive_group()
    ending.add_argument("--no-ending", action="store_true")
    ending.add_argument("--ending-slide", type=int)
    merge.add_argument(
        "--embed-fonts",
        action="store_true",
        help="Embed subsetted fonts into the merged deck (off by default; needs fonttools)",
    )
    merge.add_argument(
        "--embed-font",
        type=Path,
        action="append",
        default=[],
        dest="embed_font_paths",
        help="Explicit font file to embed (repeatable); defaults to the installed CJK font",
    )

    for name, help_text in (
        ("validate", "Validate final PPTX structure, mounts, content, and editability"),
        ("report", "Regenerate JSON and Markdown quality reports"),
    ):
        validate = sub.add_parser(name, help=help_text)
        add_project(validate)
        validate.add_argument("--pptx", type=Path)
        validate.add_argument("--body-count", type=int)
        validate.add_argument("--json-output", type=Path)
        validate.add_argument("--markdown-output", type=Path)
        validate.add_argument("--render-dir", type=Path)
        validate.add_argument("--no-ending", action="store_true")
        validate.add_argument(
            "--quality-policy", choices=("draft", "release"), default="release"
        )
        validate.add_argument("--warning-waivers", type=Path)
        validate.add_argument(
            "--target-renderer",
            choices=("auto", "libreoffice", "powerpoint", "wps"),
            default="auto",
        )

    render = sub.add_parser("render", help="Render final PPTX to PDF, page PNGs, and contact sheet")
    add_project(render)
    render.add_argument("--pptx", type=Path)
    render.add_argument("--output-dir", type=Path)
    render.add_argument("--dpi", type=int, default=144)

    review = sub.add_parser("review", help="Run one explicit optional visual review, then compose reports")
    add_project(review)
    review.add_argument("--pptx", type=Path)
    review.add_argument("--review-config", type=Path)
    review.add_argument("--review-authorization", type=Path)
    review.add_argument("--require-review", action="store_true")
    review.add_argument("--no-ending", action="store_true")
    review.add_argument(
        "--quality-policy", choices=("draft", "release"), default="release"
    )
    review.add_argument("--warning-waivers", type=Path)
    review.add_argument(
        "--target-renderer",
        choices=("auto", "libreoffice", "powerpoint", "wps"),
        default="auto",
    )

    build = sub.add_parser("build", help="Run cover, SVG gates/content export, and master merge")
    add_project(build)
    build.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    build.add_argument("--output", type=Path)
    build.add_argument("--cover-plan", type=Path)
    build.add_argument("--title")
    build.add_argument("--subtitle")
    build.add_argument("--date")
    build.add_argument("--content-layout", type=int)
    build.add_argument("--no-render", action="store_true")
    build.add_argument("--render-dpi", type=int, default=144)
    build.add_argument("--review", action="store_true")
    build.add_argument("--review-config", type=Path)
    build.add_argument("--review-authorization", type=Path)
    build.add_argument("--require-review", action="store_true")
    build.add_argument(
        "--quality-policy", choices=("draft", "release"), default="release"
    )
    build.add_argument("--warning-waivers", type=Path)
    build.add_argument(
        "--target-renderer",
        choices=("auto", "libreoffice", "powerpoint", "wps"),
        default="auto",
    )
    build.add_argument(
        "--repair-attempts",
        type=int,
        default=1,
        help="Maximum deterministic repair retries after structural validation (0-3; default 1)",
    )
    build_ending = build.add_mutually_exclusive_group()
    build_ending.add_argument("--no-ending", action="store_true")
    build_ending.add_argument("--ending-slide", type=int)
    build.add_argument(
        "--embed-fonts",
        action="store_true",
        help="Embed subsetted fonts into the final deck (off by default; needs fonttools)",
    )
    build.add_argument(
        "--embed-font",
        type=Path,
        action="append",
        default=[],
        dest="embed_font_paths",
        help="Explicit font file to embed (repeatable); defaults to the installed CJK font",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "doctor":
        payload = doctor_payload(args.template)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("PASS" if payload["passed"] else "FAIL")
            for warning in payload["warnings"]:
                print(f"WARN: {warning}")
            for error in payload["errors"]:
                print(f"ERROR: {error}")
        return 0 if payload["passed"] else 1

    if args.command == "init":
        try:
            ensure_project(args.project, create=True, dry_run=args.dry_run)
        except PipelineError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[DRY-RUN] create project {args.project} with {', '.join(REQUIRED_DIRS)}")
        else:
            print(f"[OK] Project initialized: {args.project.resolve()}")
        return 0

    if args.command == "plan":
        from scripts.plan_scaffold import ScaffoldError, scaffold_project

        if args.dry_run:
            print(f"[DRY-RUN] scaffold planning drafts under {args.project.resolve()}")
            return 0
        try:
            ensure_project(args.project)
            written = scaffold_project(
                args.project,
                source=args.from_source.resolve() if args.from_source else None,
                confirmation=args.confirmation.resolve() if args.confirmation else None,
                force=args.force,
            )
        except (PipelineError, ScaffoldError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        for path in written:
            print(f"[OK] scaffolded {path}")
        print("[NOTE] drafts carry needs_review/draft/origin markers; refine and run check-plan")
        return 0

    if args.command == "analyze-template":
        if args.project:
            try:
                ensure_project(args.project)
            except PipelineError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
        output = args.output or (
            args.project / "analysis" / "slide_library.json"
            if args.project
            else None
        )
        if output is None:
            print("[ERROR] analyze-template needs --project or --output", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[DRY-RUN] analyze {args.template} -> {output}")
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [sys.executable, str(PM / "template_fill_pptx.py"), "analyze", str(args.template), "-o", str(output)],
            cwd=ROOT,
        )
        if completed.returncode != 0:
            return completed.returncode
        if args.project:
            from scripts.template_profile import write_template_profile

            profile_path = args.project / "analysis" / "template_profile.json"
            write_template_profile(output, args.template.resolve(), profile_path)
            print(f"[OK] template profile -> {profile_path}")
        return 0

    project = args.project.resolve()
    try:
        ensure_project(project)
        run = RunContext(
            project,
            args.command,
            dry_run=args.dry_run,
            keep_intermediate=args.keep_intermediate,
        )
        try:
            if args.command == "build-cover":
                build_cover(
                    run,
                    template=args.template.resolve(),
                    output=_project_output(project, args.output, "cover.pptx"),
                    plan=args.plan.resolve() if args.plan else None,
                    title=args.title,
                    subtitle=args.subtitle,
                    date=args.date,
                )
            elif args.command == "check-svg":
                check_svg(run)
                run.checkpoint("check-svg", [])
            elif args.command == "check-plan":
                check_plan(run)
                run.checkpoint("check-plan", [])
            elif args.command == "check-project":
                check_project_contract(
                    run, require_visual_contract=True
                )
                run.checkpoint("check-project", [])
            elif args.command == "build-content":
                build_content(run, output=_project_output(project, args.output, "content.pptx"))
            elif args.command == "merge":
                check_project_contract(run, require_visual_contract=True)
                content_layout, ending_slide = _profiled_merge_values(
                    project,
                    content_layout=args.content_layout,
                    ending_slide=args.ending_slide,
                )
                merged = merge_deck(
                    run,
                    content=_project_output(project, args.content, "content.pptx"),
                    template=args.template.resolve(),
                    cover=_project_output(project, args.cover, "cover.pptx"),
                    output=_project_output(project, args.output, "final.pptx"),
                    content_layout=content_layout,
                    no_ending=args.no_ending,
                    ending_slide=ending_slide,
                )
                if args.embed_fonts:
                    embed_deck(run, pptx=merged, font_paths=args.embed_font_paths)
            elif args.command in {"validate", "report"}:
                report_dir = project / "reports"
                freshness = None
                render_dir = args.render_dir.resolve() if args.render_dir else None
                if (
                    args.command == "report"
                    and render_dir is not None
                    and render_dir != (project / "render").resolve()
                ):
                    raise PipelineError(
                        "report render evidence must use the manifest-bound project/render directory"
                    )
                pptx_path = (
                    args.pptx.resolve()
                    if args.pptx
                    else (_checkpoint_pptx(project) if args.command == "report" else None)
                ) or _project_output(project, None, "final.pptx")
                if args.command == "report":
                    manifest_path = project / ".ghb" / "evidence-manifest.json"
                    if not manifest_path.is_file():
                        raise PipelineError(
                            "evidence manifest not found; run build before report"
                        )
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        manifest_run_id = str(manifest.get("run_id", ""))
                        freshness = _report_input_freshness(
                            evidence_freshness(
                                project,
                                manifest,
                                run_id=manifest_run_id,
                                include_final=True,
                                pptx_path=pptx_path,
                            )
                        )
                    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                        raise PipelineError(f"invalid evidence manifest: {exc}") from exc
                    if not freshness.fresh:
                        stale = sorted(
                            identity
                            for identity, state in freshness.states.items()
                            if state == "stale"
                        )
                        raise PipelineError(
                            "stale evidence: " + ", ".join(stale or ["manifest-invalid"])
                        )
                    existing_render = project / "render" / "render-report.json"
                    if render_dir is None and existing_render.is_file():
                        render_dir = existing_render.parent
                json_output = (
                    args.json_output.resolve()
                    if args.json_output
                    else report_dir / "quality-report.json"
                )
                markdown_output = (
                    args.markdown_output.resolve()
                    if args.markdown_output
                    else report_dir / "quality-report.md"
                )
                review_path = project / "reports" / "visual-review.json"
                if args.command == "validate" and review_path.is_file():
                    freshness = _manifest_review_freshness(project, pptx_path)
                validate_deck(
                    run,
                    pptx=pptx_path,
                    body_count=args.body_count,
                    expect_ending=not args.no_ending,
                    json_output=json_output,
                    markdown_output=markdown_output,
                    render_dir=render_dir,
                    freshness=freshness,
                    review_report_path=(
                        review_path
                        if review_path.is_file()
                        else None
                    ),
                    review_required=bool(
                        _load_json_evidence(
                            project / ".ghb" / "adapter-policy.json"
                        ).get("required", False)
                    ),
                    quality_policy=args.quality_policy,
                    warning_waivers=(
                        args.warning_waivers.resolve() if args.warning_waivers else None
                    ),
                    target_renderer=args.target_renderer,
                )
                if args.command == "report":
                    run.checkpoint(
                        "report",
                        [pptx_path, json_output, markdown_output],
                        pptx_path=pptx_path,
                        final_report_path=json_output,
                        final_markdown_path=markdown_output,
                    )
            elif args.command == "render":
                render_deck(
                    run,
                    pptx=_project_output(project, args.pptx, "final.pptx"),
                    output_dir=(args.output_dir.resolve() if args.output_dir else project / "render"),
                    dpi=args.dpi,
                )
            elif args.command == "review":
                pptx_path = _project_output(project, args.pptx, "final.pptx")
                render_dir = project / "render"
                manifest_path = project / ".ghb" / "evidence-manifest.json"
                if not manifest_path.is_file() and not run.dry_run:
                    raise PipelineError("review requires a completed evidence manifest")
                freshness = None
                if not run.dry_run:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    freshness = _review_input_freshness(
                        evidence_freshness(
                            project,
                            manifest,
                            run_id=str(manifest.get("run_id", "")),
                            include_final=True,
                            pptx_path=pptx_path,
                        )
                    )
                    if not freshness.fresh:
                        raise PipelineError("review requires fresh deterministic and render evidence")
                review_report, _policy = run_optional_review(
                    run,
                    pptx=pptx_path,
                    render_dir=render_dir,
                    deterministic_report=project / "reports" / "quality-pre-render.json",
                    config_path=args.review_config if args.review_config else None,
                    authorization_path=(
                        args.review_authorization if args.review_authorization else None
                    ),
                    required=args.require_review,
                )
                freshness = _with_fresh_review(freshness)
                review_path = project / "reports" / "visual-review.json"
                validate_deck(
                    run,
                    pptx=pptx_path,
                    body_count=None,
                    expect_ending=not args.no_ending,
                    json_output=project / "reports" / "quality-report.json",
                    markdown_output=project / "reports" / "quality-report.md",
                    render_dir=render_dir,
                    freshness=freshness,
                    review_report_path=review_path if review_path.is_file() else None,
                    review_required=args.require_review,
                    quality_policy=args.quality_policy,
                    warning_waivers=(
                        args.warning_waivers.resolve() if args.warning_waivers else None
                    ),
                    target_renderer=args.target_renderer,
                )
                require_completed_review(review_report, required=args.require_review)
                run.checkpoint(
                    "report",
                    [
                        pptx_path,
                        project / "reports" / "quality-report.json",
                        project / "reports" / "quality-report.md",
                        review_path,
                    ],
                    pptx_path=pptx_path,
                    final_report_path=project / "reports" / "quality-report.json",
                    final_markdown_path=project / "reports" / "quality-report.md",
                )
            elif args.command == "build":
                if (args.review_config or args.review_authorization or args.require_review) and not args.review:
                    raise PipelineError("review options require explicit --review")
                if args.repair_attempts < 0 or args.repair_attempts > 3:
                    raise PipelineError("--repair-attempts must be between 0 and 3")
                cover_path = _project_output(project, None, "cover.pptx")
                content_path = _project_output(project, None, "content.pptx")
                final_path = _project_output(project, args.output, "final.pptx")
                content_layout, ending_slide = _profiled_merge_values(
                    project,
                    content_layout=args.content_layout,
                    ending_slide=args.ending_slide,
                )
                check_project_contract(run, require_visual_contract=True)
                build_cover(
                    run,
                    template=args.template.resolve(),
                    output=cover_path,
                    plan=args.cover_plan.resolve() if args.cover_plan else None,
                    title=args.title,
                    subtitle=args.subtitle,
                    date=args.date,
                )
                build_content(run, output=content_path)
                merge_deck(
                    run,
                    content=content_path,
                    template=args.template.resolve(),
                    cover=cover_path,
                    output=final_path,
                    content_layout=content_layout,
                    no_ending=args.no_ending,
                    ending_slide=ending_slide,
                )
                report_dir = project / "reports"
                pre_json = report_dir / "quality-pre-render.json"
                pre_markdown = report_dir / "quality-pre-render.md"
                fixable_merge_codes = {
                    "unregistered-used-layout",
                    "master-layout-list-mismatch",
                    "noncanonical-content-types-namespace",
                    "missing-content-override",
                    "missing-media-default",
                }
                for attempt in range(args.repair_attempts + 1):
                    try:
                        validate_deck(
                            run,
                            pptx=final_path,
                            body_count=None,
                            expect_ending=not args.no_ending,
                            json_output=pre_json,
                            markdown_output=pre_markdown,
                            quality_policy="draft",
                        )
                        break
                    except PipelineError:
                        codes = validation_error_codes(pre_json)
                        if attempt >= args.repair_attempts:
                            raise
                        if codes == {"cover-font"}:
                            run.run(
                                f"repair-cover-font-{attempt + 1}",
                                [sys.executable, str(ROOT / "scripts" / "fix_cover_font.py"), str(cover_path)],
                            )
                        elif codes and codes.issubset(fixable_merge_codes):
                            print(
                                f"[REPAIR {attempt + 1}/{args.repair_attempts}] "
                                f"rebuilding OOXML merge for {sorted(codes)}"
                            )
                        else:
                            raise
                        merge_deck(
                            run,
                            content=content_path,
                            template=args.template.resolve(),
                            cover=cover_path,
                            output=final_path,
                            content_layout=content_layout,
                            no_ending=args.no_ending,
                            ending_slide=ending_slide,
                        )
                if args.embed_fonts:
                    embed_deck(run, pptx=final_path, font_paths=args.embed_font_paths)
                render_dir = None
                if not args.no_render:
                    if shutil.which("soffice") or shutil.which("libreoffice"):
                        render_dir = render_deck(
                            run,
                            pptx=final_path,
                            output_dir=project / "render",
                            dpi=args.render_dpi,
                        )
                    else:
                        message = "no renderer detected; skipped final PPTX rendering"
                        print(f"[WARN] {message}")
                        record_unavailable_render(
                            run,
                            pptx=final_path,
                            output_dir=project / "render",
                            dpi=args.render_dpi,
                        )
                deterministic_status = "passed"
                review_freshness = None
                if args.review and render_dir is not None:
                    review_report, _policy = run_optional_review(
                        run,
                        pptx=final_path,
                        render_dir=project / "render",
                        deterministic_report=pre_json,
                        config_path=args.review_config if args.review_config else None,
                        authorization_path=(
                            args.review_authorization
                            if args.review_authorization else None
                        ),
                        required=args.require_review,
                    )
                    review_freshness = _with_fresh_review()
                elif args.review:
                    review_report, _policy = write_inactive_review_state(
                        project,
                        outcome="unavailable",
                        deterministic_status=deterministic_status,
                        required=args.require_review,
                    )
                    _record_optional_review_result(run, review_report)
                    review_freshness = _with_fresh_review()
                elif run.dry_run:
                    review_report = _inactive_review_report(
                        "skipped" if render_dir is not None else "unavailable",
                        deterministic_status=deterministic_status,
                    )
                else:
                    review_report, _policy = write_inactive_review_state(
                        project,
                        outcome="skipped" if render_dir is not None else "unavailable",
                        deterministic_status=deterministic_status,
                        required=False,
                    )
                    record_review_state(run, render_available=render_dir is not None)
                review_path = project / "reports" / "visual-review.json"
                validate_deck(
                    run,
                    pptx=final_path,
                    body_count=None,
                    expect_ending=not args.no_ending,
                    json_output=report_dir / "quality-report.json",
                    markdown_output=report_dir / "quality-report.md",
                    render_dir=render_dir,
                    freshness=review_freshness,
                    review_report_path=review_path if review_path.is_file() else None,
                    review_required=args.require_review,
                    quality_policy=args.quality_policy,
                    warning_waivers=(
                        args.warning_waivers.resolve() if args.warning_waivers else None
                    ),
                    target_renderer=args.target_renderer,
                )
                require_completed_review(review_report, required=args.require_review)
                run.checkpoint(
                    "build",
                    [
                        final_path,
                        report_dir / "quality-report.json",
                        report_dir / "quality-report.md",
                    ],
                    pptx_path=final_path,
                    final_report_path=report_dir / "quality-report.json",
                    final_markdown_path=report_dir / "quality-report.md",
                )
            run.finish()
            if not run.dry_run:
                print(f"[OK] Run log: {run.run_dir / 'run.json'}")
            return 0
        except BaseException as exc:
            run.fail(exc)
            raise
    except (OSError, PipelineError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
