"use client";

import { Activity, ArrowUpRight, BrainCircuit, FileText, LineChart, ListChecks, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MetricChart } from "@/features/workspace/metric-chart";
import type { AgentDraft, AgentTraceStep, ApiRecord, ContextManifest, MemoryRecord, WorkspaceArtifact } from "@/lib/types/api";
import { compactNumber } from "@/lib/utils";

type Props = {
  artifact: WorkspaceArtifact;
  trace: AgentTraceStep[];
  contextManifest?: ContextManifest;
  taskState?: ApiRecord;
  memories?: MemoryRecord[];
  memorySaved?: MemoryRecord[];
  accountContext?: ApiRecord;
  validationStatus?: string;
  deletingMemoryId?: string;
  updatingMemoryId?: string;
  onDeleteMemory?: (memoryId: string) => void;
  onConfirmMemory?: (memoryId: string) => void;
  onRejectMemory?: (memoryId: string) => void;
  onApproveDraft?: (draft: AgentDraft) => void;
  approvingDraftId?: string;
  approvedDraftIds?: string[];
  approvalNotice?: string;
};

export function WorkspacePanel({
  artifact,
  trace,
  contextManifest = {},
  taskState = {},
  memories = [],
  memorySaved = [],
  accountContext = {},
  validationStatus = "",
  deletingMemoryId = "",
  updatingMemoryId = "",
  onDeleteMemory,
  onConfirmMemory,
  onRejectMemory,
  onApproveDraft,
  approvingDraftId = "",
  approvedDraftIds = [],
  approvalNotice = "",
}: Props) {
  const [tab, setTab] = useState("dashboard");
  const payload = artifact.payload || {};
  const dashboardBody = ((payload.dashboard as ApiRecord | undefined) || payload) as ApiRecord;
  const summary = ((dashboardBody.summary as ApiRecord | undefined) || {}) as ApiRecord;
  const decisionCard = ((payload.decision_card as ApiRecord | undefined) || {}) as ApiRecord;
  const drafts = (Array.isArray(payload.drafts) ? payload.drafts : []) as AgentDraft[];
  const routeAssetSummary = [
    "Runtime: ReAct",
    `Intent: ${stringValue(payload.intent_type, "-")}`,
    `Presentation: ${stringValue(payload.presentation_mode, "-")}`,
  ].join("\n");
  const rows = useMemo(() => {
    const entityCards = dashboardBody.entity_cards;
    const comparison = dashboardBody.comparison_chart;
    return (Array.isArray(entityCards) ? entityCards : Array.isArray(comparison) ? comparison : []) as ApiRecord[];
  }, [dashboardBody]);

  return (
    <aside className="flex min-h-0 flex-col border-l border-border bg-[#fbfcfd] max-lg:border-l-0 max-lg:border-t">
      <div className="border-b border-border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">Evidence Workspace</div>
            <div className="mt-1 text-xs text-muted-foreground">{artifact.title}</div>
          </div>
          <Badge>{artifact.kind}</Badge>
        </div>
      </div>

      <div className="workbench-scrollbar flex-1 overflow-auto p-4">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="dashboard"><LineChart className="mr-1 h-3 w-3" />数据</TabsTrigger>
            <TabsTrigger value="audit"><FileText className="mr-1 h-3 w-3" />审计</TabsTrigger>
            <TabsTrigger value="actions" aria-label="Actions"><ListChecks className="mr-1 h-3 w-3" />动作</TabsTrigger>
            <TabsTrigger value="context"><BrainCircuit className="mr-1 h-3 w-3" />上下文</TabsTrigger>
            <TabsTrigger value="trace"><Activity className="mr-1 h-3 w-3" />Trace</TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard" className="space-y-3">
            <section className="rounded-lg border border-border bg-card p-3 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-primary">Account snapshot</p>
              <div className="mt-2 flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold">核心指标先行，复杂证据放到工作区</h3>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">聊天区保留判断；事实、假设、缺失数据、动作草稿和 trace 在这里承载。</p>
                </div>
                <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
              </div>
            </section>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Metric label="Spend" value={summary.spend ?? summary.total_spend} />
              <Metric label="CTR" value={summary.ctr} />
              <Metric label="CPC" value={summary.cpc} />
              <Metric label="CPA" value={summary.cpa ?? summary.cost_per_result} />
            </div>
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>花费对比</CardTitle>
              </CardHeader>
              <CardContent>
                {rows.length ? <MetricChart rows={rows} /> : <EmptyState text="读数完成后，这里展示核心趋势和对象对比。" />}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="audit">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>DecisionCard</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <WorkspaceNote title="判断" text={stringValue(decisionCard.judgement, "等待一次投手问题后生成明确判断。")} />
                <WorkspaceNote title="事实" text={listValue(decisionCard.facts, "有真实账户数据时列出关键事实；无数据时保持为空。")} />
                <WorkspaceNote title="假设 / 缺失" text={`${listValue(decisionCard.assumptions, "暂无经验假设。")} ${listValue(decisionCard.missing_data, "暂无缺失数据。")}`} />
                <WorkspaceNote title="下一步" text={stringValue(decisionCard.next_action, "等待 Agent 完成工具循环。")} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="actions">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>Action drafts</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2">
                  {approvalNotice ? (
                    <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{approvalNotice}</div>
                  ) : null}
                  {validationStatus ? (
                    <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">{validationStatus}</div>
                  ) : null}
                  {drafts.length ? (
                    drafts.map((draft) => (
                      <DraftCard
                        key={draft.draft_id}
                        draft={draft}
                        approved={approvedDraftIds.includes(draft.action_id || draft.draft_id)}
                        isApproving={approvingDraftId === (draft.action_id || draft.draft_id)}
                        onApprove={onApproveDraft}
                      />
                    ))
                  ) : (
                    <WorkspaceNote title="Draft" text={listValue(decisionCard.draft_actions, "No action draft was generated this turn.")} />
                  )}
                  <WorkspaceNote title="Execution boundary" text="Approve records approval only. Execution is disabled in the draft-only demo." />
                </div>
              </CardContent>
            </Card>
          </TabsContent>


          <TabsContent value="context" className="space-y-3">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>Context budget</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <WorkspaceNote title="Estimated input" text={`${stringValue(contextManifest.estimated_input_tokens, "-")} / ${stringValue(contextManifest.input_budget_tokens, "36000")} tokens`} />
                  <WorkspaceNote title="Actual usage" text={`in ${stringValue(contextManifest.actual_input_tokens, "-")} / out ${stringValue(contextManifest.actual_output_tokens, "-")}`} />
                  <WorkspaceNote title="Recent window" text={`${stringValue(contextManifest.recent_message_count, "0")} messages / ${stringValue(contextManifest.recent_rounds_limit, "5")} rounds`} />
                  <WorkspaceNote title="Summary + Memory" text={`${stringValue(contextManifest.summary_tokens, "0")} + ${stringValue(contextManifest.memory_tokens, "0")} tokens`} />
                </div>
                <WorkspaceNote title="Active Skills" text={listValue(contextManifest.active_skill_ids, "No active Skill in this task.")} />
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>Current task</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <WorkspaceNote title="Goal" text={stringValue(taskState.goal, "No task goal yet.")} />
                <WorkspaceNote title="Progress" text={formatProgress(taskState.progress)} />
                <WorkspaceNote title="Status" text={`${stringValue(taskState.status, "active")} / task ${stringValue(taskState.task_id, "-")}`} />
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>Account freshness</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-muted-foreground">
                <WorkspaceNote title="Account cache" text={`${stringValue(accountContext.name, stringValue(accountContext.account_id, "No account selected"))}\n${stringValue(accountContext.freshness, "not loaded")} / as_of ${stringValue(accountContext.as_of, "-")}`} />
                <WorkspaceNote title="Source tools" text={listValue(accountContext.source_tools, "No cached account evidence yet.")} />
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>Long-term Memory</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {memorySaved.length ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">Saved {memorySaved.length} Memory item(s) after this turn.</div> : null}
                {memories.length ? memories.map((memory) => (
                  <div key={memory.id} className="rounded-lg border border-border bg-background p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge>{memory.kind || "memory"}</Badge>
                          <span className="text-xs text-muted-foreground">{memory.scope_type || "scope"} / {memory.status || "active"}</span>
                        </div>
                        <p className="mt-2 text-xs leading-5 text-foreground">{memory.content}</p>
                        {memory.status === "candidate" ? (
                          <div className="mt-2 flex gap-2">
                            <Button type="button" size="sm" variant="outline" disabled={updatingMemoryId === memory.id} onClick={() => onConfirmMemory?.(memory.id)}>
                              Confirm
                            </Button>
                            <Button type="button" size="sm" variant="ghost" disabled={updatingMemoryId === memory.id} onClick={() => onRejectMemory?.(memory.id)}>
                              Ignore
                            </Button>
                          </div>
                        ) : null}
                      </div>
                      <Button type="button" variant="ghost" size="icon" disabled={deletingMemoryId === memory.id} onClick={() => onDeleteMemory?.(memory.id)} aria-label={`Delete memory ${memory.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )) : <WorkspaceNote title="Memory" text="No long-term memory yet. Explicit preferences, habits, account strategy, and confirmed decisions are stored here." />}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="trace" className="space-y-2">
            <WorkspaceNote title="运行摘要" text={routeAssetSummary} />
            {trace.length ? (
              trace.map((item) => (
                <div key={item.id} className="relative rounded-lg border border-border bg-card p-3 shadow-sm">
                  <div className="flex items-center justify-between gap-3">
                    <strong className="text-sm">{item.title}</strong>
                    <Badge>{item.status || "done"}</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                </div>
              ))
            ) : (
              <EmptyState text="发送问题后，这里展示 Agent 调用了哪些工具以及工具返回了什么。" />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </aside>
  );
}

function formatProgress(value: unknown) {
  if (!value || typeof value !== "object") return "No progress recorded yet.";
  const progress = value as ApiRecord;
  const recent = Array.isArray(progress.recent) ? progress.recent : [];
  const last = recent.length ? (recent[recent.length - 1] as ApiRecord) : {};
  return [
    `Turn count: ${progress.turn_count ?? 0}`,
    `Next step: ${stringValue(progress.next_step, "not set")}`,
    `Blocker: ${stringValue(progress.blocker_summary, "none")}`,
    `Last user goal: ${stringValue(last.user, "not recorded")}`,
  ].join("\n");
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <Card className="shadow-none">
      <CardContent className="p-3">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-2 text-xl font-semibold tracking-tight">{value == null || value === "" ? "-" : compactNumber(value)}</div>
      </CardContent>
    </Card>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border bg-muted/35 p-4 text-sm leading-6 text-muted-foreground">{text}</div>;
}

function WorkspaceNote({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="text-sm font-medium">{title}</div>
      <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{text}</p>
    </div>
  );
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function listValue(value: unknown, fallback: string) {
  if (!Array.isArray(value) || !value.length) return fallback;
  return value.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join("\n");
}

function DraftCard({
  draft,
  approved,
  isApproving,
  onApprove,
}: {
  draft: AgentDraft;
  approved: boolean;
  isApproving: boolean;
  onApprove?: (draft: AgentDraft) => void;
}) {
  const preflight = draft.preflight || {};
  const preflightResult = stringValue(preflight.result, "not run");
  const canApprove = Boolean(draft.action_id) && !approved && !isApproving && Boolean(onApprove);
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">{draft.target_name || `${draft.target_level || "target"} ${draft.target_id || ""}`}</p>
          <p className="mt-1 text-xs text-muted-foreground">Draft {draft.draft_id}</p>
        </div>
        <Badge className={approved ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "bg-background"}>{approved ? "approved" : draft.status || "draft"}</Badge>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-muted-foreground">
        <p><span className="font-medium text-foreground">Evidence:</span> {draft.evidence || "No evidence text returned."}</p>
        <p><span className="font-medium text-foreground">Recommendation:</span> {draft.recommendation || "No recommendation text returned."}</p>
        <p><span className="font-medium text-foreground">Risk:</span> {draft.risk_level || "not specified"}</p>
        <p><span className="font-medium text-foreground">Preflight:</span> {preflightResult}</p>
      </div>
      <Button type="button" variant="outline" className="mt-3 w-full" disabled={!canApprove} onClick={() => onApprove?.(draft)}>
        {approved ? "Approved" : isApproving ? "Approving" : "Approve draft"}
      </Button>
      {!draft.action_id ? <p className="mt-2 text-xs text-amber-700">No lifecycle action id; approval is unavailable.</p> : null}
    </div>
  );
}
