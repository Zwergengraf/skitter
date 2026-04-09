import { SectionHeader } from "@/components/SectionHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PaginationFooter } from "@/features/admin/components/PaginationFooter";
import { StateMessage } from "@/features/admin/components/StateMessage";
import type { TableRange } from "@/features/admin/types";
import type { ToolRunListItem } from "@/lib/types";
import { formatJsonPreview, formatRelativeTime } from "@/lib/utils";

type ToolRunsViewProps = {
  toolRunToolFilter: string;
  onToolRunToolFilterChange: (value: string) => void;
  toolRunUserFilter: string;
  onToolRunUserFilterChange: (value: string) => void;
  toolRunExecutorFilter: string;
  onToolRunExecutorFilterChange: (value: string) => void;
  toolRunsRange: TableRange;
  onToolRunsRangeChange: (value: TableRange) => void;
  clearFilters: () => void;
  showToolRunReasoning: boolean;
  onShowToolRunReasoningChange: (value: boolean) => void;
  toolRunsLoading: boolean;
  toolRunsError: string | null;
  toolRunsData: ToolRunListItem[];
  visibleToolRuns: ToolRunListItem[];
  pagedToolRuns: ToolRunListItem[];
  toolRunsPage: number;
  toolRunsPageCount: number;
  onPreviousPage: () => void;
  onNextPage: () => void;
  toolRunTools: string[];
  toolRunUsers: string[];
  toolRunExecutors: string[];
  renderUser: (userId: string) => React.ReactNode;
  userLabelFor: (userId: string) => string;
  openSessionDetail: (sessionId: string) => void;
  setSelectedToolRun: (tool: ToolRunListItem) => void;
  setSelectedRunId: (runId: string | null) => void;
  toolRunReasoning: (tool: ToolRunListItem) => string[];
};

export function ToolRunsView({
  toolRunToolFilter,
  onToolRunToolFilterChange,
  toolRunUserFilter,
  onToolRunUserFilterChange,
  toolRunExecutorFilter,
  onToolRunExecutorFilterChange,
  toolRunsRange,
  onToolRunsRangeChange,
  clearFilters,
  showToolRunReasoning,
  onShowToolRunReasoningChange,
  toolRunsLoading,
  toolRunsError,
  toolRunsData,
  visibleToolRuns,
  pagedToolRuns,
  toolRunsPage,
  toolRunsPageCount,
  onPreviousPage,
  onNextPage,
  toolRunTools,
  toolRunUsers,
  toolRunExecutors,
  renderUser,
  userLabelFor,
  openSessionDetail,
  setSelectedToolRun,
  setSelectedRunId,
  toolRunReasoning,
}: ToolRunsViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader title="Tool runs" subtitle="Audit all tool activity and intervention points." />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Select value={toolRunToolFilter} onValueChange={onToolRunToolFilterChange}>
              <SelectTrigger className="w-52">
                <SelectValue placeholder="Filter by tool" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All tools</SelectItem>
                {toolRunTools.map((toolName) => (
                  <SelectItem key={toolName} value={toolName}>
                    {toolName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={toolRunUserFilter} onValueChange={onToolRunUserFilterChange}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Filter by user" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All users</SelectItem>
                {toolRunUsers.map((userId) => (
                  <SelectItem key={userId} value={userId}>
                    {userLabelFor(userId)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={toolRunExecutorFilter} onValueChange={onToolRunExecutorFilterChange}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Filter by executor" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All executors</SelectItem>
                {toolRunExecutors.map((executorId) => (
                  <SelectItem key={executorId} value={executorId}>
                    {executorId}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={toolRunsRange} onValueChange={(value) => onToolRunsRangeChange(value as TableRange)}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Timeframe" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="today">Today</SelectItem>
                <SelectItem value="week">This week</SelectItem>
                <SelectItem value="month">This month</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
            <div className="ml-auto flex items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2">
              <span className="text-xs text-mutedForeground">Show reasoning</span>
              <Switch checked={showToolRunReasoning} onCheckedChange={onShowToolRunReasoningChange} />
            </div>
          </div>
          {toolRunsLoading ? (
            <StateMessage>Loading tool runs...</StateMessage>
          ) : toolRunsError ? (
            <StateMessage>{toolRunsError}</StateMessage>
          ) : visibleToolRuns.length ? (
            pagedToolRuns.map((tool) => (
              <div
                key={tool.id}
                className="cursor-pointer rounded-2xl border border-border bg-card px-5 py-4 transition-colors hover:bg-muted/20"
                onClick={() => setSelectedToolRun(tool)}
              >
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-semibold">{tool.tool}</p>
                    <div className="mt-1 flex items-center gap-2 text-xs text-mutedForeground">
                      {renderUser(tool.requested_by)}
                      <span>· {formatRelativeTime(tool.created_at)}</span>
                    </div>
                  </div>
                  <Badge
                    variant={
                      tool.status === "pending"
                        ? "warning"
                        : tool.status === "running"
                          ? "secondary"
                          : tool.status === "failed"
                            ? "danger"
                            : "success"
                    }
                  >
                    {tool.status}
                  </Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedToolRun(tool);
                    }}
                  >
                    Details
                  </Button>
                </div>
                <div className="mt-4 grid gap-3 text-xs text-mutedForeground md:grid-cols-4">
                  <div>
                    <p className="uppercase tracking-[0.2em] text-mutedForeground">Approved by</p>
                    <p className="mt-1 text-sm text-foreground">{tool.approved_by ?? "—"}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-[0.2em] text-mutedForeground">Created</p>
                    <p className="mt-1 text-sm text-foreground">{formatRelativeTime(tool.created_at)}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-[0.2em] text-mutedForeground">Executor</p>
                    <p className="mt-1 text-sm text-foreground">{tool.executor_id ?? "—"}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-[0.2em] text-mutedForeground">Links</p>
                    <div className="mt-1 flex flex-col items-start gap-1">
                      <button
                        className="text-sm text-primary underline-offset-4 hover:underline"
                        onClick={(event) => {
                          event.stopPropagation();
                          openSessionDetail(tool.session_id);
                        }}
                      >
                        View session
                      </button>
                      {tool.run_id ? (
                        <button
                          className="text-sm text-primary underline-offset-4 hover:underline"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedRunId(tool.run_id ?? null);
                          }}
                        >
                          View run
                        </button>
                      ) : (
                        <span className="text-xs text-mutedForeground">Run id unavailable</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input</p>
                    <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                      {formatJsonPreview(tool.input)}
                    </pre>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
                    <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                      {formatJsonPreview(tool.output)}
                    </pre>
                  </div>
                </div>
                {showToolRunReasoning && toolRunReasoning(tool).length ? (
                  <div className="mt-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Reasoning</p>
                    <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                      {toolRunReasoning(tool).join("\n\n")}
                    </pre>
                  </div>
                ) : null}
              </div>
            ))
          ) : (
            <StateMessage>
              {toolRunsData.length ? "No tool runs match the selected filters and timeframe." : "No tool runs found."}
            </StateMessage>
          )}
          {!toolRunsLoading && !toolRunsError && visibleToolRuns.length ? (
            <PaginationFooter
              page={toolRunsPage}
              pageCount={toolRunsPageCount}
              pageSize={15}
              totalCount={visibleToolRuns.length}
              onPrevious={onPreviousPage}
              onNext={onNextPage}
            />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
