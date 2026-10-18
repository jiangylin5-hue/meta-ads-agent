"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { AccountSidebar } from "@/features/accounts/account-sidebar";
import { ChatPanel } from "@/features/chat/chat-panel";
import { WorkspacePanel } from "@/features/workspace/workspace-panel";
import { approveActionDraft, confirmMemory, deleteMemory, getConfig, getMemory, getMetaAccounts, getMetaStatus, getSession, rejectMemory, streamAgentTurn } from "@/lib/api/client";
import { AgentStreamError, type AgentStreamEvent } from "@/lib/api/sse";
import type {
  AgentDraft,
  AgentTraceStep,
  ApiRecord,
  ChatMessage,
  ChatResponse,
  ContextManifest,
  HistoryPagination,
  MemoryRecord,
  MetaAccount,
  WorkspaceArtifact,
} from "@/lib/types/api";

const ACTIVE_SESSION_STORAGE_KEY = "ads-agent-active-session-id";

type ChatSubmission = {
  message: string;
  idempotencyKey: string;
  accountId: string;
  clientMessageId: string;
};

export function MediaBuyerWorkbench() {
  const [sessionId] = useState(resolveActiveSessionId);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyPagination, setHistoryPagination] = useState<HistoryPagination>({});
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [trace, setTrace] = useState<AgentTraceStep[]>([]);
  const [artifact, setArtifact] = useState<WorkspaceArtifact>({ kind: "empty", title: "等待任务" });
  const [approvalNotice, setApprovalNotice] = useState("");
  const [approvedDraftIds, setApprovedDraftIds] = useState<string[]>([]);
  const [approvingDraftId, setApprovingDraftId] = useState("");
  const [contextManifest, setContextManifest] = useState<ContextManifest>({});
  const [taskState, setTaskState] = useState<ApiRecord>({});
  const [memoryUsed, setMemoryUsed] = useState<MemoryRecord[]>([]);
  const [memorySaved, setMemorySaved] = useState<MemoryRecord[]>([]);
  const [accountContext, setAccountContext] = useState<ApiRecord>({});
  const [updatingMemoryId, setUpdatingMemoryId] = useState("");
  const [streamStatus, setStreamStatus] = useState("");
  const [validationStatus, setValidationStatus] = useState("");
  const requestControllerRef = useRef<AbortController | null>(null);
  const retrySubmissionRef = useRef<ChatSubmission | null>(null);
  const pendingSubmissionRef = useRef<ChatSubmission | null>(null);

  const configQuery = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const sessionQuery = useQuery({ queryKey: ["session", sessionId], queryFn: () => getSession(sessionId, { limit: 50 }) });
  const metaStatusQuery = useQuery({ queryKey: ["meta-status", sessionId], queryFn: () => getMetaStatus(sessionId) });
  const accountsQuery = useQuery({ queryKey: ["meta-accounts", sessionId], queryFn: () => getMetaAccounts(sessionId) });
  const memoryQuery = useQuery({
    queryKey: ["memory", selectedAccountId],
    queryFn: () => getMemory("local_user", selectedAccountId),
  });

  const accounts = accountsQuery.data || [];
  const selectedAccount = useMemo(
    () => accounts.find((account) => (account.id || account.account_id) === selectedAccountId),
    [accounts, selectedAccountId],
  );

  useEffect(() => {
    setMessages(normalizeHistory(sessionQuery.data?.history || []));
    setHistoryPagination(sessionQuery.data?.history_pagination || {});
  }, [sessionQuery.data]);

  useEffect(() => () => requestControllerRef.current?.abort(), []);

  const chatMutation = useMutation({
    mutationFn: async (submission: ChatSubmission) => {
      const controller = new AbortController();
      requestControllerRef.current = controller;
      setTrace([]);
      setValidationStatus("");
      setStreamStatus("正在处理");
      const frontendContext = buildFrontendContext(sessionId, selectedAccountId, accounts);
      try {
        return await streamAgentTurn(
          {
            message: submission.message,
            session_id: sessionId,
            account_id: selectedAccountId,
            idempotency_key: submission.idempotencyKey,
            frontend_context: frontendContext,
          },
          {
            signal: controller.signal,
            onEvent: handleStreamEvent,
          },
        );
      } finally {
        if (requestControllerRef.current === controller) requestControllerRef.current = null;
      }
    },
    onMutate: (submission) => {
      setMessages((items) => (
        items.some((item) => item.id === submission.clientMessageId)
          ? items
          : [...items, { id: submission.clientMessageId, role: "user", content: submission.message }]
      ));
    },
    onSuccess: (response) => {
      pendingSubmissionRef.current = null;
      const reply = response.reply || "我需要更多信息才能继续。";
      setMessages((items) => [...items, { id: createClientId(), role: "assistant", content: reply }]);
      setTrace(traceFromResponse(response));
      setArtifact(artifactFromChatResponse(response));
      setContextManifest(response.context_manifest || {});
      setTaskState(response.task_state || {});
      setMemoryUsed(response.memory_used || []);
      setMemorySaved(response.memory_saved || []);
      setAccountContext(response.account_context || {});
      if ((response.memory_saved || []).length) void memoryQuery.refetch();
      if (hasStructuredResult(response)) setValidationStatus("结果已校验");
      setStreamStatus("");
    },
    onError: (error, submission) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        setStreamStatus("");
        return;
      }
      if (error instanceof AgentStreamError && !error.retryable) {
        retrySubmissionRef.current = null;
      } else {
        retrySubmissionRef.current = submission;
      }
      const message = error instanceof Error ? error.message : "后端对话失败，请检查 API 服务。";
      setMessages((items) => [...items, { id: createClientId(), role: "assistant", content: message }]);
      upsertTrace({
        id: `error-${Date.now()}`,
        title: error instanceof AgentStreamError ? error.code : "请求失败",
        detail: message,
        status: "error",
        agent: "error",
      });
      setStreamStatus("");
    },
    onSettled: () => setStreamStatus(""),
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: (memoryId: string) => deleteMemory(memoryId),
    onSuccess: (_payload, memoryId) => {
      setMemoryUsed((items) => items.filter((item) => item.id !== memoryId));
      void memoryQuery.refetch();
    },
  });

  const updateMemoryMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "reject" }) => (
      action === "confirm" ? confirmMemory(id) : rejectMemory(id)
    ),
    onMutate: ({ id }) => setUpdatingMemoryId(id),
    onSuccess: () => {
      void memoryQuery.refetch();
    },
    onSettled: () => setUpdatingMemoryId(""),
  });

  const approveDraftMutation = useMutation({
    mutationFn: async (draft: AgentDraft) => {
      const actionId = draft.action_id || "";
      if (!actionId) throw new Error("This draft has no lifecycle action id.");
      setApprovingDraftId(actionId);
      return approveActionDraft(actionId, "Approved from the single-page demo after evidence review.");
    },
    onSuccess: (response, draft) => {
      const approvedId = draft.action_id || draft.draft_id;
      setApprovedDraftIds((items) => Array.from(new Set([...items, approvedId])));
      setApprovalNotice(response.message || `Draft ${draft.draft_id} approved. No execution was performed.`);
      setApprovingDraftId("");
    },
    onError: (error) => {
      setApprovingDraftId("");
      setApprovalNotice(error instanceof Error ? error.message : "Draft approval failed.");
    },
  });

  function handleSend(message: string) {
    const trimmed = message.trim();
    if (!trimmed || chatMutation.isPending || sessionQuery.isFetching) return;
    const pending = pendingSubmissionRef.current;
    const submission = pending && pending.message === trimmed && pending.accountId === selectedAccountId
      ? pending
      : {
          message: trimmed,
          idempotencyKey: createClientId("turn"),
          accountId: selectedAccountId,
          clientMessageId: createClientId("message"),
        };
    pendingSubmissionRef.current = submission;
    chatMutation.mutate(submission);
  }

  function handleStreamEvent(event: AgentStreamEvent) {
    const data = event.data;
    if (event.event === "turn.started") {
      setStreamStatus("已建立流式连接");
      return;
    }
    if (event.event === "step.started") {
      setStreamStatus(`模型处理第 ${String(data.step || 1)} 步`);
      return;
    }
    if (event.event === "skill.loaded") {
      const skills = Array.isArray(data.skills) ? (data.skills as ApiRecord[]) : [];
      for (const skill of skills) {
        upsertTrace({
          id: `skill-${String(skill.id || skill.name || "")}`,
          title: "已加载 Skill",
          detail: `${String(skill.name || skill.id || "")} · v${String(skill.version || "-")}`,
          status: "done",
          agent: "skill",
        });
      }
      return;
    }
    if (event.event === "reference.loaded") {
      upsertTrace({
        id: `reference-${String(data.skill || "")}-${String(data.reference || "")}`,
        title: "已加载参考",
        detail: `${String(data.skill || "")}.${String(data.reference || "")} · ${String(data.chars || 0)} chars`,
        status: "done",
        agent: "skill",
      });
      return;
    }
    if (event.event === "tool.started") {
      const tool = String(data.tool || "tool");
      setStreamStatus(`正在调用 ${tool}`);
      upsertTrace({
        id: `tool-${String(data.call_id || event.seq)}`,
        title: `调用 ${tool}`,
        detail: formatStreamDetail(data.arguments_summary),
        status: "running",
        agent: "tool",
      });
      return;
    }
    if (event.event === "tool.finished") {
      upsertTrace({
        id: `tool-${String(data.call_id || event.seq)}`,
        title: `完成 ${String(data.tool || "tool")}`,
        detail: `${formatStreamDetail(data.result_summary)} · ${String(data.duration_ms || 0)} ms`,
        status: String(data.status || "done"),
        agent: "tool",
      });
      return;
    }
    if (event.event === "draft.staged") {
      upsertTrace({
        id: `draft-${String(data.staged_action_id || event.seq)}`,
        title: "Draft 已暂存",
        detail: [data.target_level, data.target_name || data.target_id, data.staged_action_id].filter(Boolean).join(" · "),
        status: "staged",
        agent: "draft",
      });
      return;
    }
    if (event.event === "result.validated") {
      const status = `结果已校验 · ${String(data.skill_count || 0)} 个 Skill · ${String(data.conflict_count || 0)} 个冲突说明`;
      setValidationStatus(status);
      upsertTrace({
        id: `validation-${event.turn_id}`,
        title: "结构化结果校验通过",
        detail: `${String(data.resolved_decision || "resolved")} · ${status}`,
        status: "validated",
        agent: "result",
      });
      return;
    }
    if (event.event === "turn.completed") {
      setStreamStatus("正在整理最终结果");
      return;
    }
    if (event.event === "turn.failed") {
      setStreamStatus(String(data.message || "本轮处理失败"));
    }
  }

  function upsertTrace(step: AgentTraceStep) {
    setTrace((items) => {
      const index = items.findIndex((item) => item.id === step.id);
      if (index === -1) return [step, ...items].slice(0, 16);
      const next = [...items];
      next[index] = { ...next[index], ...step };
      return next;
    });
  }

  async function handleLoadOlderHistory() {
    const before = historyPagination.next_before;
    if (!before || isLoadingOlder) return;
    setIsLoadingOlder(true);
    try {
      const payload = await getSession(sessionId, { limit: 50, before });
      setMessages((items) => mergeHistory(normalizeHistory(payload.history || []), items));
      setHistoryPagination(payload.history_pagination || {});
    } finally {
      setIsLoadingOlder(false);
    }
  }

  const metaStatus = metaStatusQuery.isError
    ? "Meta 连接异常"
    : metaStatusQuery.data
      ? selectedAccount
        ? `已选择 ${selectedAccount.name || selectedAccountId}`
        : "Meta 状态已读取"
      : "检查 Meta 连接中";

  return (
    <main className="grid h-screen min-h-0 grid-cols-[320px_minmax(520px,1fr)_460px] overflow-hidden border border-border bg-background max-xl:grid-cols-[300px_minmax(0,1fr)] max-lg:h-auto max-lg:min-h-screen max-lg:grid-cols-1 max-lg:overflow-auto">
      <AccountSidebar
        accounts={accounts as MetaAccount[]}
        selectedAccountId={selectedAccountId}
        metaStatus={metaStatus}
        isLoading={accountsQuery.isFetching || metaStatusQuery.isFetching || configQuery.isFetching}
        onSelectAccount={setSelectedAccountId}
        onRefresh={() => {
          void accountsQuery.refetch();
          void metaStatusQuery.refetch();
        }}
        onQuickTask={handleSend}
      />
      <ChatPanel
        messages={messages}
        isSending={chatMutation.isPending || sessionQuery.isFetching}
        pendingText={streamStatus || "Agent 正在选择工具..."}
        hasMoreHistory={Boolean(historyPagination.has_more && historyPagination.next_before)}
        isLoadingHistory={isLoadingOlder}
        onLoadOlder={handleLoadOlderHistory}
        onSend={handleSend}
      />
      <div className="max-xl:col-span-2 max-lg:col-span-1 max-lg:min-h-[520px]">
        <WorkspacePanel
          artifact={artifact}
          trace={trace}
          contextManifest={contextManifest}
          taskState={taskState}
          memories={memoryQuery.data?.length ? memoryQuery.data : memoryUsed}
          memorySaved={memorySaved}
          accountContext={accountContext}
          validationStatus={validationStatus}
          deletingMemoryId={deleteMemoryMutation.isPending ? String(deleteMemoryMutation.variables || "") : ""}
          updatingMemoryId={updatingMemoryId}
          onDeleteMemory={(memoryId) => deleteMemoryMutation.mutate(memoryId)}
          onConfirmMemory={(memoryId) => updateMemoryMutation.mutate({ id: memoryId, action: "confirm" })}
          onRejectMemory={(memoryId) => updateMemoryMutation.mutate({ id: memoryId, action: "reject" })}
          onApproveDraft={(draft) => approveDraftMutation.mutate(draft)}
          approvingDraftId={approvingDraftId}
          approvedDraftIds={approvedDraftIds}
          approvalNotice={approvalNotice}
        />
      </div>
    </main>
  );
}

function resolveActiveSessionId() {
  const nextId = createClientId("session");
  if (typeof window === "undefined") return nextId;
  const stored = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  if (stored) return stored;
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, nextId);
  return nextId;
}

function createClientId(prefix = "message") {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${prefix}-${Date.now()}`;
}

function normalizeHistory(items: ChatMessage[]) {
  return items
    .filter((item) => item && item.role !== "system" && item.content)
    .map((item, index) => ({
      ...item,
      id: item.id || `${item.created_at || "message"}-${index}`,
    }));
}

function mergeHistory(older: ChatMessage[], current: ChatMessage[]) {
  const seen = new Set(current.map((item) => item.id));
  return [...older.filter((item) => !seen.has(item.id)), ...current];
}

function buildFrontendContext(sessionId: string, selectedAccountId: string, accounts: MetaAccount[]) {
  return {
    session_id: sessionId,
    selected_account_id: selectedAccountId,
    account_candidates: accounts.slice(0, 20).map((account) => ({
      id: account.id || account.account_id || "",
      name: account.name || "",
      account_id: account.account_id || account.id || "",
    })),
    current_mode: "media_buyer_workbench",
  };
}

function traceFromResponse(response: ChatResponse): AgentTraceStep[] {
  const source = Array.isArray(response.visible_agent_steps) && response.visible_agent_steps.length
    ? response.visible_agent_steps
    : Array.isArray(response.trace)
      ? response.trace
      : [];
  if (!source.length) {
    return [{ id: "final-direct-answer", title: "直接回答", detail: "本轮没有调用工具。", status: "done", agent: "Agent" }];
  }
  return source.map((step, index) => {
    const record = step && typeof step === "object" ? (step as Record<string, unknown>) : {};
    return {
      id: `final-${index}`,
      title: String(record.title || record.tool || record.agent || "Agent step"),
      detail: String(record.detail || record.message || record.description || "已完成一个公开执行步骤。"),
      status: String(record.status || "done"),
      agent: String(record.agent || "Agent"),
    };
  });
}

function formatStreamDetail(value: unknown) {
  if (value == null) return "No compact detail.";
  if (typeof value === "string") return value.slice(0, 500);
  try {
    return JSON.stringify(value).slice(0, 500);
  } catch {
    return String(value).slice(0, 500);
  }
}

function hasStructuredResult(response: ChatResponse) {
  const value = response.structured_result;
  return Boolean(value && typeof value === "object" && Object.keys(value).length);
}

function artifactFromChatResponse(response: ChatResponse): WorkspaceArtifact {
  const payload = response as unknown as ApiRecord;
  const presentation = String(response.presentation_mode || "");
  const intentType = String(response.intent_type || response.decision_card?.intent_type || "");
  if (presentation === "dashboard" || intentType === "read_data") {
    return { kind: "dashboard", title: "账户表现 Dashboard", payload };
  }
  if (["audit", "action_cards"].includes(presentation) || ["audit", "optimize", "action"].includes(intentType)) {
    return { kind: "actions", title: "审计与动作草稿", payload };
  }
  return { kind: "audit", title: "DecisionCard 与 Trace", payload };
}
