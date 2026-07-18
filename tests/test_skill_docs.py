from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_top_level_workflow_names_visual_contract_review_and_evidence():
    skill = _read("SKILL.md")
    readme = _read("README.md")

    for document in (skill, readme):
        assert "visual_profile.json" in document
        assert "page_schema" in document
        assert "visual-review.json" in document
        assert "evidence-manifest.json" in document
        assert "--review" in document

    assert "review" in readme
    assert "可选" in skill
    assert "Source Han Sans SC" in skill
    assert "Source Han Sans SC" in readme


def test_authoring_docs_require_semantic_focal_coherence():
    workflow = _read("references/authoring-workflow.md")
    catalog = _read("references/svg-layout-catalog.md")
    contract = _read("references/project-contract.md")

    for document in (workflow, catalog, contract):
        assert "density is not emphasis" in document.lower()
        assert "key_message" in document
        assert "focal_target" in document


def test_recovery_docs_separate_deterministic_optional_and_human_review():
    recovery = _read("references/quality-and-recovery.md")
    review_contract = _read("references/visual-review-contract.md")

    assert "skipped" in recovery
    assert "unavailable" in recovery
    assert "needs-revision" in recovery
    assert "limited" in recovery
    assert "error" in recovery
    assert "completion_status" in recovery
    assert "人工最终批准" in recovery
    assert "fresh" in recovery
    assert "build --review" in review_contract
    assert "review" in review_contract


def test_release_and_semantic_geometry_contracts_are_documented():
    skill = _read("SKILL.md")
    readme = _read("README.md")
    visual = _read("references/visual-quality-rules.md")
    recovery = _read("references/quality-and-recovery.md")

    for document in (skill, readme, recovery):
        assert "--quality-policy" in document
        assert "--target-renderer" in document
        assert "warning-waivers" in document
    for token in (
        "data-flow-node",
        "data-flow-from",
        "data-component",
        "data-component-slot",
        "header-safe-zone-collision",
    ):
        assert token in visual
