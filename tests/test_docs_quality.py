from pathlib import Path
import re


ROOT = Path(".")
DOCS = ROOT / "project-docs"
ACTIVE_STAGE = DOCS / "03-stages" / "STAGE_10_GA4_MEASUREMENT_TOOLS.md"
ACTIVE_DOCS = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    DOCS / "README.md",
    DOCS / "00-governance" / "IMPLEMENTATION_SOURCE_OF_TRUTH.md",
    DOCS / "00-governance" / "CODE_BOUNDARIES.md",
    DOCS / "01-product" / "PROJECT_CHARTER.md",
    DOCS / "01-product" / "FUNCTIONAL_OUTLINE.md",
    DOCS / "02-architecture" / "AGENT_WORKFLOW.md",
    DOCS / "02-architecture" / "ARCHITECTURE.md",
    DOCS / "05-quality" / "RUNTIME_VERIFICATION.md",
    DOCS / "05-quality" / "QUALITY_EVIDENCE.md",
    ACTIVE_STAGE,
]
MOJIBAKE_MARKERS = ("\ufffd", "锟", "鍙", "璇")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_top_level_docs_are_utf8_and_not_mojibake() -> None:
    for path in [ROOT / "README.md", ROOT / "AGENTS.md", *DOCS.rglob("*.md")]:
        text = path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            assert marker not in text, path


def test_active_docs_have_status_headers() -> None:
    for path in ACTIVE_DOCS:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:18])
        assert "Status" in head, path
        assert "Document status" in head, path


def test_active_stage_is_consistent() -> None:
    truth = (DOCS / "00-governance" / "IMPLEMENTATION_SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    stage = ACTIVE_STAGE.read_text(encoding="utf-8")

    assert "Active Stage: Stage 10 - GA4 Measurement Tools" in truth
    assert "STAGE_10_GA4_MEASUREMENT_TOOLS.md" in truth
    assert "Current active stage: [03-stages/STAGE_10_GA4_MEASUREMENT_TOOLS.md]" in index
    assert "Stage status: active" in stage
    assert "Current Progress" in stage
    assert "Verification" in stage


def test_active_stage_links_resolve() -> None:
    missing: list[str] = []
    for path in ACTIVE_DOCS:
        text = path.read_text(encoding="utf-8")
        for target in LINK_PATTERN.findall(text):
            if target.startswith(("#", "http://", "https://")):
                continue
            target_path = target.split("#", 1)[0]
            resolved = (path.parent / target_path).resolve()
            if not resolved.exists():
                missing.append(f"{path}: {target}")
    assert not missing, missing


def test_agents_defines_the_react_boundary() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for marker in [
        "POST /api/agent/turn",
        "backend/agent/runtime.py",
        "tool_search",
        "execute_action",
        "execution_disabled_in_demo",
        "no separate intent router",
    ]:
        assert marker in text


def test_architecture_matches_current_files() -> None:
    workflow = (DOCS / "02-architecture" / "AGENT_WORKFLOW.md").read_text(encoding="utf-8")
    architecture = (DOCS / "02-architecture" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    combined = workflow + architecture

    for path in [
        "backend/agent/runtime.py",
        "backend/agent/tools.py",
        "backend/services/trace_service.py",
        "backend/routes/agent_routes.py",
    ]:
        assert path in combined
        assert Path(path).exists()

    for removed in [
        "backend/services/chat_workflow.py",
        "backend/services/llm_service.py",
        "backend/services/prompt_registry.py",
        "backend/route_handlers/chat.py",
    ]:
        assert not Path(removed).exists()

    assert "tool_search" in combined
    assert "defer_loading" in combined
    assert "meta_ads" in combined


def test_product_docs_keep_the_demo_scope() -> None:
    combined = "\n".join(
        (DOCS / "01-product" / name).read_text(encoding="utf-8")
        for name in ["PROJECT_CHARTER.md", "FUNCTIONAL_OUTLINE.md"]
    )
    assert "Meta" in combined
    assert "ReAct" in combined
    assert "execution_disabled_in_demo" in combined
    assert "Out Of Scope" in combined


def test_quality_evidence_records_real_openai_and_execution_boundary() -> None:
    text = (DOCS / "05-quality" / "QUALITY_EVIDENCE.md").read_text(encoding="utf-8")
    assert "verify_mcp_tool_agent.py" in text
    assert "meta_ads.ads_get_ad_accounts" in text
    assert "tool_search" in text
    assert "execution_disabled_in_demo" in text
    assert "Approval records a lifecycle event" in text


def test_documentation_index_points_to_active_guides() -> None:
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for name in ["AGENT_WORKFLOW.md", "ARCHITECTURE.md", "CODE_BOUNDARIES.md", "RUNTIME_VERIFICATION.md", "QUALITY_EVIDENCE.md"]:
        assert name in index


def test_active_documents_stay_lightweight() -> None:
    for path in ACTIVE_DOCS:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 400, path