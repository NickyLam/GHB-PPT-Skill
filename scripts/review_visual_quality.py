#!/usr/bin/env python3
"""Bounded provider-neutral adapter for optional advisory visual review."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence

from PIL import Image


REQUEST_SCHEMA = "ghb.visual-review-request.v1"
RESPONSE_SCHEMA = "ghb.visual-review-response.v1"
REPORT_SCHEMA = "ghb.visual-review-report.v1"
POLICY_SCHEMA = "ghb.visual-review-policy.v1"

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AGGREGATE_IMAGE_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BYTES = 72 * 1024 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
MAX_STDERR_BYTES = 32 * 1024
MAX_FINDINGS = 100
MAX_STRING = 4096
MAX_DEPTH = 10
MAX_CONTAINER_ITEMS = 5000
DIMENSIONS = {"hierarchy", "spacing", "typography", "cjk", "geometry", "composition"}
OUTCOMES = {"passed", "needs-revision", "limited", "unavailable"}
REVIEWABILITY = {"reviewed", "limited", "unavailable"}
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
_SAFE_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SENSITIVE_ARGUMENT = re.compile(r"(?:token|secret|password|credential|api[-_]?key)", re.I)
_ACTIVE_TEXT = re.compile(
    r"(?:[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|<[^>]+>|\[[^\]]+\]\([^)]+\)|(?:https?|file)://|(?:^|[\\/])\.\.(?:[\\/]|$)|(?:^|\s)[A-Za-z0-9_.-]+[\\/][A-Za-z0-9_.-]+(?:\s|$))",
    re.IGNORECASE,
)


class ReviewContractError(ValueError):
    """The request or response violates the versioned adapter contract."""


class ReviewSecurityError(ReviewContractError):
    """Trusted configuration, executable, evidence, or disclosure is unsafe."""


class _ExecutionFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AdapterConfig:
    """Trusted operator-local adapter registration; never load this from a project."""

    executable: Path
    capability: str
    model_id: str
    tool_contract: str
    trusted_direct: bool = True
    launcher: tuple[str, ...] = ()
    launcher_supplies_os_sandbox: bool = False
    credential_env_names: tuple[str, ...] = ()
    deadline_seconds: float = 30.0
    max_stdout_bytes: int = MAX_RESPONSE_BYTES
    max_stderr_bytes: int = MAX_STDERR_BYTES


@dataclass(frozen=True)
class RemoteAuthorization:
    provider: str
    destination: str
    retention: str
    slide_ids: tuple[str, ...]


@dataclass(frozen=True)
class PageEvidence:
    slide_id: str
    role: str
    image_path: Path
    width: int
    height: int
    run_id: str
    sha256: str
    context: Mapping[str, Any] | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_within(path: Path, parent: Path) -> bool:
    return path.is_relative_to(parent)


def _regular_file(path: Path, *, label: str, executable: bool = False) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise ReviewSecurityError(f"{label} is unavailable: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ReviewSecurityError(f"{label} must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ReviewSecurityError(f"{label} must be a regular file")
    resolved = candidate.resolve(strict=True)
    if executable and not os.access(resolved, os.X_OK):
        raise ReviewSecurityError(f"{label} is not executable")
    return resolved


def _validate_text(value: Any, *, label: str, maximum: int = MAX_STRING) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ReviewContractError(f"{label} must be a non-empty string up to {maximum} characters")
    if _ACTIVE_TEXT.search(value) or Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ReviewContractError(f"{label} contains active content or a path")
    return value


def is_passive_review_text(value: Any, *, maximum: int = MAX_STRING) -> bool:
    """Return whether untrusted review text is bounded and non-operative."""

    try:
        _validate_text(value, label="review text", maximum=maximum)
    except ReviewContractError:
        return False
    return True


def _bounded_json(value: Any, *, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    if depth > MAX_DEPTH:
        raise ReviewContractError("JSON nesting exceeds the contract depth limit")
    counter[0] += 1
    if counter[0] > MAX_CONTAINER_ITEMS:
        raise ReviewContractError("JSON aggregate item count exceeds the contract limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise ReviewContractError("JSON object keys must be bounded strings")
            _bounded_json(item, depth=depth + 1, counter=counter)
    elif isinstance(value, list):
        for item in value:
            _bounded_json(item, depth=depth + 1, counter=counter)
    elif isinstance(value, str):
        if len(value) > MAX_STRING:
            raise ReviewContractError("JSON string exceeds the contract length limit")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ReviewContractError("JSON contains a non-finite number")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ReviewContractError("JSON contains an unsupported value type")


def _validate_config(config: AdapterConfig, project_root: Path) -> tuple[Path, list[str]]:
    if config.capability not in {"local", "remote"}:
        raise ReviewContractError("adapter capability must be local or remote")
    _validate_text(config.model_id, label="model_id", maximum=256)
    _validate_text(config.tool_contract, label="tool_contract", maximum=256)
    if not 0.05 <= config.deadline_seconds <= 300:
        raise ReviewContractError("deadline_seconds must be between 0.05 and 300")
    if not 1 <= config.max_stdout_bytes <= MAX_RESPONSE_BYTES:
        raise ReviewContractError("max_stdout_bytes exceeds policy")
    if not 1 <= config.max_stderr_bytes <= MAX_STDERR_BYTES:
        raise ReviewContractError("max_stderr_bytes exceeds policy")
    executable = _regular_file(config.executable, label="adapter executable", executable=True)
    if _is_within(executable, project_root):
        raise ReviewSecurityError("adapter executable must not be project-local mutable code")
    command: list[str]
    if config.trusted_direct:
        if config.launcher:
            raise ReviewSecurityError("trusted direct adapter must not also configure a launcher")
        command = [str(executable)]
    else:
        if not config.launcher or not config.launcher_supplies_os_sandbox:
            raise ReviewSecurityError(
                "untrusted adapter requires an explicitly configured OS-sandbox launcher"
            )
        launcher = _regular_file(Path(config.launcher[0]), label="sandbox launcher", executable=True)
        if _is_within(launcher, project_root):
            raise ReviewSecurityError("sandbox launcher must not be project-local mutable code")
        args = []
        for value in config.launcher[1:]:
            if _SENSITIVE_ARGUMENT.search(value):
                raise ReviewSecurityError("launcher arguments must not contain credential material")
            args.append(_validate_text(value, label="launcher argument", maximum=512))
        command = [str(launcher), *args, str(executable)]
    for name in config.credential_env_names:
        if not _SAFE_ENV_NAME.fullmatch(name):
            raise ReviewSecurityError("credential configuration accepts variable names only")
    if len(set(config.credential_env_names)) != len(config.credential_env_names):
        raise ReviewSecurityError("credential environment names must be unique")
    return executable, command


def _reject_project_adapter_config(project_config: Mapping[str, Any] | None) -> None:
    if not project_config:
        return
    raise ReviewSecurityError("project content cannot select adapters or provide credentials")


def _validate_authorization(
    config: AdapterConfig,
    authorization: RemoteAuthorization | None,
    slide_ids: tuple[str, ...],
) -> dict[str, Any] | None:
    if config.capability == "local":
        if authorization is not None:
            raise ReviewSecurityError("local adapter must not carry remote disclosure authorization")
        return None
    if authorization is None:
        raise ReviewSecurityError("remote adapter requires separate disclosure authorization")
    for label, value in (
        ("provider", authorization.provider),
        ("destination", authorization.destination),
        ("retention", authorization.retention),
    ):
        _validate_text(value, label=f"authorization {label}", maximum=512)
    if tuple(authorization.slide_ids) != slide_ids:
        raise ReviewSecurityError("remote authorization must bind exact ordered slide membership")
    payload = {
        "provider": authorization.provider,
        "destination": authorization.destination,
        "retention": authorization.retention,
        "slide_ids": list(slide_ids),
    }
    return {**payload, "authorization_digest": _canonical_digest(payload)}


def _snapshot_pages(
    pages: Sequence[PageEvidence],
    *,
    workspace: Path,
    run_id: str,
    approved_slide_ids: set[str] | None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    if not pages:
        raise ReviewContractError("review requires at least one page image")
    slide_ids = [page.slide_id for page in pages]
    if len(slide_ids) != len(set(slide_ids)):
        raise ReviewContractError("page slide IDs must be unique")
    if approved_slide_ids is not None and set(slide_ids) != set(approved_slide_ids):
        raise ReviewContractError("page membership does not match the approved evidence envelope")
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir()
    aggregate = 0
    request_pages: list[dict[str, Any]] = []
    protected: list[Path] = []
    for index, page in enumerate(pages, 1):
        _validate_text(page.slide_id, label="slide_id", maximum=128)
        _validate_text(page.role, label="page role", maximum=64)
        if page.run_id != run_id:
            raise ReviewContractError("page evidence belongs to another run")
        source = _regular_file(page.image_path, label=f"image for {page.slide_id}")
        if source.suffix.lower() != ".png":
            raise ReviewContractError("only bounded PNG evidence is supported")
        size = source.stat().st_size
        aggregate += size
        if size > MAX_IMAGE_BYTES or aggregate > MAX_AGGREGATE_IMAGE_BYTES:
            raise ReviewContractError("image evidence exceeds the byte budget")
        digest = _sha256(source)
        if digest != page.sha256:
            raise ReviewContractError("page image digest does not match its evidence envelope")
        try:
            with Image.open(source) as image:
                actual_width, actual_height = image.size
                image_format = image.format
                image.verify()
        except OSError as exc:
            raise ReviewContractError(f"invalid PNG evidence: {exc}") from exc
        if image_format != "PNG" or (actual_width, actual_height) != (page.width, page.height):
            raise ReviewContractError("image type or dimensions do not match the evidence envelope")
        if not 1 <= page.width <= 8192 or not 1 <= page.height <= 8192:
            raise ReviewContractError("image dimensions exceed the review contract")
        destination = evidence_dir / f"{index:03d}.png"
        shutil.copyfile(source, destination, follow_symlinks=False)
        if _sha256(destination) != digest:
            raise ReviewSecurityError("evidence snapshot digest mismatch")
        request_page = {
                "slide_id": page.slide_id,
                "role": page.role,
                "image": {
                    "workspace_path": f"evidence/{destination.name}",
                    "sha256": digest,
                    "bytes": size,
                    "width": page.width,
                    "height": page.height,
                },
            }
        if page.context is not None:
            _bounded_json(page.context)
            request_page["context"] = dict(page.context)
        request_pages.append(request_page)
        protected.append(source)
    return request_pages, protected


def _project_findings(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    allowed = {"code", "severity", "slide_id", "evidence", "expected", "suggested_action"}
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise ReviewContractError("deterministic findings must be objects")
        item = {key: finding[key] for key in allowed if key in finding}
        if not {"code", "severity", "slide_id"}.issubset(item):
            raise ReviewContractError("deterministic finding is missing stable identity fields")
        projected.append(item)
    _bounded_json(projected)
    return projected


def _protected_digests(paths: Sequence[Path]) -> dict[Path, str]:
    result: dict[Path, str] = {}
    for path in paths:
        resolved = _regular_file(path, label="protected artifact")
        result[resolved] = _sha256(resolved)
    return result


def _artifact_changed(path: Path, digest: str) -> bool:
    try:
        return _sha256(path) != digest
    except OSError:
        return True


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _invoke(
    command: list[str],
    payload: bytes,
    *,
    cwd: Path,
    env: dict[str, str],
    deadline_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[bytes, int]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    streams = (process.stdin, process.stdout, process.stderr)
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    offset = 0
    stdout = bytearray()
    stderr_size = 0
    deadline = time.monotonic() + deadline_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ExecutionFailure("adapter-timeout", "adapter exceeded the operation deadline")
            events = selector.select(min(remaining, 0.05))
            if not events and process.poll() is not None:
                if process.stdin in [key.fileobj for key in selector.get_map().values()]:
                    selector.unregister(process.stdin)
                    process.stdin.close()
                continue
            for key, _mask in events:
                stream = key.fileobj
                if key.data == "stdin":
                    try:
                        written = os.write(stream.fileno(), payload[offset : offset + 65536])
                    except BrokenPipeError:
                        written = 0
                        offset = len(payload)
                    offset += written
                    if offset >= len(payload):
                        selector.unregister(stream)
                        stream.close()
                else:
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    if key.data == "stdout":
                        stdout.extend(chunk)
                        if len(stdout) > stdout_limit:
                            raise _ExecutionFailure(
                                "adapter-output-limit", "adapter stdout exceeded the byte limit"
                            )
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > stderr_limit:
                            raise _ExecutionFailure(
                                "adapter-output-limit", "adapter stderr exceeded the byte limit"
                            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _ExecutionFailure("adapter-timeout", "adapter exceeded the operation deadline")
        returncode = process.wait(timeout=remaining)
        return bytes(stdout), returncode
    except subprocess.TimeoutExpired as exc:
        raise _ExecutionFailure("adapter-timeout", "adapter exceeded the operation deadline") from exc
    finally:
        selector.close()
        _kill_process_group(process)


def validate_adapter_response(
    response: Any,
    *,
    request_digest: str,
    run_id: str,
    model_id: str,
    slide_ids: set[str],
) -> dict[str, Any]:
    _bounded_json(response)
    if not isinstance(response, dict):
        raise ReviewContractError("adapter response must be a JSON object")
    allowed_top = {
        "schema", "request_digest", "run_id", "model_id", "outcome", "findings", "reviewer_metadata"
    }
    if set(response) != allowed_top:
        raise ReviewContractError("adapter response has missing or unknown top-level fields")
    if response["schema"] != RESPONSE_SCHEMA:
        raise ReviewContractError("adapter response schema is unsupported")
    if response["request_digest"] != request_digest or response["run_id"] != run_id:
        raise ReviewContractError("adapter response is stale or belongs to another run")
    if response["model_id"] != model_id:
        raise ReviewContractError("adapter response model identity does not match registration")
    if response["outcome"] not in OUTCOMES:
        raise ReviewContractError("adapter response outcome is invalid")
    metadata = response["reviewer_metadata"]
    if not isinstance(metadata, dict) or set(metadata) != {"adapter_version"}:
        raise ReviewContractError("reviewer metadata contains unknown fields")
    adapter_version = _validate_text(metadata["adapter_version"], label="adapter_version", maximum=256)
    findings = response["findings"]
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise ReviewContractError("adapter finding count exceeds the contract")
    allowed_finding = {
        "code", "slide_id", "dimension", "reviewability", "severity", "location", "evidence", "action"
    }
    allowed_location = {"x", "y", "width", "height"}
    projected = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != allowed_finding:
            raise ReviewContractError("adapter finding has missing or unknown fields")
        if not _SAFE_CODE.fullmatch(str(finding["code"])):
            raise ReviewContractError("adapter finding code is invalid")
        if finding["slide_id"] not in slide_ids:
            raise ReviewContractError("adapter finding refers to unapproved slide evidence")
        if finding["dimension"] not in DIMENSIONS:
            raise ReviewContractError("adapter finding dimension is invalid")
        if finding["reviewability"] not in REVIEWABILITY:
            raise ReviewContractError("adapter finding reviewability is invalid")
        if finding["severity"] != "advisory":
            raise ReviewContractError("model findings must remain advisory")
        location = finding["location"]
        if not isinstance(location, dict) or set(location) != allowed_location:
            raise ReviewContractError("adapter finding location must be normalized coordinates")
        if any(
            isinstance(location[key], bool)
            or not isinstance(location[key], (int, float))
            or not 0 <= float(location[key]) <= 1
            for key in allowed_location
        ):
            raise ReviewContractError("adapter coordinates must be finite values from zero to one")
        if float(location["x"]) + float(location["width"]) > 1.000001 or float(location["y"]) + float(location["height"]) > 1.000001:
            raise ReviewContractError("adapter finding location exceeds slide bounds")
        projected.append(
            {
                "code": finding["code"],
                "slide_id": finding["slide_id"],
                "dimension": finding["dimension"],
                "reviewability": finding["reviewability"],
                "severity": "advisory",
                "location": {key: round(float(location[key]), 6) for key in ("x", "y", "width", "height")},
                "evidence": _validate_text(finding["evidence"], label="finding evidence"),
                "action": _validate_text(finding["action"], label="finding action"),
            }
        )
    return {
        "outcome": response["outcome"],
        "findings": projected,
        "reviewer_metadata": {"adapter_version": adapter_version},
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
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


def _base_report(
    *,
    outcome: str,
    deterministic_status: str,
    target_font_available: bool,
) -> dict[str, Any]:
    dimensions = []
    for dimension in sorted(DIMENSIONS):
        limited = not target_font_available and dimension in {"typography", "cjk"}
        if outcome in {"skipped", "error", "unavailable"}:
            status = "unavailable"
        elif outcome == "limited" or limited:
            status = "limited"
        else:
            status = "reviewed"
        dimensions.append(
            {
                "dimension": dimension,
                "status": status,
                "limitations": ["target-font-missing"] if limited else [],
            }
        )
    return {
        "schema": REPORT_SCHEMA,
        "outcome": outcome,
        "deterministic_status": deterministic_status,
        "completion_status": "failed" if deterministic_status == "failed" else "completed",
        "freshness": "fresh",
        "findings": [],
        "dimension_reviewability": dimensions,
        "limitations": ["target-font-missing"] if not target_font_available else [],
        "provenance": {},
    }


def _error_report(
    code: str,
    *,
    deterministic_status: str,
    target_font_available: bool,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    report = _base_report(
        outcome="error",
        deterministic_status=deterministic_status,
        target_font_available=target_font_available,
    )
    report["completion_status"] = "failed"
    report["error"] = {"code": code, "message": "optional visual review did not complete"}
    report["provenance"] = provenance
    return report


def review_visual_quality(
    *,
    config: AdapterConfig | None,
    pages: Sequence[PageEvidence],
    project_root: Path,
    run_id: str,
    deterministic_status: str,
    deterministic_findings: Sequence[Mapping[str, Any]],
    target_font_available: bool,
    approved_slide_ids: set[str] | None = None,
    protected_paths: Sequence[Path] = (),
    remote_authorization: RemoteAuthorization | None = None,
    project_config: Mapping[str, Any] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run one optional review with a trusted registration and persist only its projection."""

    project_root = project_root.resolve()
    _reject_project_adapter_config(project_config)
    if deterministic_status not in {"passed", "failed"}:
        raise ReviewContractError("deterministic_status must be passed or failed")
    if config is None:
        report = _base_report(
            outcome="skipped",
            deterministic_status=deterministic_status,
            target_font_available=target_font_available,
        )
        report["completion_status"] = "failed" if deterministic_status == "failed" else "skipped"
        report["provenance"] = {"adapter": "absent", "credentials": [], "disclosure": None}
        if output_path is not None:
            _write_json_atomic(output_path, report)
        return report

    executable, command = _validate_config(config, project_root)
    command_artifacts = [executable]
    if not config.trusted_direct:
        command_artifacts.append(Path(command[0]))
    command_digests = {path: _sha256(path) for path in command_artifacts}
    slide_ids = tuple(page.slide_id for page in pages)
    disclosure = _validate_authorization(config, remote_authorization, slide_ids)
    credentials = [
        {"name": name, "present": name in os.environ}
        for name in config.credential_env_names
    ]
    provenance = {
        "adapter_sha256": command_digests[executable],
        "launcher_sha256": (
            command_digests[Path(command[0])] if not config.trusted_direct else None
        ),
        "capability": config.capability,
        "model_id": config.model_id,
        "tool_contract": config.tool_contract,
        "credentials": credentials,
        "disclosure": disclosure,
        "direct_subprocess_isolation": "trusted-same-user",
    }
    with tempfile.TemporaryDirectory(prefix="ghb-visual-review-") as temporary:
        workspace = Path(temporary)
        request_pages, page_sources = _snapshot_pages(
            pages,
            workspace=workspace,
            run_id=run_id,
            approved_slide_ids=approved_slide_ids,
        )
        projected_findings = _project_findings(deterministic_findings)
        request_base = {
            "schema": REQUEST_SCHEMA,
            "policy_schema": POLICY_SCHEMA,
            "run_id": run_id,
            "adapter": {
                "capability": config.capability,
                "model_id": config.model_id,
                "tool_contract": config.tool_contract,
                "executable_sha256": provenance["adapter_sha256"],
            },
            "pages": request_pages,
            "deterministic": {
                "status": deterministic_status,
                "findings": projected_findings,
                "digest": _canonical_digest(projected_findings),
            },
            "renderer_limitations": {
                "target_font_available": target_font_available,
                "limited_dimensions": [] if target_font_available else ["typography", "cjk"],
            },
            "disclosure": disclosure,
        }
        request_digest = _canonical_digest(request_base)
        request = {**request_base, "request_digest": request_digest}
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise ReviewContractError("adapter request exceeds the aggregate byte limit")
        protected_candidates = [*page_sources, *protected_paths]
        if output_path is not None and output_path.exists():
            protected_candidates.append(output_path)
        protected = _protected_digests(protected_candidates)
        if any(_artifact_changed(path, digest) for path, digest in command_digests.items()):
            raise ReviewSecurityError("adapter or launcher changed before launch")
        protected.update(command_digests)
        child_env = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": str(workspace),
        }
        secret_values: list[bytes] = []
        for name in config.credential_env_names:
            value = os.environ.get(name)
            if value is not None:
                child_env[name] = value
                if value:
                    secret_values.append(value.encode("utf-8"))
        if any(secret in payload for secret in secret_values):
            raise ReviewSecurityError("credential value detected in adapter payload")
        if any(
            value and any(value in argument for argument in command)
            for name in config.credential_env_names
            if (value := os.environ.get(name)) is not None
        ):
            raise ReviewSecurityError("credential value must not appear in adapter argv")
        try:
            stdout, returncode = _invoke(
                command,
                payload,
                cwd=workspace,
                env=child_env,
                deadline_seconds=config.deadline_seconds,
                stdout_limit=config.max_stdout_bytes,
                stderr_limit=config.max_stderr_bytes,
            )
            changed = [
                str(path.name)
                for path, digest in protected.items()
                if _artifact_changed(path, digest)
            ]
            if changed:
                report = _error_report(
                    "protected-artifact-modified",
                    deterministic_status=deterministic_status,
                    target_font_available=target_font_available,
                    provenance=provenance,
                )
            elif returncode != 0:
                report = _error_report(
                    "adapter-nonzero-exit",
                    deterministic_status=deterministic_status,
                    target_font_available=target_font_available,
                    provenance=provenance,
                )
            elif any(secret in stdout for secret in secret_values):
                report = _error_report(
                    "adapter-secret-echo",
                    deterministic_status=deterministic_status,
                    target_font_available=target_font_available,
                    provenance=provenance,
                )
            else:
                if len(stdout) > MAX_RESPONSE_BYTES:
                    raise _ExecutionFailure("adapter-output-limit", "response exceeds policy")
                try:
                    response = json.loads(stdout.decode("utf-8"))
                    projection = validate_adapter_response(
                        response,
                        request_digest=request_digest,
                        run_id=run_id,
                        model_id=config.model_id,
                        slide_ids=set(slide_ids),
                    )
                except (UnicodeDecodeError, json.JSONDecodeError, ReviewContractError):
                    report = _error_report(
                        "adapter-response-invalid",
                        deterministic_status=deterministic_status,
                        target_font_available=target_font_available,
                        provenance=provenance,
                    )
                else:
                    report = _base_report(
                        outcome=projection["outcome"],
                        deterministic_status=deterministic_status,
                        target_font_available=target_font_available,
                    )
                    report["request_digest"] = request_digest
                    report["findings"] = projection["findings"]
                    dimension_status = {
                        item["dimension"]: item
                        for item in report["dimension_reviewability"]
                    }
                    if not target_font_available:
                        for finding in report["findings"]:
                            if finding["dimension"] in {"typography", "cjk"}:
                                finding["reviewability"] = "limited"
                    priority = {"reviewed": 0, "limited": 1, "unavailable": 2}
                    for finding in report["findings"]:
                        item = dimension_status[finding["dimension"]]
                        if priority[finding["reviewability"]] > priority[item["status"]]:
                            item["status"] = finding["reviewability"]
                    report["reviewer_metadata"] = projection["reviewer_metadata"]
                    report["provenance"] = provenance
        except _ExecutionFailure as exc:
            report = _error_report(
                exc.code,
                deterministic_status=deterministic_status,
                target_font_available=target_font_available,
                provenance=provenance,
            )
        finally:
            changed_after_failure = [
                str(path.name)
                for path, digest in protected.items()
                if _artifact_changed(path, digest)
            ]
        if changed_after_failure:
            report = _error_report(
                "protected-artifact-modified",
                deterministic_status=deterministic_status,
                target_font_available=target_font_available,
                provenance=provenance,
            )
    if output_path is not None:
        _write_json_atomic(output_path, report)
    return report


__all__ = [
    "AdapterConfig",
    "PageEvidence",
    "RemoteAuthorization",
    "ReviewContractError",
    "ReviewSecurityError",
    "is_passive_review_text",
    "review_visual_quality",
    "validate_adapter_response",
]
