export type ApiRecord = Record<string, unknown>;

export type MetaAccount = {
  id?: string;
  account_id?: string;
  name?: string;
  currency?: string;
  status?: string;
  business_name?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  metadata?: ApiRecord;
};

export type HistoryPagination = {
  limit?: number;
  has_more?: boolean;
  next_before?: string;
};

export type SessionDetail = {
  session_id?: string;
  history?: ChatMessage[];
  history_pagination?: HistoryPagination;
  compressed_context?: ApiRecord;
  task_state?: ApiRecord;
};

export type MemoryRecord = {
  id: string;
  kind?: string;
  scope_type?: string;
  scope_id?: string;
  account_id?: string;
  content?: string;
  status?: string;
  confidence?: number;
  updated_at?: string;
};

export type ContextManifest = {
  input_budget_tokens?: number;
  output_reserve_tokens?: number;
  recent_rounds_limit?: number;
  recent_message_count?: number;
  older_message_count?: number;
  summary_tokens?: number;
  memory_tokens?: number;
  task_tokens?: number;
  account_tokens?: number;
  skill_tokens?: number;
  instructions_tokens?: number;
  history_tokens?: number;
  tool_schema_tokens?: number;
  estimated_input_tokens?: number;
  actual_input_tokens?: number;
  actual_output_tokens?: number;
  active_skill_ids?: string[];
};

export type AgentTraceStep = {
  id: string;
  title: string;
  detail: string;
  status?: string;
  agent?: string;
};

export type WorkspaceArtifact = {
  kind: "empty" | "dashboard" | "audit" | "actions";
  title: string;
  payload?: ApiRecord;
};

export type AgentDraft = {
  draft_id: string;
  action_id?: string;
  status?: string;
  requires_approval?: boolean;
  target_level?: string;
  target_id?: string;
  target_name?: string;
  evidence?: string;
  recommendation?: string;
  risk_level?: string;
  preflight?: ApiRecord;
};

export type ActionApprovalResponse = {
  action?: ApiRecord;
  approval?: ApiRecord;
  message?: string;
};

export type ChatResponse = {
  session_id?: string;
  status?: string;
  reply?: string;
  runtime?: string;
  trace_id?: string;
  turn_id?: string;
  intent_type?: string;
  presentation_mode?: string;
  visible_agent_steps?: ApiRecord[];
  decision_card?: ApiRecord;
  trace?: ApiRecord[];
  drafts?: AgentDraft[];
  direct_drafts?: ApiRecord[];
  direct_draft_mutations?: ApiRecord[];
  steps?: number;
  stopped_reason?: string;
  skills_loaded?: string[];
  references_loaded?: string[];
  structured_result?: ApiRecord;
  context_manifest?: ContextManifest;
  task_state?: ApiRecord;
  memory_used?: MemoryRecord[];
  memory_saved?: MemoryRecord[];
  account_context?: ApiRecord;
  user_message_id?: string;
  assistant_message_id?: string;
  idempotent_replay?: boolean;
};
