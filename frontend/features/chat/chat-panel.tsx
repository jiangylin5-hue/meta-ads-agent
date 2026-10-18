"use client";

import { BarChart3, FileCheck2, History, ListChecks, SendHorizonal, Sparkles } from "lucide-react";
import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/lib/i18n/messages";
import type { ChatMessage } from "@/lib/types/api";
import { cn } from "@/lib/utils";

type Props = {
  messages: ChatMessage[];
  isSending: boolean;
  pendingText?: string;
  hasMoreHistory?: boolean;
  isLoadingHistory?: boolean;
  onLoadOlder?: () => void;
  onSend: (message: string) => void;
};

export function ChatPanel({ messages, isSending, pendingText = "Agent 正在选择工具...", hasMoreHistory = false, isLoadingHistory = false, onLoadOlder, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || isSending) return;
    setDraft("");
    onSend(message);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <section className="flex min-h-0 flex-col bg-[#f8fafc] max-lg:min-h-[560px]">
      <div className="border-b border-border bg-card/85 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-primary" />
              AI 投手对话
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{copy.appSubtitle}</div>
          </div>
          <div className="hidden rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground sm:block">短答优先 · 证据进 Workspace</div>
        </div>
      </div>

      <div className="workbench-scrollbar flex-1 overflow-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {hasMoreHistory ? (
            <div className="flex justify-center">
              <Button type="button" variant="outline" size="sm" onClick={onLoadOlder} disabled={isLoadingHistory}>
                <History className="mr-2 h-4 w-4" />
                {isLoadingHistory ? "加载中" : "加载更早历史"}
              </Button>
            </div>
          ) : null}
          {messages.length === 0 ? <WelcomePanel onSend={onSend} /> : null}
          {messages.map((message) => (
            <div key={message.id} className={cn("flex gap-3", message.role === "user" ? "justify-end" : "justify-start")}>
              {message.role !== "user" ? <Avatar label="AI" /> : null}
              <div
                className={cn(
                  "max-w-[82%] rounded-lg border px-4 py-3 text-sm leading-6 shadow-sm",
                  message.role === "user"
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-card-foreground",
                )}
              >
                {message.content}
              </div>
              {message.role === "user" ? <Avatar label="You" muted /> : null}
            </div>
          ))}
          {isSending ? (
            <div className="flex items-center gap-3">
              <Avatar label="AI" />
              <div className="w-fit rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">{pendingText}</div>
            </div>
          ) : null}
        </div>
      </div>

      <form onSubmit={submit} className="border-t border-border bg-card/95 p-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-lg border border-border bg-background p-2 shadow-sm">
          <Textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={copy.askPlaceholder}
            className="max-h-40 min-h-12 flex-1 border-0 bg-transparent focus-visible:ring-0"
          />
          <Button type="submit" size="icon" className="mb-1" disabled={isSending || !draft.trim()} aria-label={copy.send}>
            <SendHorizonal className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </section>
  );
}

function WelcomePanel({ onSend }: { onSend: (message: string) => void }) {
  const tasks = [
    { icon: BarChart3, title: "账户读数", text: "今天这个账户怎么样？" },
    { icon: FileCheck2, title: "审计判断", text: "找一下浪费预算的地方" },
    { icon: ListChecks, title: "动作草稿", text: "把建议整理成待审批动作" },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-primary">Media buyer cockpit</p>
          <h1 className="mt-2 text-xl font-semibold tracking-tight">用一句话推进账户诊断、证据和动作</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">默认短答；需要展开时，Dashboard、审计和草稿会进入右侧 Workspace。</p>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {tasks.map((task) => (
          <button
            key={task.title}
            type="button"
            onClick={() => onSend(task.text)}
            className="rounded-lg border border-border bg-background p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent"
          >
            <task.icon className="h-4 w-4 text-primary" />
            <div className="mt-2 text-sm font-medium">{task.title}</div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">{task.text}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Avatar({ label, muted = false }: { label: string; muted?: boolean }) {
  return (
    <div
      className={cn(
        "mt-1 grid h-8 w-8 flex-none place-items-center rounded-lg text-[11px] font-semibold",
        muted ? "border border-border bg-muted text-muted-foreground" : "bg-primary text-primary-foreground",
      )}
    >
      {label}
    </div>
  );
}
