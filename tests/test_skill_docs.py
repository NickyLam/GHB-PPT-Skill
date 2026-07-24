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


def test_layout_docs_make_builtin_diagrams_optional_and_diversity_non_blocking():
    skill = _read("SKILL.md")
    workflow = _read("references/authoring-workflow.md")
    catalog = _read("references/svg-layout-catalog.md")

    assert "禁止为了凑版式数量强套内置结构图" in skill
    assert "Built-in renderers are optional" in workflow
    assert "advisory review signal, not a build error" in catalog
    assert "editorial" in catalog
    assert "file_tree" in catalog


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


def test_consulting_content_profile_is_explicit_and_visual_style_stays_separate():
    skill = _read("SKILL.md")
    workflow_modes = _read("references/workflow-modes.md")
    profile = _read("references/content-styles/consulting-evidence-cn-v1.md")
    visual_profile = _read("references/visual-styles/consulting-research-cn-v1.md")

    for document in (skill, workflow_modes, profile):
        assert "consulting-evidence-cn-v1" in document
    assert "默认不启用" in skill
    assert "visual_style" in skill
    assert "结论" in profile
    assert "source_refs" in profile
    assert "consulting-research-cn-v1" in skill
    assert "visual_profile" in workflow_modes
    assert "默认不启用" in visual_profile
    assert "GHB" in visual_profile
    assert "template-section-label" in visual_profile
    assert "全画布白色覆盖层" in visual_profile
    assert "KaiTi" in visual_profile
    assert "font-resolution-report.json" in visual_profile
    assert "--consulting-font" in skill
    assert "--consulting-font" in visual_profile
