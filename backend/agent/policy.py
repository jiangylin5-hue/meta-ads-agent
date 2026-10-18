from __future__ import annotations

from .tools import is_forbidden_publish_tool, is_ignored_tool, is_write_tool


LOCAL_TOOL_NAMES = {"ask_user", "load_skill", "read_skill_reference", "submit_result", "save_memory", "update_task"}
FORBIDDEN_TOOL_NAMES = {"execute_action", "publish_batch_draft", "execute_rollback"}


def classify_tool(name: str) -> str:
    if name in LOCAL_TOOL_NAMES:
        return "local"
    if is_write_tool(name):
        return "draft"
    return "read"


def ensure_tool_allowed(name: str, available_mcp_tools: set[str] | None = None) -> None:
    if name in FORBIDDEN_TOOL_NAMES:
        raise PermissionError(f"Execution tool is not available to the agent: {name}")
    if is_forbidden_publish_tool(name):
        raise PermissionError(f"Publishing or activation tools are not available to the agent: {name}")
    if is_ignored_tool(name):
        raise PermissionError(f"Tool is not exposed to the agent: {name}")
    if name in LOCAL_TOOL_NAMES:
        return
    if available_mcp_tools is not None and name in available_mcp_tools:
        return
    raise PermissionError(f"Unknown agent tool: {name}")
