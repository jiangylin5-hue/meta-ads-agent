import { expect, test } from "@playwright/test";

test("loads the single-page agent workbench and consumes one SSE turn", async ({ page }) => {
  await routeCoreApi(page, "success");
  await page.goto("/app");

  await expect(page.getByText("AI 投手对话")).toBeVisible();
  await expect(page.getByText("账户列表")).toBeVisible();
  await expect(page.getByText("Northbeam - Main Ad Account")).toBeVisible();

  await page.getByPlaceholder("问一个投手问题，例如：今天这个账户怎么样？哪些广告该停？").fill("今天这个账户怎么样？");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("今天这个账户怎么样？", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("先看近 30 天数据，再判断预算和素材方向。")).toBeVisible();

  await page.getByRole("button", { name: "Trace" }).click();
  await expect(page.getByText("Agent step").first()).toBeVisible();
  await expect(page.getByText("已加载 Skill")).toHaveCount(0);

  await page.getByRole("button", { name: "Actions" }).click();
  await expect(page.getByText("结果已校验")).toBeVisible();
  await expect(page.getByText("Demo Ad")).toBeVisible();
  await expect(page.getByText(/Spend without conversions/)).toBeVisible();
  await page.getByRole("button", { name: "Approve draft" }).click();
  await expect(page.getByText(/Draft draft_demo approved/)).toBeVisible();

  await page.getByRole("button", { name: "上下文" }).click();
  await expect(page.getByText("Context budget")).toBeVisible();
  await expect(page.getByText("Current task")).toBeVisible();

  const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(hasOverflow).toBe(false);
});

test("turn.failed shows one error message without duplicating the user message", async ({ page }) => {
  await routeCoreApi(page, "failed");
  await page.goto("/app");

  const question = "触发失败";
  await page.getByPlaceholder("问一个投手问题，例如：今天这个账户怎么样？哪些广告该停？").fill(question);
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("模拟执行失败，请稍后重试。")).toHaveCount(1);
  await expect(page.getByText(question, { exact: true })).toHaveCount(1);
});

test("an interrupted SSE response leaves one user message and one visible error", async ({ page }) => {
  await routeCoreApi(page, "interrupted");
  await page.goto("/app");

  const question = "连接中断测试";
  await page.getByPlaceholder("问一个投手问题，例如：今天这个账户怎么样？哪些广告该停？").fill(question);
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText(/流式响应未收到最终结果/)).toHaveCount(1);
  await expect(page.getByText(question, { exact: true })).toHaveCount(1);
});

test("reuses the idempotency key when the same failed message is retried", async ({ page }) => {
  await routeCoreApi(page, "success");
  const idempotencyKeys: string[] = [];
  let attempts = 0;
  await page.route("**/api/agent/turn", async (route) => {
    const body = route.request().postDataJSON() as { idempotency_key?: string };
    idempotencyKeys.push(String(body.idempotency_key || ""));
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({ status: 503, json: { detail: "temporary failure" } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        reply: "retry succeeded",
        runtime: "react",
        intent_type: "chat",
        presentation_mode: "chat",
        visible_agent_steps: [],
        drafts: [],
        trace: [],
        context_manifest: { input_budget_tokens: 36000, recent_rounds_limit: 5 },
        task_state: { status: "active", progress: {} },
        memory_used: [],
        memory_saved: [],
        account_context: {},
      },
    });
  });
  await page.goto("/app");

  const textarea = page.locator("textarea");
  await textarea.fill("retry this exact turn");
  await textarea.press("Enter");
  await expect(page.getByText("temporary failure")).toBeVisible();

  await textarea.fill("retry this exact turn");
  await textarea.press("Enter");
  await expect(page.getByText("retry succeeded")).toBeVisible();

  expect(idempotencyKeys).toHaveLength(2);
  expect(idempotencyKeys[0]).toBeTruthy();
  expect(idempotencyKeys[1]).toBe(idempotencyKeys[0]);
});

test("rejects a stream with a missing sequence number", async ({ page }) => {
  await routeCoreApi(page, "sequence_gap");
  await page.goto("/app");

  const question = "sequence gap test";
  const textarea = page.locator("textarea");
  await textarea.fill(question);
  await textarea.press("Enter");

  await expect(page.getByText("流式事件顺序不正确。")).toHaveCount(1);
  await expect(page.getByText(question, { exact: true })).toHaveCount(1);
});

async function routeCoreApi(page: import("@playwright/test").Page, agentMode: "success" | "failed" | "interrupted" | "sequence_gap") {
  await page.route("**/api/config", (route) => route.fulfill({ json: { default_model: "gpt-6-luna" } }));
  await page.route("**/api/meta/status?**", (route) =>
    route.fulfill({ json: { configured: true, session_connected: true } }),
  );
  await page.route("**/api/meta/adaccounts?**", (route) =>
    route.fulfill({
      json: {
        accounts: [
          {
            id: "act_1001",
            account_id: "act_1001",
            name: "Northbeam - Main Ad Account",
            currency: "USD",
          },
        ],
      },
    }),
  );
  await page.route("**/api/sessions/**", (route) =>
    route.fulfill({ json: { session_id: "test-session", history: [], history_pagination: {}, task_state: {} } }),
  );
  await page.route("**/api/memory?**", (route) => route.fulfill({ json: { memories: [] } }));
  await page.route("**/api/memory/*", (route) => route.fulfill({ json: { id: "mem_demo", status: "deleted" } }));
  await page.route("**/api/actions/drafts/*/approve", (route) =>
    route.fulfill({ json: { action: { id: "act_demo", status: "approved" }, message: "Draft draft_demo approved. No execution was performed." } }),
  );
  await page.route("**/api/agent/turn", (route) =>
    route.fulfill({
      headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache" },
      body: agentResponse(agentMode),
    }),
  );
}

function agentResponse(mode: "success" | "failed" | "interrupted" | "sequence_gap") {
  if (mode === "sequence_gap") {
    return [
      sseEvent(1, "turn.started", startedPayload()),
      sseEvent(3, "step.started", { step: 1, max_steps: 12 }),
    ].join("");
  }
  if (mode === "interrupted") return sseEvent(1, "turn.started", startedPayload());
  if (mode === "failed") {
    return [
      sseEvent(1, "turn.started", startedPayload()),
      sseEvent(2, "step.started", { step: 1, max_steps: 12 }),
      sseEvent(3, "turn.failed", { code: "agent_runtime_failed", message: "模拟执行失败，请稍后重试。", retryable: true }),
    ].join("");
  }
  const response = {
    session_id: "test-session",
    status: "completed",
    reply: "先看近 30 天数据，再判断预算和素材方向。",
    runtime: "react",
    trace_id: "trace_chat",
    turn_id: "turn_chat",
    visible_agent_steps: [{ agent: "Agent", title: "Agent step", status: "completed", detail: "读取账户数据。" }],
    drafts: [
      {
        draft_id: "draft_demo",
        action_id: "act_demo",
        status: "draft",
        requires_approval: true,
        target_level: "ad",
        target_id: "ad_1",
        target_name: "Demo Ad",
        evidence: "Spend without conversions.",
        recommendation: "Pause the ad.",
        risk_level: "high",
        preflight: { result: "allowed" },
      },
    ],
    intent_type: "read_data",
    presentation_mode: "dashboard",
    context_manifest: { input_budget_tokens: 36000, recent_rounds_limit: 5, recent_message_count: 10 },
    task_state: { task_id: "task_demo", goal: "Review account", status: "active", progress: { turn_count: 1 } },
    memory_used: [],
    memory_saved: [],
    account_context: { account_id: "act_1001", freshness: "fresh", as_of: "2026-10-18T00:00:00Z" },
    structured_result: { account_brief: { facts: ["Read succeeded."] } },
    decision_card: {
      judgement: "先看数据，再动预算。",
      facts: ["已读取账户列表"],
      missing_data: ["需要读取本轮 insights"],
      next_action: "读取近 30 天 campaign insights",
      requires_approval: false,
    },
  };
  return [
    sseEvent(1, "turn.started", startedPayload()),
    sseEvent(2, "step.started", { step: 1, max_steps: 12 }),
    sseEvent(3, "skill.loaded", { skills: [{ id: "account_brief", name: "account_brief", version: "0.1.0" }] }),
    sseEvent(4, "tool.started", { step: 1, call_id: "call_1", tool: "meta_ads.ads_get_ad_accounts", arguments_summary: { limit: 3 } }),
    sseEvent(5, "tool.finished", { step: 1, call_id: "call_1", tool: "meta_ads.ads_get_ad_accounts", status: "ok", result_summary: { count: 1 }, duration_ms: 12 }),
    sseEvent(6, "result.validated", { resolved_decision: "HOLD", skill_count: 1, conflict_count: 0 }),
    sseEvent(7, "turn.completed", { response }),
  ].join("");
}

function startedPayload() {
  return { session_id: "test-session", user_message_id: "msg_user", task_id: "task_demo" };
}

function sseEvent(seq: number, event: string, payload: Record<string, unknown>) {
  return `id: ${seq}\nevent: ${event}\ndata: ${JSON.stringify({ ...payload, turn_id: "trace_chat", seq })}\n\n`;
}
