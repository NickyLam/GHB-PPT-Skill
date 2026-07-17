#!/usr/bin/env python3
"""Render a PPTX to PDF, per-page PNGs, and a contact sheet."""

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
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from .font_policy import (
        LEGACY_CJK_FONT,
        PRIMARY_CJK_FONT,
        detect_cjk_fonts,
        preferred_cjk_font,
    )
except ImportError:  # Direct script execution.
    from font_policy import (
        LEGACY_CJK_FONT,
        PRIMARY_CJK_FONT,
        detect_cjk_fonts,
        preferred_cjk_font,
    )


class RenderError(RuntimeError):
    """Raised when a requested render backend cannot complete reliably."""


FONTCONFIG_FILES = (
    Path("/opt/homebrew/etc/fonts/fonts.conf"),
    Path("/usr/local/etc/fonts/fonts.conf"),
    Path("/etc/fonts/fonts.conf"),
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RenderCommand:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass
class RenderReport:
    schema: str
    status: str
    passed: bool
    pptx: str
    pptx_sha256: str | None
    output_dir: str
    renderer: str
    renderer_path: str | None
    dpi: int
    font: dict[str, object]
    page_count: int = 0
    pdf: str | None = None
    pages: list[str] = field(default_factory=list)
    contact_sheet: str | None = None
    commands: list[RenderCommand] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def outputs(self) -> list[str]:
        return [value for value in [self.pdf, *self.pages, self.contact_sheet] if value]


def _write_report_atomic(output_dir: Path, report: RenderReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "render-report.json"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=output_dir
    )
    temp_path = Path(temp_name)
    try:
        payload = asdict(report)
        payload["outputs"] = report.outputs
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def detect_renderer(preferred: str = "auto") -> tuple[str, str]:
    if preferred not in {"auto", "soffice", "libreoffice"}:
        raise RenderError(f"unsupported renderer: {preferred}")
    candidates = [preferred] if preferred != "auto" else ["soffice", "libreoffice"]
    for name in candidates:
        executable = shutil.which(name)
        if executable:
            return name, executable
    raise RenderError("no LibreOffice/soffice renderer found")


def _run(command: list[str], *, env: dict[str, str] | None = None) -> RenderCommand:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return RenderCommand(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=round(time.monotonic() - started, 3),
    )


def _render_environment(cache_dir: Path) -> dict[str, str]:
    """Give isolated LibreOffice a writable cache and host font directories."""
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(cache_dir)
    configured = env.get("FONTCONFIG_FILE")
    if not configured or not Path(configured).is_file():
        for candidate in FONTCONFIG_FILES:
            if candidate.is_file():
                env["FONTCONFIG_FILE"] = str(candidate)
                env["FONTCONFIG_PATH"] = str(candidate.parent)
                break
    return env


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Verdana.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_contact_sheet(
    pages: list[Path],
    output: Path,
    *,
    columns: int = 3,
    thumb_width: int = 384,
    padding: int = 12,
) -> Path:
    if not pages:
        raise RenderError("cannot create contact sheet without page images")
    columns = max(1, columns)
    thumbnails: list[Image.Image] = []
    for path in pages:
        with Image.open(path) as image:
            converted = image.convert("RGB")
            height = max(1, round(converted.height * thumb_width / converted.width))
            thumbnails.append(converted.resize((thumb_width, height), Image.Resampling.LANCZOS))
    thumb_height = max(image.height for image in thumbnails)
    label_height = 30
    rows = (len(thumbnails) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (
            padding + columns * (thumb_width + padding),
            padding + rows * (thumb_height + label_height + padding),
        ),
        "#ECEFF3",
    )
    draw = ImageDraw.Draw(canvas)
    font = _font(14)
    for index, image in enumerate(thumbnails, 1):
        row = (index - 1) // columns
        column = (index - 1) % columns
        x = padding + column * (thumb_width + padding)
        y = padding + row * (thumb_height + label_height + padding)
        canvas.paste(image, (x, y))
        draw.text((x, y + thumb_height + 6), f"Slide {index:02d}", fill="#2B2B2B", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    return output


def _font_warning() -> str | None:
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return "fontconfig is unavailable; target CJK font presence was not checked"
    completed = subprocess.run([fc_list], capture_output=True, text=True, errors="replace")
    if preferred_cjk_font(detect_cjk_fonts(completed.stdout)) is None:
        return (
            f"Neither {PRIMARY_CJK_FONT} nor {LEGACY_CJK_FONT} is installed for this renderer; "
            "Chinese glyph substitution or loss is possible, so rendered pages require "
            "manual font review"
        )
    return None


def _render_outputs(
    report: RenderReport,
    *,
    pptx: Path,
    output_dir: Path,
    renderer_path: str,
    pdftoppm: str,
    dpi: int,
    columns: int,
) -> tuple[Path, list[Path], Path]:
    with tempfile.TemporaryDirectory(prefix="ghb-render-") as tmp:
        staging = Path(tmp) / "output"
        profile = Path(tmp) / "lo-profile"
        font_cache = Path(tmp) / "font-cache"
        staging.mkdir()
        profile.mkdir()
        font_cache.mkdir()
        staged_source = Path(tmp) / f"input{pptx.suffix.lower()}"
        shutil.copy2(pptx, staged_source)
        command = [
            renderer_path,
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(staging),
            str(staged_source),
        ]
        conversion = _run(command, env=_render_environment(font_cache))
        report.commands.append(conversion)
        generated_pdf = staging / "input.pdf"
        if conversion.returncode or not generated_pdf.is_file():
            detail = conversion.stderr.strip() or conversion.stdout.strip() or "no PDF produced"
            raise RenderError(f"LibreOffice conversion failed: {detail}")

        page_prefix = staging / "slide"
        raster = _run([pdftoppm, "-png", "-r", str(dpi), str(generated_pdf), str(page_prefix)])
        report.commands.append(raster)
        pages = sorted(
            staging.glob("slide-*.png"),
            key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
        )
        if raster.returncode or not pages:
            detail = raster.stderr.strip() or raster.stdout.strip() or "no page PNGs produced"
            raise RenderError(f"PDF rasterization failed: {detail}")
        contact = make_contact_sheet(pages, staging / "contact-sheet.png", columns=columns)

        # Replace only files owned by this renderer, leaving unrelated user files intact.
        for stale in output_dir.glob("slide-*.png"):
            stale.unlink()
        for stale_name in ("render.pdf", "contact-sheet.png"):
            stale = output_dir / stale_name
            if stale.exists():
                stale.unlink()
        final_pdf = output_dir / "render.pdf"
        shutil.copy2(generated_pdf, final_pdf)
        final_pages: list[Path] = []
        for index, page in enumerate(pages, 1):
            destination = output_dir / f"slide-{index:02d}.png"
            shutil.copy2(page, destination)
            final_pages.append(destination)
        final_contact = output_dir / "contact-sheet.png"
        shutil.copy2(contact, final_contact)
    return final_pdf, final_pages, final_contact


def render_pptx(
    pptx: Path,
    output_dir: Path,
    *,
    renderer: str = "auto",
    dpi: int = 144,
    columns: int = 3,
) -> RenderReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    pptx_exists = pptx.is_file()
    report = RenderReport(
        schema="ghb.render-report.v1",
        status="error",
        passed=False,
        pptx=str(pptx.resolve()),
        pptx_sha256=_file_sha256(pptx) if pptx_exists else None,
        output_dir=str(output_dir.resolve()),
        renderer=renderer,
        renderer_path=None,
        dpi=dpi,
        font={"status": "unknown", "warnings": []},
    )
    if not pptx_exists:
        report.errors.append(f"PPTX not found: {pptx}")
        _write_report_atomic(output_dir, report)
        return report
    if dpi < 72 or dpi > 600:
        report.errors.append("DPI must be between 72 and 600")
        _write_report_atomic(output_dir, report)
        return report
    try:
        renderer_name, renderer_path = detect_renderer(renderer)
        report.renderer = renderer_name
        report.renderer_path = renderer_path
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise RenderError("pdftoppm is required for deterministic per-page PNG rendering")
        warning = _font_warning()
        font = font_evidence(warning)
        if warning:
            report.warnings.append(warning)
        report.font = font
    except RenderError as exc:
        report.status = "unavailable"
        report.errors.append(str(exc))
        _write_report_atomic(output_dir, report)
        return report

    assert report.renderer_path is not None
    try:
        final_pdf, final_pages, final_contact = _render_outputs(
            report,
            pptx=pptx,
            output_dir=output_dir,
            renderer_path=report.renderer_path,
            pdftoppm=pdftoppm,
            dpi=dpi,
            columns=columns,
        )
    except (OSError, RenderError) as exc:
        report.status = "error"
        report.errors.append(str(exc))
        _write_report_atomic(output_dir, report)
        return report

    report.passed = True
    report.status = "passed"
    report.page_count = len(final_pages)
    report.pdf = str(final_pdf.resolve())
    report.pages = [str(path.resolve()) for path in final_pages]
    report.contact_sheet = str(final_contact.resolve())
    _write_report_atomic(output_dir, report)
    return report


def font_evidence(warning: str | None) -> dict[str, Any]:
    """Project the target-font probe into stable render evidence."""
    if warning:
        return {
            "status": "limited",
            "warnings": [warning],
            "limitation_codes": ["target-font-missing"],
        }
    return {"status": "available", "warnings": [], "limitation_codes": []}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--renderer", choices=("auto", "soffice", "libreoffice"), default="auto")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = render_pptx(
            args.pptx,
            args.output_dir,
            renderer=args.renderer,
            dpi=args.dpi,
            columns=args.columns,
        )
    except (OSError, RenderError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if args.json:
        payload = asdict(report)
        payload["outputs"] = report.outputs
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[{'PASS' if report.passed else 'FAIL'}] renderer={report.renderer} pages={report.page_count}")
        for warning in report.warnings:
            print(f"WARN: {warning}")
        for error in report.errors:
            print(f"ERROR: {error}")
        if report.contact_sheet:
            print(f"Contact sheet: {report.contact_sheet}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
