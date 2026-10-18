from pathlib import Path


FRONTEND_ROOT = Path("frontend")

MOJIBAKE_MARKERS = [
    chr(0x93B4),
    chr(0x7487),
    chr(0x95AB),
    chr(0x7039),
    chr(0x93C1),
    chr(0x7EDB),
    chr(0x9422),
    chr(0x951B),
    chr(0x9286),
    "\ufffd",
    "\u93b6",
    "\u7035",
    "\u8930",
    "\u9a9e",
    "\u7490",
    "\u752f",
    "\u6769",
    "\u9225",
]

FRONTEND_POLLUTION_MARKERS = [
    "Brief Agent",
    "Media Agent",
    "Execution Agent",
    "mock_ads",
    "external research",
    "competitor research",
]


def test_single_page_workbench_is_the_only_frontend_shell() -> None:
    assert (FRONTEND_ROOT / "package.json").exists()
    assert (FRONTEND_ROOT / "app" / "app" / "page.tsx").exists()
    assert (FRONTEND_ROOT / "features" / "workbench" / "media-buyer-workbench.tsx").exists()
    assert not (FRONTEND_ROOT / "features" / "saas-dashboard").exists()
    assert not (FRONTEND_ROOT / "index.html").exists()
    assert not (FRONTEND_ROOT / "app.js").exists()
    assert not (FRONTEND_ROOT / "styles.css").exists()


def test_frontend_uses_mature_workbench_stack() -> None:
    package_json = (FRONTEND_ROOT / "package.json").read_text(encoding="utf-8")
    for dependency in ["next", "react", "@tanstack/react-query", "tailwindcss", "echarts", "lucide-react", "@playwright/test"]:
        assert dependency in package_json

    components_json = (FRONTEND_ROOT / "components.json").read_text(encoding="utf-8")
    assert "shadcn" in components_json.lower()


def test_frontend_copy_has_no_encoding_or_legacy_pollution() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FRONTEND_ROOT.rglob("*")
        if path.suffix in {".ts", ".tsx", ".css", ".json", ".mjs"}
        and "node_modules" not in path.parts
        and ".next" not in path.parts
        and "tsconfig" not in path.name
    )

    assert "AI Media Buyer" in text
    assert "AI 投手对话" in text
    assert "Workspace" in text
    assert "当前广告账户" in text

    for marker in MOJIBAKE_MARKERS:
        assert marker not in text

    for marker in FRONTEND_POLLUTION_MARKERS:
        assert marker not in text


def test_frontend_api_client_contains_only_the_demo_core_interfaces() -> None:
    api_client = (FRONTEND_ROOT / "lib" / "api" / "client.ts").read_text(encoding="utf-8")
    for endpoint in [
        "/api/config",
        "/api/meta/status",
        "/api/meta/adaccounts",
        "/api/agent/turn",
        "/api/actions/drafts/",
    ]:
        assert endpoint in api_client

    assert "approveActionDraft" in api_client
    for removed in ["/performance-dashboard", "/batch-drafts", "/publish-paused", "/api/intent", "/api/chat"]:
        assert removed not in api_client

    for forbidden_path in ["/api/google", "/api/tiktok", "/api/shopify", "/api/ga4"]:
        assert forbidden_path not in api_client