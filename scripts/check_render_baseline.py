#!/usr/bin/env python3
"""Compare a rendered slide with a tolerant, renderer-portable pixel baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image


def measure_render(path: Path) -> dict[str, float | int]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        pixel_data = (
            image.get_flattened_data()
            if hasattr(image, "get_flattened_data")
            else image.getdata()
        )
        pixels = list(pixel_data)
        width, height = image.size
    count = max(len(pixels), 1)
    non_background = sum(not (red >= 248 and green >= 248 and blue >= 248) for red, green, blue in pixels)
    brand_red = sum(
        abs(red - 0xAB) <= 45 and abs(green - 0x1F) <= 45 and abs(blue - 0x29) <= 45
        for red, green, blue in pixels
    )
    dark = sum((0.2126 * red + 0.7152 * green + 0.0722 * blue) < 100 for red, green, blue in pixels)
    mean_luma = sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in pixels
    ) / count
    return {
        "width": width,
        "height": height,
        "non_background_ratio": round(non_background / count, 6),
        "brand_red_ratio": round(brand_red / count, 6),
        "dark_ratio": round(dark / count, 6),
        "mean_luma": round(mean_luma, 3),
    }


def compare_render(metrics: dict[str, float | int], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for dimension in ("width", "height"):
        expected = baseline.get(dimension)
        actual = metrics.get(dimension)
        if isinstance(expected, dict):
            minimum, maximum = expected.get("min"), expected.get("max")
            if not isinstance(actual, (int, float)) or not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or not minimum <= actual <= maximum:
                errors.append(f"{dimension}: expected {minimum}..{maximum}, got {actual}")
        elif actual != expected:
            errors.append(f"{dimension}: expected {expected}, got {actual}")
    ranges = baseline.get("ranges")
    if not isinstance(ranges, dict):
        return [*errors, "baseline ranges are missing"]
    for name, limits in ranges.items():
        if not isinstance(limits, dict) or not isinstance(metrics.get(name), (int, float)):
            errors.append(f"{name}: invalid baseline or metric")
            continue
        value = float(metrics[name])
        minimum, maximum = limits.get("min"), limits.get("max")
        if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)):
            errors.append(f"{name}: range must contain numeric min/max")
        elif not float(minimum) <= value <= float(maximum):
            errors.append(f"{name}: expected {minimum}..{maximum}, got {value}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args(argv)
    metrics = measure_render(args.image)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    errors = compare_render(metrics, baseline)
    print(json.dumps({"passed": not errors, "metrics": metrics, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
