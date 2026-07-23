from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.validate_project_contract import validate_project_contract
from scripts.workflow_profiles import (
    GENERATED_ORIGIN,
    WorkflowProfileError,
    materialize_standard_contract,
    seed_simplified_contract,
)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_confirmed_standard(project: Path) -> None:
    project.mkdir()
    (project / "sources").mkdir()
    (project / "svg_output").mkdir()
    (project / "sources" / "source.md").write_text("# 来源\n- 事实 A", encoding="utf-8")
    (project / "svg_output" / "01.svg").write_text(
        '<svg viewBox="0 0 1280 720"><g id="bg"/><g data-layout="editorial"/></svg>',
        encoding="utf-8",
    )
    _write(project / "brief.json", {
        "schema": "ghb.brief.v1",
        "status": "confirmed",
        "confirmation_source": "user",
        "confirmed_at": "2026-07-22T00:00:00Z",
        "audience": "技术团队",
        "purpose": "内部分享",
        "page_count": "1",
        "mode": "briefing",
        "visual_style": "professional-modern",
        "assets": {"image_source": "none", "icon_set": "none"},
    })
    _write(project / "deck_plan.json", {
        "schema": "ghb.deck-plan.v1",
        "story": {"opening": "问题", "development": "方案", "ending": "行动"},
        "style": {"tone": "专业", "density": "balanced", "variation": "high"},
        "slides": [{
            "page": 1,
            "type": "summary",
            "message": "事实 A 是核心结论",
            "layout": "editorial",
            "source_refs": ["sources/source.md#来源"],
        }],
    })


def test_standard_init_contract_contains_only_two_author_inputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        seed_simplified_contract(project)
        assert (project / "brief.json").is_file()
        assert (project / "deck_plan.json").is_file()
        assert not (project / "confirmation.json").exists()
        assert not (project / "visual_profile.json").exists()


def test_standard_projection_builds_legacy_compatibility_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        written = materialize_standard_contract(project)
        assert {path.name for path in written} >= {
            "confirmation.json", "content_model.json", "layout_plan.json",
            "design_spec.md", "spec_lock.md",
        }
        confirmation = json.loads((project / "confirmation.json").read_text(encoding="utf-8"))
        assert confirmation["origin"] == GENERATED_ORIGIN
        assert confirmation["status"] == "confirmed"
        assert confirmation["decisions"]["outline"][0]["title"] == "事实 A 是核心结论"
        issues = validate_project_contract(project, workflow_mode="standard")
        assert issues == []


def test_standard_consulting_profile_is_opt_in_and_projected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["style"]["content_profile"] = "consulting-evidence-cn-v1"
        plan["slides"][0]["consulting_content"] = {
            "claim_type": "fact",
            "evidence": [{
                "label": "采用率",
                "value": "88%",
                "source_ref": "sources/source.md#来源",
            }],
            "so_what": {
                "type": "inference",
                "text": "下一步应关注规模化条件。",
            },
        }
        _write(plan_path, plan)

        materialize_standard_contract(project)

        layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        assert layout[0]["content_profile"] == "consulting-evidence-cn-v1"
        assert layout[0]["consulting_content"] == plan["slides"][0]["consulting_content"]
        design = (project / "design_spec.md").read_text(encoding="utf-8")
        assert "Content profile: consulting-evidence-cn-v1" in design
        lock = (project / "spec_lock.md").read_text(encoding="utf-8")
        assert "content_profile" not in lock


def test_standard_consulting_research_visual_profile_is_opt_in_and_projected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["style"]["visual_profile"] = "consulting-research-cn-v1"
        _write(plan_path, plan)
        brief_path = project / "brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief["mode"] = "narrative"
        _write(brief_path, brief)

        materialize_standard_contract(project)

        layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        assert layout[0]["visual_profile"] == "consulting-research-cn-v1"
        confirmation = json.loads((project / "confirmation.json").read_text(encoding="utf-8"))
        assert confirmation["decisions"]["visual_profile"] == "consulting-research-cn-v1"
        design = (project / "design_spec.md").read_text(encoding="utf-8")
        assert "Visual profile: consulting-research-cn-v1" in design
        lock = (project / "spec_lock.md").read_text(encoding="utf-8")
        assert "- mode: narrative" in lock
        assert "## visual_profile" in lock
        assert "preserve the GHB logo" in lock
        assert "section_label: required id='template-section-label'" in lock
        assert "font_family: 'KaiTi'" in lock
        assert "right edge flush with x=1280" in lock
        assert "full-canvas white overlays" in lock
        assert "#00A6E8" in lock


def test_standard_research_visual_profile_rejects_unknown_value() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["style"]["visual_profile"] = "unknown-visual-profile"
        _write(plan_path, plan)

        try:
            materialize_standard_contract(project)
        except WorkflowProfileError as exc:
            assert "unsupported visual_profile" in str(exc)
        else:
            raise AssertionError("unknown visual_profile must fail before projection")


def test_standard_default_projection_does_not_emit_consulting_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)

        materialize_standard_contract(project)

        layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        assert "content_profile" not in layout[0]
        assert "consulting_content" not in layout[0]
        assert "visual_profile" not in layout[0]
        design = (project / "design_spec.md").read_text(encoding="utf-8")
        assert "Content profile:" not in design
        assert "Visual profile:" not in design


def test_standard_projection_preserves_timeline_order_signal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["slides"][0]["layout"] = "timeline"
        plan["slides"][0]["order_signal"] = "next quarter → next 12 months → capital cycle"
        _write(plan_path, plan)

        materialize_standard_contract(project)

        layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        assert layout[0]["order_signal"] == plan["slides"][0]["order_signal"]


def test_standard_consulting_profile_rejects_unknown_profile_and_unmapped_fact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["style"]["content_profile"] = "unrecognized-profile"
        _write(plan_path, plan)

        try:
            materialize_standard_contract(project)
        except WorkflowProfileError as exc:
            assert "unsupported content_profile" in str(exc)
        else:
            raise AssertionError("unknown content profile must fail before projection")

        plan["style"]["content_profile"] = "consulting-evidence-cn-v1"
        plan["slides"][0]["consulting_content"] = {
            "claim_type": "fact",
            "evidence": [{
                "label": "采用率",
                "value": "88%",
                "source_ref": "sources/source.md#未映射",
            }],
        }
        _write(plan_path, plan)

        try:
            materialize_standard_contract(project)
        except WorkflowProfileError as exc:
            assert "must match one source_refs entry" in str(exc)
        else:
            raise AssertionError("fact evidence must be traceable to source_refs")


def test_standard_consulting_content_requires_profile_and_fact_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["slides"][0]["consulting_content"] = {"claim_type": "fact", "evidence": []}
        _write(plan_path, plan)

        try:
            materialize_standard_contract(project)
        except WorkflowProfileError as exc:
            assert "requires style.content_profile" in str(exc)
        else:
            raise AssertionError("consulting_content must remain opt-in")

        plan["style"]["content_profile"] = "consulting-evidence-cn-v1"
        _write(plan_path, plan)

        try:
            materialize_standard_contract(project)
        except WorkflowProfileError as exc:
            assert "requires at least one evidence item" in str(exc)
        else:
            raise AssertionError("fact consulting_content must include evidence")


def test_standard_projection_refreshes_when_deck_plan_changes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        materialize_standard_contract(project)
        plan_path = project / "deck_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["slides"][0]["message"] = "更新后的结论"
        _write(plan_path, plan)
        materialize_standard_contract(project)
        layout = json.loads((project / "layout_plan.json").read_text(encoding="utf-8"))
        assert layout[0]["key_message"] == "更新后的结论"


def test_standard_projection_refreshes_generated_design_but_preserves_authored_design() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        _seed_confirmed_standard(project)
        materialize_standard_contract(project)
        brief_path = project / "brief.json"
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief["visual_style"] = "editorial-bold"
        _write(brief_path, brief)
        materialize_standard_contract(project)
        design = project / "design_spec.md"
        assert "editorial-bold" in design.read_text(encoding="utf-8")

        design.write_text("# Human authored design\n", encoding="utf-8")
        brief["visual_style"] = "should-not-overwrite"
        _write(brief_path, brief)
        materialize_standard_contract(project)
        assert design.read_text(encoding="utf-8") == "# Human authored design\n"


def test_quick_contract_requires_only_source_and_authored_svg() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "sources").mkdir()
        (project / "svg_output").mkdir()
        (project / "sources" / "source.md").write_text("source", encoding="utf-8")
        (project / "svg_output" / "01.svg").write_text("<svg/>", encoding="utf-8")
        assert validate_project_contract(project, workflow_mode="quick") == []
