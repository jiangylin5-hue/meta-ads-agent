"use client";

import { Bot, ChevronRight, Database, Facebook, Gauge, History, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { copy } from "@/lib/i18n/messages";
import type { MetaAccount } from "@/lib/types/api";
import { cn } from "@/lib/utils";

type Props = {
  accounts: MetaAccount[];
  selectedAccountId: string;
  metaStatus?: string;
  isLoading: boolean;
  onSelectAccount: (accountId: string) => void;
  onRefresh: () => void;
  onQuickTask: (message: string) => void;
};

export function AccountSidebar({ accounts, selectedAccountId, metaStatus, isLoading, onSelectAccount, onRefresh, onQuickTask }: Props) {
  const selectedAccount = accounts.find((account) => (account.id || account.account_id) === selectedAccountId);

  return (
    <aside className="flex min-h-0 flex-col border-r border-border bg-[#fbfcfd] max-lg:border-b max-lg:border-r-0">
      <div className="border-b border-border bg-card p-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground shadow-sm">A</div>
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight">{copy.appName}</div>
            <div className="truncate text-xs text-muted-foreground">Personal media buying cockpit</div>
          </div>
        </div>
      </div>

      <div className="workbench-scrollbar flex-1 space-y-4 overflow-auto p-4">
        <section className="rounded-lg border border-border bg-card p-3 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Current account</p>
              <h2 className="mt-1 truncate text-base font-semibold">{selectedAccount?.name || copy.noAccount}</h2>
              <p className="mt-1 truncate text-xs text-muted-foreground">{selectedAccountId || "Select an account before reading data"}</p>
            </div>
            <Button size="icon" variant="ghost" onClick={onRefresh} aria-label={copy.refreshAccounts}>
              <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
            </Button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <StatusTile icon={Facebook} label="Meta" value={metaStatus || copy.loadingMeta} />
            <StatusTile icon={ShieldCheck} label="Safety" value="Draft gated" />
          </div>
        </section>

        <Card className="shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2"><Database className="h-4 w-4" />账户列表</span>
              <Badge>{accounts.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
              {accounts.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">No accounts. Check META_ACCESS_TOKEN.</div>
              ) : (
                accounts.slice(0, 12).map((account) => {
                  const accountId = account.id || account.account_id || "";
                  return (
                    <button
                      key={accountId}
                      type="button"
                      onClick={() => onSelectAccount(accountId)}
                      className={cn(
                        "group w-full rounded-lg border border-border bg-background p-3 text-left transition-all hover:border-primary/50 hover:bg-card",
                        selectedAccountId === accountId && "border-primary bg-accent shadow-sm",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-sm font-medium">{account.name || accountId}</div>
                        <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2">
                        <span className="truncate text-xs text-muted-foreground">{accountId}</span>
                        <span className="text-xs text-muted-foreground">{account.currency || ""}</span>
                      </div>
                    </button>
                  );
                })
              )}
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Search className="h-4 w-4" />
              投手快捷任务
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {copy.quickTasks.map((task, index) => (
              <Button key={task} variant="outline" className="h-auto w-full justify-start gap-2 whitespace-normal text-left text-xs" onClick={() => onQuickTask(task)}>
                {index % 2 === 0 ? <Gauge className="h-3.5 w-3.5" /> : <History className="h-3.5 w-3.5" />}
                {task}
              </Button>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="border-t border-border p-4">
        <Badge className="gap-1">
          <Bot className="h-3 w-3" />
          Agent runtime
        </Badge>
      </div>
    </aside>
  );
}

function StatusTile({ icon: Icon, label, value }: { icon: typeof Facebook; label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-muted/35 p-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-1 truncate text-xs font-medium">{value}</div>
    </div>
  );
}
