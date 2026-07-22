#!/usr/bin/env python3
"""Versioned canonical evidence manifests and dependency-aware freshness checks.

This module is deliberately provider-neutral and has no CLI or pipeline side
effects.  Callers describe evidence; this module snapshots its semantic and
byte digests and later decides whether that snapshot is still usable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Mapping


MANIFEST_SCHEMA = "ghb.evidence-manifest.v2"
CANONICALIZATION_SCHEMA = "ghb.canonical-json.v1"

# The dependency graph is part of the evidence contract, not caller folklore.
# Ordered keys also make serialized manifests easy to inspect and diff.
DEFAULT_DEPENDENCY_DAG: dict[str, tuple[str, ...]] = {
    "visual-profile": (),
    "art-direction": (),
    "layout-plan": (),
    "rule-contract": (),
    "authored-svg-bundle": (
        "visual-profile",
        "art-direction",
        "layout-plan",
        "rule-contract",
    ),
    "finalized-svg-bundle": ("authored-svg-bundle",),
    "pptx": ("finalized-svg-bundle",),
    "render-environment": (),
    "render-evidence": ("pptx", "render-environment"),
    "deterministic-report": (
        "visual-profile",
        "art-direction",
        "layout-plan",
        "rule-contract",
        "authored-svg-bundle",
        "finalized-svg-bundle",
        "pptx",
    ),
    "adapter-policy": (),
    "adapter-review": ("render-evidence", "deterministic-report", "adapter-policy"),
    "final-report": ("deterministic-report", "render-evidence", "adapter-review"),
}

_INPUT_IDENTITIES = {
    "visual-profile",
    "art-direction",
    "layout-plan",
    "rule-contract",
    "render-environment",
    "adapter-policy",
}
_VOLATILE_KEYS = {
    "timestamp",
    "created_at",
    "updated_at",
    "generated_at",
    "completed_at",
    "run_id",
    "run_dir",
    "run_directory",
    "run_path",
    "output_dir",
    "output_directory",
    "output_path",
    "absolute_path",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EvidenceItem:
    """Current semantic and optional byte evidence for one logical identity."""

    identity: str
    kind: str
    semantic: Any
    content: bytes | Path | None = None
    depends_on: tuple[str, ...] | None = None


@dataclass(frozen=True)
class FreshnessResult:
    """Orthogonal freshness states plus fail-visible contract issues."""

    states: dict[str, str]
    issues: tuple[dict[str, str], ...]

    @property
    def fresh(self) -> bool:
        return bool(self.states) and not self.issues and all(
            state == "fresh" for state in self.states.values()
        )

    @property
    def issue_codes(self) -> frozenset[str]:
        return frozenset(item["code"] for item in self.issues)


def _issue(code: str, message: str, identity: str | None = None) -> dict[str, str]:
    result = {"severity": "error", "code": code, "message": message}
    if identity is not None:
        result["identity"] = identity
    return result


def _is_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            if key.lower() in _VOLATILE_KEYS:
                continue
            result[key] = _canonicalize(value[key])
        return result
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, str) and _is_absolute_path(value):
        return "<absolute-path>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_digest(value: Any) -> str:
    """Hash semantic JSON after removing documented run-local metadata."""

    payload = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _content_digest(content: bytes | Path | None) -> str | None:
    if content is None:
        return None
    if isinstance(content, bytes):
        payload = content
    elif isinstance(content, Path):
        if not content.is_file() or content.is_symlink():
            raise ValueError(f"evidence content must be a regular non-symlink file: {content}")
        payload = content.read_bytes()
    else:
        raise TypeError("evidence content must be bytes, pathlib.Path, or None")
    return hashlib.sha256(payload).hexdigest()


def _dependencies(item: EvidenceItem) -> tuple[str, ...]:
    if item.depends_on is not None:
        return tuple(item.depends_on)
    return DEFAULT_DEPENDENCY_DAG.get(item.identity, ())


def create_manifest(
    *,
    project_id: str,
    run_id: str,
    items: Iterable[EvidenceItem],
) -> dict[str, Any]:
    """Create an immutable digest snapshot for a logical project and run."""

    if not project_id or not run_id:
        raise ValueError("project_id and run_id must be non-empty logical identities")
    supplied_items = list(items)
    order = {identity: index for index, identity in enumerate(DEFAULT_DEPENDENCY_DAG)}
    supplied_items.sort(key=lambda item: (order.get(item.identity, len(order)), item.identity))
    records = []
    seen: set[str] = set()
    for item in supplied_items:
        if not item.identity or not item.kind:
            raise ValueError("evidence identity and kind must be non-empty")
        if item.identity in seen:
            raise ValueError(f"duplicate evidence identity: {item.identity}")
        seen.add(item.identity)
        records.append(
            {
                "identity": item.identity,
                "kind": item.kind,
                "role": "input" if item.identity in _INPUT_IDENTITIES else "envelope",
                "depends_on": list(_dependencies(item)),
                "canonical_sha256": canonical_digest(item.semantic),
                "byte_sha256": _content_digest(item.content),
            }
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "canonicalization": CANONICALIZATION_SCHEMA,
        "project_id": project_id,
        "run_id": run_id,
        "evidence": records,
    }
    issues, _ = _validate_manifest(manifest)
    if issues:
        rendered = "; ".join(f"{item['code']}: {item['message']}" for item in issues)
        raise ValueError(rendered)
    return manifest


def _validate_manifest(
    manifest: Mapping[str, Any] | Any,
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    issues: list[dict[str, str]] = []
    if not isinstance(manifest, Mapping):
        return [_issue("evidence-invalid-manifest", "manifest must be a JSON object")], {}
    if manifest.get("schema") != MANIFEST_SCHEMA:
        issues.append(_issue(
            "evidence-unknown-manifest-version",
            f"manifest schema must be {MANIFEST_SCHEMA}",
        ))
    if manifest.get("canonicalization") != CANONICALIZATION_SCHEMA:
        issues.append(_issue(
            "evidence-unknown-canonicalization-version",
            f"canonicalization must be {CANONICALIZATION_SCHEMA}",
        ))
    records = manifest.get("evidence")
    if not isinstance(records, list):
        issues.append(_issue("evidence-invalid-records", "evidence must be a list"))
        return issues, {}

    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("identity"), str):
            issues.append(_issue("evidence-invalid-record", "every evidence record requires an identity"))
            continue
        identity = record["identity"]
        if identity in by_id:
            issues.append(_issue(
                "evidence-duplicate-identity",
                f"evidence identity appears more than once: {identity}",
                identity,
            ))
            continue
        by_id[identity] = record
        dependencies = record.get("depends_on")
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            issues.append(_issue(
                "evidence-invalid-dependencies", "depends_on must be a string list", identity
            ))
        elif len(dependencies) != len(set(dependencies)):
            issues.append(_issue(
                "evidence-duplicate-dependency", "depends_on contains duplicates", identity
            ))
        if not _SHA256_RE.fullmatch(str(record.get("canonical_sha256", ""))):
            issues.append(_issue(
                "evidence-invalid-digest", "canonical_sha256 must be a lowercase SHA-256", identity
            ))
        byte_digest = record.get("byte_sha256")
        if byte_digest is not None and not _SHA256_RE.fullmatch(str(byte_digest)):
            issues.append(_issue(
                "evidence-invalid-digest", "byte_sha256 must be null or a lowercase SHA-256", identity
            ))

    for identity, record in by_id.items():
        dependencies = record.get("depends_on")
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if dependency not in by_id:
                issues.append(_issue(
                    "evidence-missing-dependency",
                    f"dependency {dependency} is absent from the manifest",
                    identity,
                ))
        expected = DEFAULT_DEPENDENCY_DAG.get(identity)
        if expected is not None and tuple(dependencies) != expected:
            issues.append(_issue(
                "evidence-dependency-mismatch",
                f"dependencies do not match the v1 contract for {identity}",
                identity,
            ))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identity: str) -> bool:
        if identity in visiting:
            return True
        if identity in visited:
            return False
        visiting.add(identity)
        dependencies = by_id[identity].get("depends_on")
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if dependency in by_id and visit(dependency):
                    return True
        visiting.remove(identity)
        visited.add(identity)
        return False

    if any(visit(identity) for identity in by_id if identity not in visited):
        issues.append(_issue("evidence-dependency-cycle", "evidence dependency graph contains a cycle"))
    return issues, by_id


def evaluate_freshness(
    manifest: Mapping[str, Any] | Any,
    *,
    project_id: str,
    run_id: str,
    current_items: Iterable[EvidenceItem],
) -> FreshnessResult:
    """Compare current evidence to a manifest and propagate staleness downstream."""

    issues, records = _validate_manifest(manifest)
    states = {identity: "fresh" for identity in records}
    global_mismatch = False
    if isinstance(manifest, Mapping) and manifest.get("project_id") != project_id:
        issues.append(_issue("evidence-project-mismatch", "manifest belongs to another project"))
        global_mismatch = True
    if isinstance(manifest, Mapping) and manifest.get("run_id") != run_id:
        issues.append(_issue("evidence-run-mismatch", "manifest belongs to another run"))
        global_mismatch = True

    current: dict[str, EvidenceItem] = {}
    for item in current_items:
        if item.identity in current:
            issues.append(_issue(
                "evidence-duplicate-identity",
                f"current evidence identity appears more than once: {item.identity}",
                item.identity,
            ))
            states[item.identity] = "stale"
            continue
        current[item.identity] = item

    if global_mismatch:
        states = {identity: "stale" for identity in records}
    for identity, record in records.items():
        item = current.get(identity)
        if item is None:
            states[identity] = "stale"
            issues.append(_issue(
                "evidence-missing-current-item",
                "required current evidence is missing",
                identity,
            ))
            continue
        try:
            semantic_digest = canonical_digest(item.semantic)
            content_digest = _content_digest(item.content)
        except (OSError, TypeError, ValueError) as exc:
            states[identity] = "stale"
            issues.append(_issue("evidence-current-item-error", str(exc), identity))
            continue
        if semantic_digest != record.get("canonical_sha256"):
            states[identity] = "stale"
            issues.append(_issue(
                "evidence-canonical-digest-mismatch",
                "current semantic evidence does not match the manifest",
                identity,
            ))
        if content_digest != record.get("byte_sha256"):
            states[identity] = "stale"
            issues.append(_issue(
                "evidence-byte-digest-mismatch",
                "current evidence bytes do not match the manifest",
                identity,
            ))

    # Structural manifest errors make their affected records stale.  Unknown
    # global versions cannot be interpreted safely, so no record is reusable.
    global_codes = {
        "evidence-invalid-manifest",
        "evidence-unknown-manifest-version",
        "evidence-unknown-canonicalization-version",
        "evidence-invalid-records",
        "evidence-dependency-cycle",
    }
    if any(item["code"] in global_codes for item in issues):
        states = {identity: "stale" for identity in records}
    else:
        for issue in issues:
            identity = issue.get("identity")
            if identity in states:
                states[identity] = "stale"

    changed = True
    while changed:
        changed = False
        for identity, record in records.items():
            dependencies = record.get("depends_on")
            if not isinstance(dependencies, list):
                continue
            if states.get(identity) == "fresh" and any(
                states.get(dependency, "stale") == "stale" for dependency in dependencies
            ):
                states[identity] = "stale"
                changed = True
    return FreshnessResult(states=states, issues=tuple(issues))


def write_manifest_atomic(path: Path, manifest: Mapping[str, Any]) -> None:
    """Validate and atomically replace a JSON manifest on the same filesystem."""

    issues, _ = _validate_manifest(manifest)
    if issues:
        rendered = "; ".join(f"{item['code']}: {item['message']}" for item in issues)
        raise ValueError(rendered)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
