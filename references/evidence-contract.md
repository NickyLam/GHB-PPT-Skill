# Evidence manifest contract

The GHB evidence manifest is the single owner of canonical digests, byte
digests, dependency edges, evidence envelopes, and freshness decisions. A
consumer must use `scripts/evidence_manifest.py`; file existence, modification
time, or a checkpoint path is never evidence of freshness.

## Version and identity

V1 manifests use:

```json
{
  "schema": "ghb.evidence-manifest.v1",
  "canonicalization": "ghb.canonical-json.v1",
  "project_id": "logical-project-id",
  "run_id": "logical-run-id",
  "evidence": []
}
```

`project_id` and `run_id` are stable logical identities supplied by the trusted
caller. They are not filesystem paths. Freshness evaluation compares both
identities, so copying an envelope into another project or run does not make it
fresh. Unknown manifest or canonicalization versions fail closed.

## Canonical and byte digests

Each evidence record contains:

- `identity`: unique logical identity in this manifest;
- `kind`: provider-neutral evidence kind;
- `role`: `input` or immutable `envelope` snapshot;
- `depends_on`: identities whose freshness is required by this record;
- `canonical_sha256`: SHA-256 of semantic JSON under
  `ghb.canonical-json.v1`;
- `byte_sha256`: SHA-256 of exact artifact bytes, or `null` when the evidence
  has no byte artifact.

Canonical JSON recursively sorts object keys, uses compact UTF-8 JSON, and
rejects non-JSON values and non-finite numbers. Object key order therefore does
not affect the digest. Semantic schema, thresholds, policies, renderer/DPI/font
properties, tool or rule versions, adapter identity, disclosure policy, slide
membership, and review state must be included by the producing stage and do
affect the digest.

The following run-local metadata is excluded from canonical digests:

- timestamps (`timestamp`, `created_at`, `updated_at`, `generated_at`, and
  `completed_at`);
- run identifiers and directories (`run_id`, `run_dir`, `run_directory`, and
  `run_path`);
- output locations (`output_dir`, `output_directory`, and `output_path`);
- `absolute_path`, and any absolute POSIX or Windows path value.

Paths do not authenticate an artifact. When bytes matter, the caller supplies
the regular, non-symlink file or exact bytes and the manifest binds
`byte_sha256`. Relative membership such as `slide_id` or an allowlisted page
name remains semantic data and must not be hidden inside an excluded output
path.

## V1 dependency DAG

The built-in DAG is versioned in `DEFAULT_DEPENDENCY_DAG`:

```text
visual-profile ─┐
layout-plan ────┼─> svg-bundle -> pptx ──────────────┐
                │          │       │                 │
rule-contract ──┴──────────┴──────> deterministic-report
                                     │               │
render-environment -> render-evidence <──────────────┘
                              │      │
adapter-policy ───────────────┼──────┴─> adapter-review
                              │                │
                              └────────────────┴─> final-report
```

This gives every downstream stage an explicit invalidation path:

- profile or layout changes invalidate SVG, PPTX, deterministic, rendered,
  adapter-review, and final-report evidence;
- SVG byte changes invalidate PPTX and all of its downstream evidence;
- renderer, DPI, font inventory, or substitution changes invalidate rendered,
  adapter-review, and final-report evidence, but not deterministic evidence;
- rule-contract changes invalidate deterministic, adapter-review, and final
  reports;
- adapter identity, local/remote capability, authorization, credential-variable
  names/presence, retention, slide membership, and bounds belong in
  `adapter-policy`; a policy change invalidates adapter-review and final-report
  evidence;
- deterministic-report and adapter-review changes converge only in the final
  report. Model evidence never rewrites deterministic evidence.

The default offline path still creates an `adapter-review` envelope whose
semantic outcome is `skipped`. This keeps the DAG complete without invoking an
adapter. Outcomes (`passed`, `needs-revision`, `limited`, `unavailable`,
`skipped`, or `error`), freshness (`fresh` or `stale`), and reviewability
limitations remain separate fields in producer semantics.

## API and lifecycle

The intentionally small API is:

- `EvidenceItem`: current semantic data, optional bytes/path, and optional
  dependencies;
- `create_manifest(...)`: snapshot digests after validating the DAG;
- `evaluate_freshness(...)`: compare current evidence and propagate staleness
  only to declared downstream records;
- `canonical_digest(...)`: reusable canonical JSON digest;
- `write_manifest_atomic(...)`: validate, fsync, and atomically replace JSON.

`evaluate_freshness` returns per-identity states and structured issues. It does
not render, invoke a provider, repair evidence, mutate SVG/PPTX, or infer a
review result. Report composition can consume only a fully fresh result for the
evidence it claims.

## Stable failure codes

At minimum, callers should preserve these codes verbatim:

| Code | Meaning |
|---|---|
| `evidence-unknown-manifest-version` | Unsupported manifest schema |
| `evidence-unknown-canonicalization-version` | Unsupported digest rules |
| `evidence-duplicate-identity` | Duplicate manifest or current identity |
| `evidence-missing-dependency` | A declared dependency is absent |
| `evidence-dependency-mismatch` | A V1 built-in edge differs from the contract |
| `evidence-dependency-cycle` | Dependency graph is cyclic |
| `evidence-project-mismatch` | Manifest belongs to another project |
| `evidence-run-mismatch` | Manifest belongs to another run |
| `evidence-missing-current-item` | Required current evidence is absent |
| `evidence-canonical-digest-mismatch` | Semantic content changed |
| `evidence-byte-digest-mismatch` | Exact artifact bytes changed |

Malformed manifests, missing dependencies, cycles, identity mismatch, unreadable
or symlinked evidence, and digest mismatch fail visibly. They never degrade to a
passing, available, or fresh review state.

## Security boundary

The manifest authenticates the evidence supplied to it; it is not an OS
sandbox, signature system, or same-user process isolation boundary. Trusted
callers must provide logical identities and fresh regular files, keep credential
values out of semantic data, and protect the manifest and artifacts from
concurrent mutation. Untrusted adapters still require the separately configured
OS-sandboxed launcher described by the review-adapter contract. Persist only
bounded, schema-validated failure evidence—never raw malicious streams or
credential values.
