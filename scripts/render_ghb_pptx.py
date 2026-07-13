#!/usr/bin/env python3
"""Render a PPTX to PDF, per-page PNGs, and a contact sheet."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class RenderError(RuntimeError):
    """Raised when a requested render backend cannot complete reliably."""


@dataclass
class RenderCommand:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass
class RenderReport:
    passed: bool
    pptx: str
    output_dir: str
    renderer: str
    renderer_path: str
    page_count: int = 0
    pdf: str | None = None
    pages: list[str] = field(default_factory=list)
    contact_sheet: str | None = None
    commands: list[RenderCommand] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def detect_renderer(preferred: str = "auto") -> tuple[str, str]:
    if preferred not in {"auto", "soffice", "libreoffice"}:
        raise RenderError(f"unsupported renderer: {preferred}")
    candidates = [preferred] if preferred != "auto" else ["soffice", "libreoffice"]
    for name in candidates:
        executable = shutil.which(name)
        if executable:
            return name, executable
    raise RenderError("no LibreOffice/soffice renderer found")


def _run(command: list[str]) -> RenderCommand:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return RenderCommand(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=round(time.monotonic() - started, 3),
    )


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
        return "fontconfig is unavailable; Microsoft YaHei presence was not checked"
    completed = subprocess.run([fc_list], capture_output=True, text=True, errors="replace")
    text = completed.stdout.lower()
    if "microsoft yahei" not in text and "微软雅黑" not in text:
        return (
            "Microsoft YaHei is not installed for this renderer; Chinese glyph substitution "
            "or loss is possible, so rendered pages require manual font review"
        )
    return None


def render_pptx(
    pptx: Path,
    output_dir: Path,
    *,
    renderer: str = "auto",
    dpi: int = 144,
    columns: int = 3,
) -> RenderReport:
    if not pptx.is_file():
        raise RenderError(f"PPTX not found: {pptx}")
    if dpi < 72 or dpi > 600:
        raise RenderError("DPI must be between 72 and 600")
    renderer_name, renderer_path = detect_renderer(renderer)
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RenderError("pdftoppm is required for deterministic per-page PNG rendering")

    output_dir.mkdir(parents=True, exist_ok=True)
    report = RenderReport(
        passed=False,
        pptx=str(pptx.resolve()),
        output_dir=str(output_dir.resolve()),
        renderer=renderer_name,
        renderer_path=renderer_path,
    )
    warning = _font_warning()
    if warning:
        report.warnings.append(warning)

    with tempfile.TemporaryDirectory(prefix="ghb-render-") as tmp:
        staging = Path(tmp) / "output"
        profile = Path(tmp) / "lo-profile"
        staging.mkdir()
        profile.mkdir()
        staged_source = Path(tmp) / f"input{pptx.suffix.lower()}"
        shutil.copy2(pptx, staged_source)
        profile_uri = profile.resolve().as_uri()
        command = [
            renderer_path,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(staging),
            str(staged_source),
        ]
        conversion = _run(command)
        report.commands.append(conversion)
        generated_pdf = staging / "input.pdf"
        if conversion.returncode or not generated_pdf.is_file():
            detail = conversion.stderr.strip() or conversion.stdout.strip() or "no PDF produced"
            report.errors.append(f"LibreOffice conversion failed: {detail}")
            return report

        page_prefix = staging / "slide"
        raster = _run([pdftoppm, "-png", "-r", str(dpi), str(generated_pdf), str(page_prefix)])
        report.commands.append(raster)
        pages = sorted(
            staging.glob("slide-*.png"),
            key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
        )
        if raster.returncode or not pages:
            detail = raster.stderr.strip() or raster.stdout.strip() or "no page PNGs produced"
            report.errors.append(f"PDF rasterization failed: {detail}")
            return report
        contact = make_contact_sheet(pages, staging / "contact-sheet.png", columns=columns)

        # Replace only files owned by this renderer, leaving unrelated user files intact.
        for stale in output_dir.glob("slide-*.png"):
            stale.unlink()
        for stale_name in ("render.pdf", "contact-sheet.png", "render-report.json"):
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

    report.passed = True
    report.page_count = len(final_pages)
    report.pdf = str(final_pdf.resolve())
    report.pages = [str(path.resolve()) for path in final_pages]
    report.contact_sheet = str(final_contact.resolve())
    report_path = output_dir / "render-report.json"
    report_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


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
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
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
