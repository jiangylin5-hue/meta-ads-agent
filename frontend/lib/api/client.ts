import { AgentStreamError, parseAgentStreamFrame, readSSEStream, type AgentStreamEvent } from "@/lib/api/sse";
import type {
  ActionApprovalResponse,
  ApiRecord,
  ChatResponse,
  MemoryRecord,
  MetaAccount,
  SessionDetail,
} from "@/lib/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8010";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  return parseResponse<T>(response);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(response);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: Record<string, unknown> = {};
  try {
    data = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    if (!response.ok) throw new Error(text.slice(0, 500) || `HTTP ${response.status}`);
    throw new Error("后端返回了无法解析的响应。");
  }
  if (!response.ok) {
    throw new Error(extractErrorDetail(data, response));
  }
  return data as T;
}

function extractErrorDetail(data: Record<string, unknown>, response: Response): string {
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
  }
  return response.statusText || `HTTP ${response.status}`;
}

export function getConfig() {
  return apiGet<ApiRecord>("/api/config");
}

export function getMetaStatus(sessionId: string) {
  return apiGet<ApiRecord>(`/api/meta/status?session_id=${encodeURIComponent(sessionId)}`);
}

export async function getMetaAccounts(sessionId: string) {
  const payload = await apiGet<{ accounts?: MetaAccount[] }>(`/api/meta/adaccounts?session_id=${encodeURIComponent(sessionId)}`);
  return payload.accounts || [];
}

export function getSession(sessionId: string, options: { limit?: number; before?: string } = {}) {
  const params = new URLSearchParams({ limit: String(options.limit || 50) });
  if (options.before) params.set("before", options.before);
  return apiGet<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}?${params.toString()}`);
}

export function sendAgentTurn(payload: ApiRecord) {
  return apiPost<ChatResponse>("/api/agent/turn", payload);
}

export type StreamAgentTurnOptions = {
  signal?: AbortSignal;
  onEvent?: (event: AgentStreamEvent) => void;
};

export async function streamAgentTurn(payload: ApiRecord, options: StreamAgentTurnOptions = {}): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/agent/turn`, {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
    signal: options.signal,
  });

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    return parseResponse<ChatResponse>(response);
  }
  if (!response.body) throw new AgentStreamError("stream_unavailable", "浏览器无法读取流式响应。", false);

  let completed: ChatResponse | null = null;
  let lastSeq = 0;
  let expectedTurnId = "";
  let firstEvent = true;
  let terminalSeen = false;

  try {
    await readSSEStream(response.body, (frame) => {
      const event = parseAgentStreamFrame(frame);
      if (event.seq !== lastSeq + 1) {
        throw new AgentStreamError("invalid_sequence", "流式事件顺序不正确。", false, event.turn_id);
      }
      if (expectedTurnId && event.turn_id !== expectedTurnId) {
        throw new AgentStreamError("turn_mismatch", "流式事件属于不同的任务。", false, event.turn_id);
      }
      if (firstEvent && event.event !== "turn.started") {
        throw new AgentStreamError("missing_turn_start", "流式响应缺少任务开始事件。", false, event.turn_id);
      }
      if (terminalSeen) {
        throw new AgentStreamError("duplicate_terminal", "流式响应包含重复的终止事件。", false, event.turn_id);
      }
      firstEvent = false;
      lastSeq = event.seq;
      expectedTurnId = event.turn_id;
      options.onEvent?.(event);

      if (event.event === "turn.failed") {
        terminalSeen = true;
        throw new AgentStreamError(
          String(event.data.code || "turn_failed"),
          String(event.data.message || "本轮处理失败。"),
          Boolean(event.data.retryable),
          event.turn_id,
        );
      }
      if (event.event === "turn.completed") {
        terminalSeen = true;
        const value = event.data.response;
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          throw new AgentStreamError("invalid_completion", "最终响应格式不正确。", false, event.turn_id);
        }
        completed = value as ChatResponse;
      }
    });
  } catch (error) {
    if (error instanceof AgentStreamError) throw error;
    if (options.signal?.aborted) throw error;
    throw new AgentStreamError(
      "stream_interrupted",
      "连接已断开，后台可能仍在处理；请刷新会话查看结果。",
      false,
      expectedTurnId,
    );
  }

  if (completed) return completed;
  throw new AgentStreamError("stream_incomplete", "流式响应未收到最终结果，请刷新会话查看状态。", false, expectedTurnId);
}

export async function getMemory(userId = "local_user", accountId = "") {
  const params = new URLSearchParams({ user_id: userId });
  if (accountId) params.set("account_id", accountId);
  const payload = await apiGet<{ memories?: MemoryRecord[] }>(`/api/memory?${params.toString()}`);
  return payload.memories || [];
}

export function deleteMemory(memoryId: string, userId = "local_user") {
  return apiDelete<{ id: string; status: string }>(`/api/memory/${encodeURIComponent(memoryId)}?user_id=${encodeURIComponent(userId)}`);
}

export function confirmMemory(memoryId: string, userId = "local_user") {
  return apiPost<{ id: string; status: string }>(`/api/memory/${encodeURIComponent(memoryId)}/confirm?user_id=${encodeURIComponent(userId)}`, {});
}

export function rejectMemory(memoryId: string, userId = "local_user") {
  return apiPost<{ id: string; status: string }>(`/api/memory/${encodeURIComponent(memoryId)}/reject?user_id=${encodeURIComponent(userId)}`, {});
}

export function approveActionDraft(actionId: string, note = "") {
  return apiPost<ActionApprovalResponse>(`/api/actions/drafts/${encodeURIComponent(actionId)}/approve`, { note });
}
