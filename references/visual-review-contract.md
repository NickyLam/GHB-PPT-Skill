# Optional visual-review adapter contract

This document defines `ghb.visual-review-request.v1`,
`ghb.visual-review-response.v1`, and the persisted
`ghb.visual-review-report.v1` projection. The adapter is optional and
provider-neutral. Deterministic SVG/PPTX validation remains authoritative.

## Trust boundary

- With no trusted adapter registration, review is `skipped` and no child
  process starts.
- Registration is accepted only as an explicit operator/CLI `AdapterConfig`.
  A project file cannot select an executable, launcher, capability, credential,
  model, or destination.
- A direct adapter is trusted same-user executable code. This mechanism does
  **not** claim to isolate its filesystem or network access.
- Untrusted code requires an operator-configured launcher explicitly declared
  to provide OS sandboxing. Merely starting a subprocess is not a sandbox.
- Adapter and launcher paths resolve to executable canonical regular files.
  Symlinks, directories, project-local mutable shims, and missing executables
  are rejected before launch. The executable byte digest is request-bound.

## Request envelope

The core copies approved, regular, non-symlink PNGs into a new dedicated
temporary workspace. It verifies the source digest, decoded PNG type,
dimensions, per-image size, aggregate size, ordered slide membership, and run
identity before copying. The adapter receives only:

- request, policy, and run schema identities;
- registered capability, model ID, tool-contract ID, and executable digest;
- stable slide ID and role;
- a workspace-relative snapshot name, byte digest, size, and dimensions;
- projected deterministic findings with stable code, severity, slide identity,
  evidence, expectation, and suggested action;
- deterministic-finding digest and deterministic status;
- renderer/font limitations;
- digest-bound disclosure metadata when remote review is authorized.

The canonical request digest binds schema, policy, page order and membership,
image bytes, deterministic findings, adapter registration, model, tool
contract, capability, font limitations, and disclosure authorization. A
response must echo this digest, run ID, and model ID.

## Remote disclosure and credentials

A `remote` adapter cannot launch without a separate `RemoteAuthorization`
naming provider, destination, retention, and the exact ordered slide IDs. The
persisted provenance contains those non-secret fields and their authorization
digest.

Credential configuration contains environment-variable **names only**. Names
come from trusted operator configuration; values are resolved from the local
environment immediately before launch. Project JSON, argv metadata, requests,
reports, and logs never accept or store credential values. Persisted provenance
records only `{name, present}`. An adapter response that echoes a resolved
secret is discarded.

## Process and resource limits

The adapter runs with an argv array, `shell=False`, a new process group, its
temporary workspace as cwd, and a minimal environment: locale, temporary
directory, and explicitly registered credential variables. The operation uses
one wall-clock deadline covering stdin, execution, stdout, and stderr.

Nonblocking streaming enforces stdout/stderr byte ceilings while data is in
flight. On timeout, overflow, exit, or validation failure, the process group is
terminated to clean up descendants. There is no automatic retry. Request and
response byte size, JSON depth, aggregate item count, finding count, string
length, image bytes, and dimensions are bounded.

## Response and persisted projection

Responses contain exactly:

- schema, request digest, run ID, model ID, and categorical outcome;
- up to 100 per-slide findings;
- one bounded adapter-version metadata field.

Each finding has a stable code, approved slide ID, supported dimension,
`reviewed|limited|unavailable` reviewability, advisory severity, normalized
slide rectangle, evidence text, and suggested action. Unknown fields,
fabricated slides, non-advisory severity, invalid coordinates, HTML, terminal
controls, Markdown links, URIs, traversal/path content, tool calls, and action
objects are rejected.

Only the validated projection is written atomically. Raw stdout/stderr, rejected
JSON, credentials, snapshot paths, and malicious strings are never persisted.
Protected evidence, deck, report, adapter, or explicitly supplied artifacts are
digested before and after execution; modification or deletion yields
`protected-artifact-modified` and prevents completion.

## Outcome semantics

- `skipped`: no adapter registration; no process was attempted.
- `passed`, `needs-revision`, or `limited`: schema-valid advisory model result.
- `error`: bounded execution, integrity, or response failure.

Model outcome never changes deterministic status. If deterministic status is
`failed`, completion remains failed even if the model says `passed`. When the
target font is missing, typography and CJK reviewability are forced to
`limited`; supported geometry dimensions may still be reviewed.

## Integration boundary

This module defines the U4 adapter and evidence lifecycle only. Attaching it to
the unified `build`/`report` CLI is U10. Default offline builds have no adapter
or network dependency.
