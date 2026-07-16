#!/usr/bin/env python3
"""Unified, checkpointed entry point for the GHB PPT pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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
from scripts.evidence_manifest import (  # noqa: E402
    EvidenceItem,
    FreshnessResult,
    create_manifest,
    evaluate_freshness,
    write_manifest_atomic,
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _svg_bundle(project: Path) -> dict[str, Any]:
    files = []
    for directory in ("svg_output", "svg_final"):
        for path in sorted((project / directory).glob("*.svg")):
            files.append(
                {
                    "path": str(path.relative_to(project)),
                    "sha256": _file_digest(path),
                }
            )
    return {"schema": "ghb.svg-bundle-evidence.v1", "files": files}


def _render_environment(project: Path) -> dict[str, Any]:
    render_payload = _load_json_evidence(project / "render" / "render-report.json")
    return {
        "schema": "ghb.render-environment.v1",
        "renderer": render_payload.get("renderer") if isinstance(render_payload, dict) else None,
        "renderer_available": bool(shutil.which("soffice") or shutil.which("libreoffice")),
        "rasterizer_available": bool(shutil.which("pdftoppm")),
        "dpi": render_payload.get("dpi") if isinstance(render_payload, dict) else None,
        "font": render_payload.get("font") if isinstance(render_payload, dict) else None,
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
    layout = project / "layout_plan.json"
    rules = ROOT / "references" / "visual-quality-rules.md"
    items = [
        EvidenceItem("visual-profile", "json", _load_json_evidence(profile), profile if profile.is_file() else None),
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
        "build-content": 1,
        "merge": 2,
        "validate": 3,
        "render": 4,
        "build": 5,
    }
    level = stage_order.get(stage, 0)
    if level >= 1 or include_final:
        items.append(EvidenceItem("svg-bundle", "svg-bundle", _svg_bundle(project)))
    pptx = (pptx_path or project / "exports" / "final.pptx").resolve()
    if level >= 2 or include_final:
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
    if level >= 3 or include_final:
        items.append(
            EvidenceItem(
                "deterministic-report",
                "json",
                _load_json_evidence(deterministic_report_path),
                deterministic_report_path if deterministic_report_path.is_file() else None,
            )
        )
    render_path = project / "render" / "render-report.json"
    if level >= 4 or include_final:
        items.extend(
            [
                EvidenceItem("render-environment", "environment", _render_environment(project)),
                EvidenceItem(
                    "render-evidence",
                    "json",
                    _load_json_evidence(render_path),
                    render_path if render_path.is_file() else None,
                ),
            ]
        )
    if include_final:
        render_payload = _load_json_evidence(render_path)
        render_status = render_payload.get("status") if isinstance(render_payload, dict) else None
        review_outcome = "skipped" if render_status == "passed" else "unavailable"
        items.extend(
            [
                EvidenceItem("adapter-policy", "optional-review-policy", {"status": "absent"}),
                EvidenceItem(
                    "adapter-review",
                    "optional-review",
                    {"outcome": review_outcome, "implementation": "absent"},
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


def _write_cover_plan(path: Path, title: str, subtitle: str, date: str) -> None:
    payload = {
        "schema": "template_fill_pptx_plan.v1",
        "slides": [
            {
                "source_slide": 1,
                "purpose": "封面",
                "replacements": [
                    {"slot_id": "s01_sh8", "text": title},
                    {"slot_id": "s01_sh6", "text": subtitle},
                    {"slot_id": "s01_sh4", "text": date},
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
    resolved_plan = plan or run.project / "analysis" / "cover_fill_plan.json"
    if plan is None:
        if not all((title, subtitle, date)):
            raise PipelineError("build-cover needs --plan or all of --title/--subtitle/--date")
        if run.dry_run:
            run.plan("cover-plan", f"write {resolved_plan}")
        else:
            _write_cover_plan(resolved_plan, title or "", subtitle or "", date or "")
    elif not plan.is_file():
        raise PipelineError(f"cover plan not found: {plan}")

    run.run("analyze-template", [sys.executable, str(PM / "template_fill_pptx.py"), "analyze", str(template), "-o", str(analysis)])
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
    check_project_contract(run)
    run_svg_gate(run, stage="authored")


def build_content(run: RunContext, *, output: Path) -> Path:
    check_svg(run)
    backup_dir = run.run_dir / "authored-svg"
    if run.dry_run:
        run.plan("remove-background", f"validate/remove GHB preview backgrounds; backup -> {backup_dir}")
    else:
        try:
            results = remove_project_backgrounds(run.project, backup_dir=backup_dir)
        except (OSError, BackgroundRemovalError) as exc:
            raise PipelineError(str(exc)) from exc
        run.record.stages.append(
            {"stage": "remove-background", "results": [asdict(result) for result in results]}
        )
        run._write_record()

    total_notes = run.project / "notes" / "total.md"
    if total_notes.exists() or run.dry_run:
        run.run("split-notes", [sys.executable, str(PM / "total_md_split.py"), str(run.project)])
    run.run("finalize-svg", [sys.executable, str(PM / "finalize_svg.py"), str(run.project)])
    run_svg_gate(run, stage="finalized")
    run.run(
        "svg-to-pptx",
        [sys.executable, str(PM / "svg_to_pptx.py"), str(run.project), "-o", str(output), "--animation", "none", "--transition", "none"],
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
    command.append("--expect-ending" if expect_ending else "--no-ending")
    if render_dir is not None:
        command.extend(["--render-dir", str(render_dir)])
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
    fc_list = shutil.which("fc-list")
    if fc_list:
        completed = subprocess.run([fc_list], capture_output=True, text=True, errors="replace")
        font_output = completed.stdout.lower()
    fonts = {
        "Microsoft YaHei": "microsoft yahei" in font_output or "微软雅黑" in font_output,
        "Arial Black": "arial black" in font_output,
        "Arial": "arial" in font_output,
    }
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
    if not template.is_file():
        errors.append(f"template missing: {template}")
    for module, available in imports.items():
        if not available:
            errors.append(f"Python dependency missing: {module}")
    if not fonts["Microsoft YaHei"]:
        warnings.append("Microsoft YaHei is not installed; LibreOffice/Keynote CJK rendering may substitute or lose glyphs")
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
        "renderers": renderers,
        "permissions": permissions,
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

    contract = sub.add_parser(
        "check-project",
        help="Enforce confirmation, content-model, layout-plan, and authored-file contracts",
    )
    add_project(contract)
    contract.add_argument(
        "--require-visual-contract",
        action="store_true",
        help="Opt into the v1 visual profile and per-page schema gate before the U11 rollout",
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
    merge.add_argument("--content-layout", type=int, default=2)
    ending = merge.add_mutually_exclusive_group()
    ending.add_argument("--no-ending", action="store_true")
    ending.add_argument("--ending-slide", type=int)

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

    render = sub.add_parser("render", help="Render final PPTX to PDF, page PNGs, and contact sheet")
    add_project(render)
    render.add_argument("--pptx", type=Path)
    render.add_argument("--output-dir", type=Path)
    render.add_argument("--dpi", type=int, default=144)

    build = sub.add_parser("build", help="Run cover, SVG gates/content export, and master merge")
    add_project(build)
    build.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    build.add_argument("--output", type=Path)
    build.add_argument("--cover-plan", type=Path)
    build.add_argument("--title")
    build.add_argument("--subtitle")
    build.add_argument("--date")
    build.add_argument("--content-layout", type=int, default=2)
    build.add_argument("--no-render", action="store_true")
    build.add_argument("--render-dpi", type=int, default=144)
    build.add_argument(
        "--repair-attempts",
        type=int,
        default=1,
        help="Maximum deterministic repair retries after structural validation (0-3; default 1)",
    )
    build_ending = build.add_mutually_exclusive_group()
    build_ending.add_argument("--no-ending", action="store_true")
    build_ending.add_argument("--ending-slide", type=int)
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
        return completed.returncode

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
            elif args.command == "check-project":
                check_project_contract(
                    run, require_visual_contract=args.require_visual_contract
                )
                run.checkpoint("check-project", [])
            elif args.command == "build-content":
                build_content(run, output=_project_output(project, args.output, "content.pptx"))
            elif args.command == "merge":
                check_project_contract(run)
                merge_deck(
                    run,
                    content=_project_output(project, args.content, "content.pptx"),
                    template=args.template.resolve(),
                    cover=_project_output(project, args.cover, "cover.pptx"),
                    output=_project_output(project, args.output, "final.pptx"),
                    content_layout=args.content_layout,
                    no_ending=args.no_ending,
                    ending_slide=args.ending_slide,
                )
            elif args.command in {"validate", "report"}:
                report_dir = project / "reports"
                freshness = None
                render_dir = args.render_dir.resolve() if args.render_dir else None
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
                validate_deck(
                    run,
                    pptx=pptx_path,
                    body_count=args.body_count,
                    expect_ending=not args.no_ending,
                    json_output=json_output,
                    markdown_output=markdown_output,
                    render_dir=render_dir,
                    freshness=freshness,
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
            elif args.command == "build":
                if args.repair_attempts < 0 or args.repair_attempts > 3:
                    raise PipelineError("--repair-attempts must be between 0 and 3")
                cover_path = _project_output(project, None, "cover.pptx")
                content_path = _project_output(project, None, "content.pptx")
                final_path = _project_output(project, args.output, "final.pptx")
                check_project_contract(run)
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
                    content_layout=args.content_layout,
                    no_ending=args.no_ending,
                    ending_slide=args.ending_slide,
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
                            content_layout=args.content_layout,
                            no_ending=args.no_ending,
                            ending_slide=args.ending_slide,
                        )
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
                record_review_state(run, render_available=render_dir is not None)
                validate_deck(
                    run,
                    pptx=final_path,
                    body_count=None,
                    expect_ending=not args.no_ending,
                    json_output=report_dir / "quality-report.json",
                    markdown_output=report_dir / "quality-report.md",
                    render_dir=render_dir,
                )
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
