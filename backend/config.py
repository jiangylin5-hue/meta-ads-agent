import os
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
_loaded_env_mtime: float | None = None
_loaded_env_values: dict[str, str] = {}


def load_dotenv(force: bool = False) -> None:
    global _loaded_env_mtime, _loaded_env_values
    env_path = ENV_PATH
    if not env_path.exists():
        return
    mtime = env_path.stat().st_mtime
    if not force and _loaded_env_mtime == mtime:
        return

    next_values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        next_values[key] = value

    for key, previous_value in _loaded_env_values.items():
        if key not in next_values and os.environ.get(key) == previous_value:
            os.environ.pop(key, None)
    for key, value in next_values.items():
        current = os.environ.get(key)
        if current is None or current == _loaded_env_values.get(key):
            os.environ[key] = value

    _loaded_env_values = next_values
    _loaded_env_mtime = mtime


def reload_dotenv() -> None:
    load_dotenv(force=True)


def env_file_status() -> dict[str, object]:
    load_dotenv()
    if not ENV_PATH.exists():
        return {"path": str(ENV_PATH), "exists": False, "loaded_key_count": 0}
    return {
        "path": str(ENV_PATH),
        "exists": True,
        "loaded_key_count": len(_loaded_env_values),
        "mtime": _loaded_env_mtime,
    }


def secret_fingerprint(value: str) -> dict[str, object]:
    normalized = (value or "").strip()
    if not normalized:
        return {"configured": False}
    return {
        "configured": True,
        "length": len(normalized),
        "sha256_8": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8],
    }


load_dotenv()


def openai_api_key() -> str:
    load_dotenv()
    return os.getenv("OPENAI_API_KEY", "")


def openai_model() -> str:
    load_dotenv()
    return os.getenv("OPENAI_MODEL", "gpt-6-luna")


def openai_reasoning_effort() -> str:
    load_dotenv()
    return os.getenv("OPENAI_REASONING_EFFORT", "medium")


def openai_timeout_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv("OPENAI_TIMEOUT_SECONDS", "180")
    try:
        return max(30, int(raw_value))
    except ValueError:
        return 180


def active_llm_provider() -> str:
    load_dotenv()
    return os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"


def deepseek_api_key() -> str:
    load_dotenv()
    return os.getenv("DEEPSEEK_API_KEY", "")


def deepseek_base_url() -> str:
    load_dotenv()
    return os.getenv("LLM_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).strip()


def active_llm_model() -> str:
    load_dotenv()
    if active_llm_provider() == "deepseek":
        return os.getenv("LLM_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-flash")).strip() or "deepseek-flash"
    return openai_model()


def llm_reasoning_effort() -> str:
    load_dotenv()
    if active_llm_provider() == "deepseek":
        return os.getenv("LLM_REASONING_EFFORT", "high").strip().lower() or "high"
    return ""


def llm_timeout_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv("LLM_TIMEOUT_SECONDS", "120")
    try:
        return max(30, int(raw_value))
    except ValueError:
        return 120


def llm_max_retries() -> int:
    load_dotenv()
    raw_value = os.getenv("LLM_MAX_RETRIES", "2")
    try:
        return max(0, min(int(raw_value), 5))
    except ValueError:
        return 2


def llm_max_output_tokens() -> int:
    load_dotenv()
    raw_value = os.getenv("LLM_MAX_OUTPUT_TOKENS", "16384")
    try:
        return max(256, int(raw_value))
    except ValueError:
        return 4096


def agent_max_steps() -> int:
    load_dotenv()
    raw_value = os.getenv("AGENT_MAX_STEPS", "16")
    try:
        return max(1, min(int(raw_value), 24))
    except ValueError:
        return 16


def agent_turn_timeout_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv("AGENT_TURN_TIMEOUT_SECONDS", "600")
    try:
        return max(30, int(raw_value))
    except ValueError:
        return 600


def meta_access_token() -> str:
    load_dotenv()
    return os.getenv("META_ACCESS_TOKEN", "")


def meta_graph_api_version() -> str:
    load_dotenv()
    return os.getenv("META_GRAPH_API_VERSION", "v23.0")


def meta_default_ad_account_id() -> str:
    load_dotenv()
    return os.getenv("META_AD_ACCOUNT_ID", "")


def remote_ads_mcp_endpoint() -> str:
    load_dotenv()
    return os.getenv("ADS_MCP_ENDPOINT_URL", "")


def remote_ads_mcp_token() -> str:
    load_dotenv()
    for key in ("ADS_MCP_API_TOKEN", "PIPEBOARD_API_TOKEN", "ADS_MCP_AUTH_TOKEN"):
        value = os.getenv(key, "")
        if _is_configured_secret(value):
            return value
    return ""


def _is_configured_secret(value: str | None) -> bool:
    normalized = (value or "").strip().strip('"').strip("'")
    if not normalized:
        return False
    if not normalized.isascii():
        return False
    lowered = normalized.lower()
    placeholders = {
        "your-key",
        "your-openai-key",
        "sk-your-key-here",
        "your-token",
        "your-mcp-token",
        "your-meta-access-token",
        "replace-me",
        "changeme",
        "todo",
    }
    if lowered in placeholders:
        return False
    if lowered.startswith(("your-", "replace-", "example-", "dummy-")):
        return False
    return True


def account_gateway_preference() -> str:
    load_dotenv()
    return os.getenv("ACCOUNT_GATEWAY_PREFERENCE", "mcp").strip().lower()


def meta_live_write_enabled() -> bool:
    load_dotenv()
    return os.getenv("META_LIVE_WRITE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def meta_draft_write_enabled() -> bool:
    load_dotenv()
    return os.getenv("META_DRAFT_WRITE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def ga4_credentials_path() -> str:
    load_dotenv()
    return os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()


def ga4_project_id() -> str:
    load_dotenv()
    return os.getenv("GOOGLE_PROJECT_ID", "").strip()


def ga4_default_property_id() -> str:
    load_dotenv()
    return os.getenv("GA4_PROPERTY_ID", "").strip()


def ga4_request_timeout_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv("GA4_TIMEOUT_SECONDS", "30")
    try:
        return max(5, min(int(raw_value), 60))
    except ValueError:
        return 30


def ga4_enabled() -> bool:
    load_dotenv()
    credentials = ga4_credentials_path()
    return bool(credentials and Path(credentials).expanduser().is_file())


def app_allowed_origins() -> list[str]:
    load_dotenv()
    raw_value = os.getenv("APP_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://127.0.0.1:3100").strip()
    if not raw_value:
        return ["http://127.0.0.1:3000", "http://127.0.0.1:3100"]
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def ads_agent_db_path() -> str:
    load_dotenv()
    return os.getenv("ADS_AGENT_DB_PATH", str(ROOT / "_runtime" / "ads_agent.sqlite3"))


def database_url() -> str:
    load_dotenv()
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://ads_agent:ads_agent@127.0.0.1:5432/ads_agent?connect_timeout=3",
    )


def ads_agent_secret_key() -> str:
    load_dotenv()
    return os.getenv("ADS_AGENT_SECRET_KEY", "")


def legacy_sqlite_import_path() -> str:
    load_dotenv()
    return os.getenv("LEGACY_SQLITE_IMPORT_PATH", ads_agent_db_path())


def agent_trace_enabled() -> bool:
    load_dotenv()
    return os.getenv("AGENT_TRACE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
