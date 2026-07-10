#!/usr/bin/env python3
"""Normalize filled GHB cover slide fonts to Microsoft YaHei atomically."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


SOURCE_FONTS = ("Arial Unicode MS", "Arial Black", "楷体", "KaiTi", "Arial")


class FontFixError(RuntimeError):
    """Raised when a cover package cannot be safely rewritten."""


@dataclass(frozen=True)
class FontFixResult:
    path: Path
    changed_parts: int
    replacements: int


def fix_cover_font(path: Path, font: str = "Microsoft YaHei") -> FontFixResult:
    if not path.is_file():
        raise FontFixError(f"cover PPTX not found: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise FontFixError(f"corrupt ZIP member: {bad}")
            entries = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
                if not info.is_dir()
            }
    except zipfile.BadZipFile as exc:
        raise FontFixError(f"invalid PPTX ZIP: {path}") from exc

    slides = sorted(name for name in entries if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
    if not slides:
        raise FontFixError("cover PPTX has no slide parts")
    changed_parts = 0
    replacements = 0
    for slide in slides:
        text = entries[slide].decode("utf-8")
        updated = text
        for old in SOURCE_FONTS:
            updated, count = re.subn(
                rf'typeface="{re.escape(old)}"',
                f'typeface="{font}"',
                updated,
            )
            replacements += count
        if updated != text:
            entries[slide] = updated.encode("utf-8")
            changed_parts += 1

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)
        with zipfile.ZipFile(temp_path) as archive:
            bad = archive.testzip()
            if bad:
                raise FontFixError(f"rewritten cover contains corrupt member: {bad}")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return FontFixResult(path, changed_parts, replacements)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cover", type=Path)
    parser.add_argument("font", nargs="?", default="Microsoft YaHei")
    args = parser.parse_args(argv)
    try:
        result = fix_cover_font(args.cover, args.font)
    except (OSError, UnicodeDecodeError, FontFixError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(
        f"[OK] cover font -> {args.font} "
        f"(parts={result.changed_parts}, replacements={result.replacements})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
