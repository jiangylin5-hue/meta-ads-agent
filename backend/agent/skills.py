from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SKILL_ORDER = (
    "account_brief",
    "performance_diagnosis",
    "account_audit",
    "creative_diagnosis",
    "optimization_draft",
    "campaign_plan",
    "tracking_troubleshooting",
    "audience_audit",
    "catalog_health",
    "competitive_research",
    "experiment_design",
    "policy_preflight",
)
REQUIRED_FIELDS = (
    "id",
    "version",
    "status",
    "description",
    "when_to_use",
    "do_not_use",
    "advertiser_job",
    "required_inputs",
    "optional_inputs",
    "read_groups",
    "optional_read_groups",
    "draft_groups",
    "required_evidence",
    "output_contract",
    "hard_rules",
    "source_refs",
    "input_gates",
    "evidence_gates",
    "evidence_requirements",
)


class SkillCatalogError(ValueError):
    pass


class SkillCatalog:
    """Load project Skill folders without exposing arbitrary filesystem paths."""

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self.skills_dir = Path(skills_dir) if skills_dir else Path(__file__).resolve().parents[1] / "skills"
        self.tool_groups: dict[str, dict[str, list[str]]] = {}
        self.contracts: dict[str, dict[str, Any]] = {}
        self.skill_docs: dict[str, dict[str, Any]] = {}
        self.max_loaded_skills = 4
        self.max_loaded_references = 6
        self.max_reference_chars = 6000
        self._load()

    def _load(self) -> None:
        groups_path = self.skills_dir / "tool_groups.json"
        if not groups_path.is_file():
            raise SkillCatalogError(f"Skill tool groups are missing: {groups_path}")
        groups = json.loads(groups_path.read_text(encoding="utf-8"))
        self.tool_groups = {
            "read": {str(key): list(value) for key, value in (groups.get("read_groups") or {}).items()},
            "draft": {str(key): list(value) for key, value in (groups.get("draft_groups") or {}).items()},
        }
        self.max_loaded_skills = self._bounded_int(groups.get("max_loaded_skills"), 4, 1)
        self.max_loaded_references = self._bounded_int(groups.get("max_loaded_references"), 6, 1)
        self.max_reference_chars = self._bounded_int(groups.get("max_reference_chars"), 6000, 500)
        for skill_id in SKILL_ORDER:
            skill_dir = self.skills_dir / skill_id
            contract_path = skill_dir / "contract.json"
            skill_path = skill_dir / "SKILL.md"
            if not contract_path.is_file() or not skill_path.is_file():
                raise SkillCatalogError(f"Skill files are missing for {skill_id}")
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            missing = [field for field in REQUIRED_FIELDS if field not in contract]
            if missing:
                raise SkillCatalogError(f"{skill_id} is missing fields: {', '.join(missing)}")
            if contract.get("id") != skill_id:
                raise SkillCatalogError(f"{contract_path} has id {contract.get('id')!r}")
            for group in list(contract.get("read_groups", [])) + list(contract.get("optional_read_groups", [])):
                if group not in self.tool_groups["read"]:
                    raise SkillCatalogError(f"{skill_id} references unknown read group {group}")
            for group in contract.get("draft_groups", []):
                if group not in self.tool_groups["draft"]:
                    raise SkillCatalogError(f"{skill_id} references unknown draft group {group}")
            meta, body = _read_markdown(skill_path)
            if meta.get("name") != skill_id:
                raise SkillCatalogError(f"{skill_path} has name {meta.get('name')!r}")
            if not meta.get("description"):
                raise SkillCatalogError(f"{skill_path} is missing a description")
            references: dict[str, dict[str, str]] = {}
            ref_dir = skill_dir / "references"
            if ref_dir.is_dir():
                for ref_path in sorted(ref_dir.glob("*.md")):
                    ref_meta, ref_body = _read_markdown(ref_path)
                    ref_id = ref_path.stem
                    if ref_meta.get("name") and ref_meta["name"] != ref_id:
                        raise SkillCatalogError(f"{ref_path} has name {ref_meta['name']!r}")
                    references[ref_id] = {
                        "id": ref_id,
                        "description": str(ref_meta.get("description") or ref_id),
                        "body": ref_body.strip(),
                    }
            self.contracts[skill_id] = contract
            self.skill_docs[skill_id] = {
                "name": skill_id,
                "description": str(meta.get("description") or contract.get("description") or ""),
                "body": body.strip(),
                "references": references,
            }

    def catalog_entries(self) -> list[dict[str, str]]:
        return [
            {"id": skill_id, "description": str(self.skill_docs[skill_id].get("description") or "")}
            for skill_id in SKILL_ORDER
        ]

    def catalog_text(self) -> str:
        lines = [
            "Available project skills (closed menu). Call load_skill before Meta tools; load at most four skills.",
            "Choose by the task description, then use only the tool groups and references returned by load_skill.",
        ]
        lines.extend(f"- {entry['id']}: {entry['description']}" for entry in self.catalog_entries())
        return "\n".join(lines)

    def load(self, skill_id: str, available_tools: set[str] | None = None) -> dict[str, Any]:
        skill_id = str(skill_id or "").strip()
        contract = self.contracts.get(skill_id)
        doc = self.skill_docs.get(skill_id)
        if contract is None or doc is None:
            raise SkillCatalogError(f"Unknown skill: {skill_id}")
        read_tools = self._resolve("read", contract.get("read_groups", []), available_tools)
        optional_read_tools = self._resolve("read", contract.get("optional_read_groups", []), available_tools)
        draft_tools = self._resolve("draft", contract.get("draft_groups", []), available_tools)
        missing_tools = self._missing(contract, available_tools)
        allowed_tools = sorted(set(read_tools) | set(optional_read_tools) | set(draft_tools))
        references = [
            {"skill": skill_id, "id": ref_id, "description": str(ref.get("description") or ref_id)}
            for ref_id, ref in doc["references"].items()
        ]
        return {
            "name": skill_id,
            "version": str(contract.get("version") or ""),
            "description": str(doc["description"]),
            "advertiser_job": str((contract.get("advertiser_job") or {}).get("default") or "other"),
            "instructions": self._instructions(contract, doc, read_tools, optional_read_tools, draft_tools),
            "read_tools": read_tools,
            "optional_read_tools": optional_read_tools,
            "draft_tools": draft_tools,
            "missing_tools": missing_tools,
            "allowed_tools": allowed_tools,
            "references": references,
            "input_gates": dict(contract.get("input_gates") or {}),
            "evidence_gates": dict(contract.get("evidence_gates") or {}),
            "evidence_requirements": dict(contract.get("evidence_requirements") or {}),
            "output_contract": dict(contract.get("output_contract") or {}),
        }

    def read_reference(self, skill_id: str, reference_id: str) -> dict[str, Any]:
        skill_id = str(skill_id or "").strip()
        reference_id = str(reference_id or "").strip()
        doc = self.skill_docs.get(skill_id)
        if doc is None:
            raise SkillCatalogError(f"Unknown skill: {skill_id}")
        reference = doc["references"].get(reference_id)
        if reference is None:
            available = ", ".join(sorted(doc["references"])) or "none"
            raise SkillCatalogError(f"Unknown reference {reference_id!r} for {skill_id}. Available: {available}")
        content = str(reference.get("body") or "")
        truncated = len(content) > self.max_reference_chars
        return {
            "skill": skill_id,
            "reference": reference_id,
            "description": str(reference.get("description") or reference_id),
            "content": content[: self.max_reference_chars],
            "truncated": truncated,
            "chars": len(content),
        }

    def allowed_tools(self, loaded_skills: list[dict[str, Any]]) -> set[str]:
        allowed: set[str] = set()
        for item in loaded_skills:
            allowed.update(str(name) for name in item.get("allowed_tools", []))
        return allowed

    def advertiser_job(self, loaded_skills: list[dict[str, Any]]) -> str:
        for item in loaded_skills:
            job = str(item.get("advertiser_job") or "other")
            if job != "other":
                return job
        return "other"

    def _resolve(self, group_type: str, group_names: list[str], available_tools: set[str] | None) -> list[str]:
        names: list[str] = []
        groups = self.tool_groups[group_type]
        for group_name in group_names:
            for name in groups.get(group_name, []):
                if available_tools is None or name in available_tools:
                    names.append(str(name))
        return sorted(set(names))

    def _missing(self, contract: dict[str, Any], available_tools: set[str] | None) -> list[str]:
        if available_tools is None:
            return []
        configured: set[str] = set()
        for group_type, field in (("read", "read_groups"), ("read", "optional_read_groups"), ("draft", "draft_groups")):
            for group_name in contract.get(field, []):
                configured.update(self.tool_groups[group_type].get(group_name, []))
        return sorted(configured - available_tools)

    @staticmethod
    def _instructions(
        contract: dict[str, Any],
        doc: dict[str, Any],
        read_tools: list[str],
        optional_read_tools: list[str],
        draft_tools: list[str],
    ) -> str:
        references = doc.get("references") or {}
        ref_lines = [f"- {ref_id}: {ref.get('description') or ref_id}" for ref_id, ref in references.items()]
        lines = [
            str(doc.get("body") or "").strip(),
            "",
            "Read tools allowed for this skill: " + (", ".join(read_tools) if read_tools else "none"),
            "Optional read tools: " + (", ".join(optional_read_tools) if optional_read_tools else "none"),
            "Draft tools: " + (", ".join(draft_tools) if draft_tools else "none"),
            "Executable input gates: " + json.dumps(contract.get("input_gates") or {}, ensure_ascii=False),
            "Executable evidence gates: " + json.dumps(contract.get("evidence_gates") or {}, ensure_ascii=False),
            "Evidence requirements: " + json.dumps(contract.get("evidence_requirements") or {}, ensure_ascii=False),
            "Output contract: " + json.dumps(contract.get("output_contract") or {}, ensure_ascii=False),
            "Reference index (read only when needed with read_skill_reference):",
        ]
        lines.extend(ref_lines if ref_lines else ["- none"])
        lines.append("Call tool_search for selected tools before using them. Do not call tools outside the active skill groups.")
        return "\n".join(lines)

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default


def _read_markdown(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for raw_line in parts[1].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        meta[key.strip()] = str(value)
    return meta, parts[2].lstrip("\n")