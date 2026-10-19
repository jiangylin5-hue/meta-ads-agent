from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent.skills import SKILL_ORDER, SkillCatalog, SkillCatalogError


SKILLS_DIR = Path("backend/skills")


def test_catalog_exposes_exactly_twelve_project_skills() -> None:
    catalog = SkillCatalog(SKILLS_DIR)
    entries = catalog.catalog_entries()

    assert [item["id"] for item in entries] == list(SKILL_ORDER)
    assert catalog.max_loaded_skills == 4
    assert catalog.max_loaded_references == 6
    catalog_text = catalog.catalog_text()
    assert all(item["id"] in catalog_text for item in entries)
    assert "Hard rules:" not in catalog_text


def test_performance_contract_resolves_read_groups_and_references() -> None:
    catalog = SkillCatalog(SKILLS_DIR)
    loaded = catalog.load("performance_diagnosis")

    assert loaded["advertiser_job"] == "explain_poor_results"
    assert "ads_get_ad_entities" in loaded["read_tools"]
    assert "ads_insights_performance_trend" in loaded["read_tools"]
    assert loaded["draft_tools"] == []
    assert {item["id"] for item in loaded["references"]} == {
        "diagnosis-order",
        "evaluation-level",
        "learning-and-marginal",
    }
    assert "Inspect next_actions" in loaded["instructions"]


def test_reference_body_is_loaded_on_demand_and_bounded() -> None:
    catalog = SkillCatalog(SKILLS_DIR)
    reference = catalog.read_reference("performance_diagnosis", "evaluation-level")

    assert reference["skill"] == "performance_diagnosis"
    assert reference["reference"] == "evaluation-level"
    assert "Campaign" in reference["content"]
    assert reference["truncated"] is False


def test_optimization_contract_resolves_draft_tools() -> None:
    catalog = SkillCatalog(SKILLS_DIR)
    loaded = catalog.load("optimization_draft")

    assert "ads_update_entity" in loaded["draft_tools"]
    assert "ads_create_creative" in loaded["draft_tools"]
    assert "ads_update_entity" in loaded["allowed_tools"]
    assert "Draft tools:" in loaded["instructions"]


def test_unknown_skill_and_reference_are_rejected() -> None:
    catalog = SkillCatalog(SKILLS_DIR)
    with pytest.raises(SkillCatalogError):
        catalog.load("not_a_skill")
    with pytest.raises(SkillCatalogError):
        catalog.read_reference("performance_diagnosis", "not_a_reference")


def test_all_skill_folders_have_contracts_skill_md_and_sources() -> None:
    for skill_id in SKILL_ORDER:
        skill_dir = SKILLS_DIR / skill_id
        contract = json.loads((skill_dir / "contract.json").read_text(encoding="utf-8"))
        assert (skill_dir / "SKILL.md").is_file(), skill_id
        assert (skill_dir / "references").is_dir(), skill_id
        assert contract["source_refs"], skill_id
        assert contract["input_gates"], skill_id
        assert "min_reads" in contract["evidence_gates"], skill_id
        assert "required_fields" in contract["evidence_requirements"], skill_id
        assert contract["required_evidence"], skill_id
        assert contract["hard_rules"], skill_id
        assert contract["output_contract"]["id"], skill_id