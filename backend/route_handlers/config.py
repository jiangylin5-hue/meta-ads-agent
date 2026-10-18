from typing import Any

from fastapi import APIRouter

from ..config import (
    active_llm_model,
    active_llm_provider,
    agent_max_steps,
    agent_turn_timeout_seconds,
    deepseek_api_key,
    env_file_status,
    llm_reasoning_effort,
    meta_draft_write_enabled,
    meta_live_write_enabled,
    openai_api_key,
    openai_model,
    openai_reasoning_effort,
    openai_timeout_seconds,
    reload_dotenv,
    secret_fingerprint,
)
from ..agent.skills import SKILL_ORDER
from ..integrations.meta_ads import MetaAdsProvider

router = APIRouter()

LOCAL_AGENT_TOOLS = ["ask_user", "load_skill", "read_skill_reference", "submit_result", "save_memory", "update_task"]


@router.get("/config")
def config() -> dict[str, Any]:
    return {
        "llm_provider": active_llm_provider(),
        "llm_reasoning_effort": llm_reasoning_effort(),
        "openai_env_configured": bool(openai_api_key().strip()),
        "deepseek_env_configured": bool(deepseek_api_key().strip()),
        "openai_key_fingerprint": secret_fingerprint(openai_api_key()),
        "default_model": active_llm_model(),
        "reasoning_effort": llm_reasoning_effort() or openai_reasoning_effort(),
        "openai_timeout_seconds": openai_timeout_seconds(),
        "meta_live_write_enabled": meta_live_write_enabled(),
        "meta_draft_write_enabled": meta_draft_write_enabled(),
        "env_file": env_file_status(),
        "runtime": {
            "name": "react",
            "max_steps": agent_max_steps(),
            "turn_timeout_seconds": agent_turn_timeout_seconds(),
            "tool_namespace": "meta_ads",
            "tool_discovery": "mcp_tools_list",
            "deferred_tools": active_llm_provider() == "openai",
            "tool_search": active_llm_provider() == "openai",
            "portable_tool_exposure": active_llm_provider() == "deepseek",
            "skill_loader": "load_skill",
            "reference_loader": "read_skill_reference",
            "result_validator": "submit_result",
            "project_skill_count": len(SKILL_ORDER),
            "skill_scope_enforced": True,
            "local_tools": LOCAL_AGENT_TOOLS,
            "execution": "disabled",
            "direct_meta_drafts": True,
            "activation": "blocked",
            "trace_policy": "redacted_tool_summary",
            "context_recent_rounds": 5,
            "context_input_token_budget": 36000,
            "context_output_reserve_tokens": 4000,
            "context_compression_ratio": 0.8,
            "long_term_memory": True,
            "task_state": True,
            "account_cache": True,
        },
        "ads_providers": {"meta": MetaAdsProvider().status()},
    }


@router.post("/config/reload")
def config_reload() -> dict[str, Any]:
    reload_dotenv()
    return config()


__all__ = [name for name in globals() if not name.startswith("__")]
