#!/usr/bin/env python3
"""Validate and freeze the offline visual benchmark contract without rendering."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("visual_quality_cases.json")
PREFERENCES_PATH = Path(__file__).with_name("visual_preferences.json")
SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
PRECHANGE_SVG_DIR = Path(__file__).with_name("visual_prechange_svg")
PURPOSES = {"architecture", "process", "comparison", "timeline", "metrics", "summary"}
PARTITIONS = {"calibration", "pilot-holdout", "final-holdout"}
CONSUMER_PARTITION = {
    "tuning": "calibration",
    "u11-pilot": "pilot-holdout",
    "final-evaluation": "final-holdout",
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def partition_digest(cases: list[dict[str, Any]]) -> str:
    assignments = sorted((case["case_id"], case["partition"]) for case in cases)
    return canonical_sha256(assignments)


def advisory_denominator_digest(pairs: list[str]) -> str:
    return canonical_sha256(sorted(pairs))


def cases_for_consumer(corpus: dict[str, Any], consumer: str) -> list[dict[str, Any]]:
    try:
        partition = CONSUMER_PARTITION[consumer]
    except KeyError as exc:
        raise ValueError(f"unknown benchmark consumer: {consumer}") from exc
    return [dict(case) for case in corpus["cases"] if case["partition"] == partition]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_contracts(corpus: dict[str, Any], preferences: dict[str, Any]) -> None:
    _require(corpus.get("schema") == "ghb.visual-quality-corpus.v1", "unknown corpus schema")
    _require(preferences.get("schema") == "ghb.visual-preferences.v1", "unknown preferences schema")
    cases = corpus.get("cases")
    _require(isinstance(cases, list) and len(cases) >= 30, "corpus requires at least 30 cases")
    ids = [case.get("case_id") for case in cases]
    _require(all(isinstance(case_id, str) and case_id for case_id in ids), "case_id is required")
    _require(len(ids) == len(set(ids)), "duplicate case_id")
    source_ids = [
        (case.get("source", {}).get("scenario_id"), case.get("source", {}).get("body_slide_index"))
        for case in cases
    ]
    _require(len(source_ids) == len(set(source_ids)), "source identity cannot cross cases or partitions")
    _require({case.get("page_purpose") for case in cases} == PURPOSES, "all six page purposes are required")

    coverage: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        purpose = case.get("page_purpose")
        partition = case.get("partition")
        _require(partition in PARTITIONS, f"{case['case_id']}: invalid partition")
        coverage[purpose][partition] += 1
        _require(case.get("density") in {"breathing", "anchor", "dense"}, f"{case['case_id']}: invalid density")
        _require(case.get("content_length_band") in {"short", "medium", "long"}, f"{case['case_id']}: invalid content band")
        _require(case.get("item_count_band") in {"few", "standard", "many"}, f"{case['case_id']}: invalid item band")
        source = case.get("source", {})
        _require(source.get("scenario_file") == "tests/fixtures/scenarios.json", f"{case['case_id']}: invalid scenario source")
        _require(isinstance(source.get("scenario_id"), str), f"{case['case_id']}: scenario_id is required")
        _require(isinstance(source.get("body_slide_index"), int), f"{case['case_id']}: body_slide_index is required")
        evidence = case.get("pre_change_evidence", {})
        _require(evidence.get("categorical_status") in {"approved-current", "known-limitation"}, f"{case['case_id']}: categorical evidence is required")
        provenance = evidence.get("provenance", {})
        _require(isinstance(provenance.get("renderer"), str), f"{case['case_id']}: renderer is required")
        _require(isinstance(provenance.get("dpi"), int), f"{case['case_id']}: dpi is required")
        _require(isinstance(provenance.get("fonts"), list), f"{case['case_id']}: fonts are required")
        digest = evidence.get("authored_svg_sha256")
        _require(isinstance(digest, str) and len(digest) == 64, f"{case['case_id']}: authored SVG digest is required")
        _require(evidence.get("rendered_png") is None, f"{case['case_id']}: rendered PNG must not be fabricated")
        _require(evidence.get("render_status") == "unavailable-without-render", f"{case['case_id']}: render limitation is required")
    for purpose in PURPOSES:
        _require(coverage[purpose]["calibration"] >= 2, f"{purpose}: needs two calibration cases")
        _require(coverage[purpose]["pilot-holdout"] >= 1, f"{purpose}: needs one pilot holdout")
        _require(coverage[purpose]["final-holdout"] >= 2, f"{purpose}: needs two final holdouts")
    _require(partition_digest(cases) == corpus.get("partition_assignment_sha256"), "partition assignment digest changed")

    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    _require(sum(len(scenario["slides"]) for scenario in scenarios.values()) == 30, "scenario corpus must contain exactly 30 independent pages")
    for case in cases:
        source = case["source"]
        try:
            slide = scenarios[source["scenario_id"]]["slides"][source["body_slide_index"] - 1]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"{case['case_id']}: source slide does not exist") from exc
        _require(slide.get("page_purpose") == case["page_purpose"], f"{case['case_id']}: page-purpose drift")
        _require(slide.get("density") == case["density"], f"{case['case_id']}: density drift")

    protocol = preferences.get("blind_review_protocol", {})
    _require(protocol.get("pair_order_randomized") is True, "pair order must be randomized")
    _require(protocol.get("identity_anonymized") is True, "pair identities must be anonymized")
    _require(protocol.get("minimum_independent_eligible_reviewers_per_page", 0) >= 3, "three reviewers are required")
    _require(protocol.get("minimum_eligible_non_tie_judgments_per_page", 0) >= 2, "two non-tie judgments are required")
    _require(protocol.get("structural_regression") == "page-level-veto", "structural regression must veto the page")
    gate = preferences.get("deterministic_pilot_false_positive_gate", {})
    pairs = gate.get("advisory_rule_case_pairs", [])
    _require(gate.get("blocking_false_positive_maximum") == 0, "blocking false positives must be zero")
    _require(gate.get("advisory_false_positive_rate_maximum") == 0.10, "advisory ceiling must be 10 percent")
    _require(gate.get("advisory_denominator_count") == len(pairs), "advisory denominator count changed")
    _require(len(pairs) == len(set(pairs)), "duplicate advisory rule/case pair")
    _require(advisory_denominator_digest(pairs) == gate.get("advisory_denominator_sha256"), "advisory denominator digest changed")
    pilot_ids = {case["case_id"] for case in cases if case["partition"] == "pilot-holdout"}
    _require({pair.split("::", 1)[0] for pair in pairs} == pilot_ids, "advisory denominator must cover every pilot case")


def build(output: Path, corpus: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    validate_contracts(corpus, preferences)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite frozen benchmark output: {output}")
    output.mkdir(parents=True)
    svg_dir = output / "authored-svg"
    svg_dir.mkdir()
    generated: list[dict[str, str]] = []
    for case in corpus["cases"]:
        frozen_svg = PRECHANGE_SVG_DIR / f"{case['case_id']}.svg"
        if not frozen_svg.is_file() or frozen_svg.is_symlink():
            raise ValueError(f"{case['case_id']}: frozen pre-change SVG is missing or unsafe")
        digest = hashlib.sha256(frozen_svg.read_bytes()).hexdigest()
        if digest != case["pre_change_evidence"]["authored_svg_sha256"]:
            raise ValueError(f"{case['case_id']}: pre-change SVG digest changed")
        svg_path = svg_dir / frozen_svg.name
        shutil.copy2(frozen_svg, svg_path)
        generated.append({"case_id": case["case_id"], "authored_svg_sha256": digest})
    shutil.copy2(CASES_PATH, output / CASES_PATH.name)
    shutil.copy2(PREFERENCES_PATH, output / PREFERENCES_PATH.name)
    result = {
        "schema": "ghb.visual-benchmark-manifest.v1",
        "case_count": len(corpus["cases"]),
        "corpus_sha256": canonical_sha256(corpus),
        "preferences_sha256": canonical_sha256(preferences),
        "partition_assignment_sha256": corpus["partition_assignment_sha256"],
        "network": "disabled-not-required",
        "model_adapter": "not-used",
        "credentials": "not-used",
        "binary_evidence": "copied-from-versioned-pre-change-svg-fixtures",
        "generated_authored_svg": generated,
    }
    (output / "benchmark-manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--consumer", choices=sorted(CONSUMER_PARTITION))
    args = parser.parse_args()
    corpus = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    preferences = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    validate_contracts(corpus, preferences)
    if args.consumer:
        print(json.dumps(cases_for_consumer(corpus, args.consumer), ensure_ascii=False, indent=2))
        return 0
    if args.validate_only:
        print(f"validated {len(corpus['cases'])} frozen visual benchmark cases")
        return 0
    if args.output is None:
        parser.error("--output is required unless --validate-only or --consumer is used")
    result = build(args.output, corpus, preferences)
    print(f"frozen {result['case_count']} cases at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
