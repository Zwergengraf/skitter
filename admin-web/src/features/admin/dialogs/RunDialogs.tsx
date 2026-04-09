import type { MutableRefObject, ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AgentJobDetail, RunTraceDetail, SessionDetail, ToolRunListItem } from "@/lib/types";
import { formatCurrency, formatJsonPreview, formatNumber, formatRelativeTime } from "@/lib/utils";

type SessionTimelineItem =
  | { type: "message"; id: string; created_at: string; data: SessionDetail["messages"][number] }
  | { type: "tool"; id: string; created_at: string; data: SessionDetail["tool_runs"][number] };

type AgentJobDetailDialogProps = {
  selectedAgentJobId: string | null;
  setSelectedAgentJobId: (value: string | null) => void;
  selectedAgentJobLoading: boolean;
  selectedAgentJobError: string | null;
  selectedAgentJob: AgentJobDetail | null;
  formatDuration: (durationMs?: number | null) => string;
  computeAgentJobDurationMs: (job: AgentJobDetail) => number | null;
  formatFullJson: (value: unknown) => string;
  extractAgentJobTranscript: (job: AgentJobDetail | null) => Array<{ role: string; content: string }>;
};

export function AgentJobDetailDialog({
  selectedAgentJobId,
  setSelectedAgentJobId,
  selectedAgentJobLoading,
  selectedAgentJobError,
  selectedAgentJob,
  formatDuration,
  computeAgentJobDurationMs,
  formatFullJson,
  extractAgentJobTranscript,
}: AgentJobDetailDialogProps) {
  if (!selectedAgentJobId) {
    return null;
  }

  return (
    <Dialog open={Boolean(selectedAgentJobId)} onOpenChange={(open) => !open && setSelectedAgentJobId(null)}>
      <DialogContent className="w-[98vw] max-w-[1700px] max-h-[92vh] overflow-hidden p-0">
        <div className="border-b border-border p-6">
          <DialogHeader>
            <DialogTitle>Background Job Detail</DialogTitle>
            <DialogDescription>Full execution details for job `{selectedAgentJobId}`.</DialogDescription>
          </DialogHeader>
        </div>
        {selectedAgentJobLoading ? (
          <div className="p-6 text-sm text-mutedForeground">Loading background job detail...</div>
        ) : selectedAgentJobError ? (
          <div className="p-6 text-sm text-mutedForeground">{selectedAgentJobError}</div>
        ) : selectedAgentJob ? (
          <>
            <div className="grid gap-4 border-b border-border p-6 md:grid-cols-5">
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Status</p>
                <div className="mt-2">
                  <Badge
                    variant={
                      selectedAgentJob.status === "failed" || selectedAgentJob.status === "cancelled"
                        ? "danger"
                        : selectedAgentJob.status === "timeout"
                          ? "warning"
                          : selectedAgentJob.status === "running"
                            ? "secondary"
                            : selectedAgentJob.status === "queued"
                              ? "warning"
                              : "success"
                    }
                  >
                    {selectedAgentJob.status}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-mutedForeground">
                  Duration: {formatDuration(computeAgentJobDurationMs(selectedAgentJob))}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Model</p>
                <p className="mt-2 text-sm">{selectedAgentJob.model ?? "—"}</p>
                <p className="mt-1 text-xs text-mutedForeground">{selectedAgentJob.kind}</p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Usage</p>
                <p className="mt-2 text-sm">{formatNumber(selectedAgentJob.total_tokens ?? 0)} tokens</p>
                <p className="mt-1 text-xs text-mutedForeground">
                  {formatNumber(selectedAgentJob.tool_calls_used ?? 0)} tools · {formatCurrency(selectedAgentJob.cost ?? 0)}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Target</p>
                <p className="mt-2 text-sm">
                  {selectedAgentJob.target_scope_type}:{selectedAgentJob.target_scope_id}
                </p>
                <p className="mt-1 text-xs text-mutedForeground">
                  {selectedAgentJob.target_origin ?? "—"} · {selectedAgentJob.target_destination_id ?? "—"}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Delivery</p>
                {selectedAgentJob.delivery_error ? (
                  <Badge className="mt-2" variant="danger">
                    failed
                  </Badge>
                ) : selectedAgentJob.delivered_at ? (
                  <Badge className="mt-2" variant="success">
                    delivered
                  </Badge>
                ) : (
                  <Badge className="mt-2" variant="secondary">
                    pending
                  </Badge>
                )}
                <p className="mt-2 text-xs text-mutedForeground">
                  {selectedAgentJob.delivered_at ? formatRelativeTime(selectedAgentJob.delivered_at) : "Not delivered yet"}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4 md:col-span-5">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Run ID</p>
                <p className="mt-2 text-sm font-mono">{selectedAgentJob.run_id}</p>
              </div>
            </div>
            {(selectedAgentJob.error || selectedAgentJob.delivery_error) && (
              <div className="border-b border-border px-6 py-4 text-sm">
                {selectedAgentJob.error ? <p className="text-foreground">Execution error: {selectedAgentJob.error}</p> : null}
                {selectedAgentJob.delivery_error ? (
                  <p className="text-foreground">Delivery error: {selectedAgentJob.delivery_error}</p>
                ) : null}
              </div>
            )}
            <div className="grid min-h-0 flex-1 gap-4 p-6 md:grid-cols-3">
              <div className="min-h-0">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Payload</p>
                <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <pre className="text-xs text-foreground whitespace-pre-wrap">{formatFullJson(selectedAgentJob.payload)}</pre>
                </ScrollArea>
              </div>
              <div className="min-h-0">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Limits</p>
                <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <pre className="text-xs text-foreground whitespace-pre-wrap">{formatFullJson(selectedAgentJob.limits)}</pre>
                </ScrollArea>
              </div>
              <div className="min-h-0">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Result</p>
                <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <pre className="text-xs text-foreground whitespace-pre-wrap">{formatFullJson(selectedAgentJob.result)}</pre>
                </ScrollArea>
              </div>
            </div>
            <div className="grid gap-4 border-t border-border px-6 py-4 md:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Worker transcript</p>
                <ScrollArea className="mt-2 h-[30vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <div className="space-y-3">
                    {extractAgentJobTranscript(selectedAgentJob).length ? (
                      extractAgentJobTranscript(selectedAgentJob).map((turn, index) => (
                        <div key={`${turn.role}-${index}`} className="rounded-xl border border-border bg-card p-3">
                          <p className="text-[11px] uppercase tracking-[0.2em] text-mutedForeground">{turn.role}</p>
                          <pre className="mt-2 text-xs text-foreground whitespace-pre-wrap">{turn.content}</pre>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-mutedForeground">No transcript captured.</p>
                    )}
                  </div>
                </ScrollArea>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Tool runs</p>
                <ScrollArea className="mt-2 h-[30vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <div className="space-y-3">
                    {selectedAgentJob.tool_runs.length ? (
                      selectedAgentJob.tool_runs.map((tool) => (
                        <div key={tool.id} className="rounded-xl border border-border bg-card p-3">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-semibold">{tool.tool}</p>
                            <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>{tool.status}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-mutedForeground">{formatRelativeTime(tool.created_at)}</p>
                          <div className="mt-2 grid gap-2 md:grid-cols-2">
                            <pre className="rounded-lg border border-border bg-muted/40 p-2 text-[11px] text-mutedForeground whitespace-pre-wrap">
                              {formatJsonPreview(tool.input, 800)}
                            </pre>
                            <pre className="rounded-lg border border-border bg-muted/40 p-2 text-[11px] text-mutedForeground whitespace-pre-wrap">
                              {formatJsonPreview(tool.output, 800)}
                            </pre>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-mutedForeground">No tool runs recorded for this job yet.</p>
                    )}
                  </div>
                </ScrollArea>
              </div>
            </div>
          </>
        ) : (
          <div className="p-6 text-sm text-mutedForeground">Background job not found.</div>
        )}
        <div className="flex justify-end border-t border-border p-4">
          <Button variant="outline" onClick={() => setSelectedAgentJobId(null)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

type ToolRunDetailDialogProps = {
  selectedToolRun: ToolRunListItem | null;
  setSelectedToolRun: (value: ToolRunListItem | null) => void;
  showToolRunReasoning: boolean;
  toolRunReasoning: (tool: ToolRunListItem) => string[];
  formatFullJson: (value: unknown) => string;
  renderUser: (userId: string) => ReactNode;
  setSelectedRunId: (value: string | null) => void;
};

export function ToolRunDetailDialog({
  selectedToolRun,
  setSelectedToolRun,
  showToolRunReasoning,
  toolRunReasoning,
  formatFullJson,
  renderUser,
  setSelectedRunId,
}: ToolRunDetailDialogProps) {
  if (!selectedToolRun) {
    return null;
  }

  return (
    <Dialog open={Boolean(selectedToolRun)} onOpenChange={(open) => !open && setSelectedToolRun(null)}>
      <DialogContent className="w-[98vw] max-w-[1700px] max-h-[92vh] overflow-hidden p-0">
        <div className="border-b border-border p-6">
          <DialogHeader>
            <DialogTitle>Tool Run Details</DialogTitle>
            <DialogDescription>Full input and output payload for `{selectedToolRun.tool}`.</DialogDescription>
          </DialogHeader>
        </div>
        <div className="grid gap-4 border-b border-border p-6 md:grid-cols-6">
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Tool</p>
            <p className="mt-2 text-sm font-semibold">{selectedToolRun.tool}</p>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Status</p>
            <div className="mt-2">
              <Badge
                variant={
                  selectedToolRun.status === "pending"
                    ? "warning"
                    : selectedToolRun.status === "running"
                      ? "secondary"
                      : selectedToolRun.status === "failed"
                        ? "danger"
                        : "success"
                }
              >
                {selectedToolRun.status}
              </Badge>
            </div>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Requested by</p>
            <div className="mt-2">{renderUser(selectedToolRun.requested_by)}</div>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Created</p>
            <p className="mt-2 text-sm">{formatRelativeTime(selectedToolRun.created_at)}</p>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Executor</p>
            <p className="mt-2 text-sm">{selectedToolRun.executor_id ?? "—"}</p>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Run</p>
            {selectedToolRun.run_id ? (
              <button
                className="mt-2 text-sm text-primary underline-offset-4 hover:underline"
                onClick={() => setSelectedRunId(selectedToolRun.run_id ?? null)}
              >
                Open run detail
              </button>
            ) : (
              <p className="mt-2 text-sm text-mutedForeground">Unavailable</p>
            )}
          </div>
        </div>
        <div className="grid min-h-0 flex-1 gap-4 p-6 md:grid-cols-2">
          <div className="min-h-0">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input</p>
            <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
              <pre className="text-xs text-foreground whitespace-pre-wrap">{formatFullJson(selectedToolRun.input)}</pre>
            </ScrollArea>
          </div>
          <div className="min-h-0">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
            <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
              <pre className="text-xs text-foreground whitespace-pre-wrap">{formatFullJson(selectedToolRun.output)}</pre>
            </ScrollArea>
          </div>
          {showToolRunReasoning && toolRunReasoning(selectedToolRun).length ? (
            <div className="min-h-0 md:col-span-2">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Reasoning</p>
              <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                <pre className="text-xs text-foreground whitespace-pre-wrap">{toolRunReasoning(selectedToolRun).join("\n\n")}</pre>
              </ScrollArea>
            </div>
          ) : null}
        </div>
        <div className="flex justify-end border-t border-border p-4">
          <Button variant="outline" onClick={() => setSelectedToolRun(null)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

type RunDetailDialogProps = {
  selectedRunId: string | null;
  setSelectedRunId: (value: string | null) => void;
  runDetailLoading: boolean;
  runDetailError: string | null;
  runDetail: RunTraceDetail | null;
  formatDuration: (durationMs?: number | null) => string;
  formatFullJson: (value: unknown) => string;
  userLabelFor: (userId: string) => string;
  showRunReasoning: boolean;
  setShowRunReasoning: (value: boolean) => void;
  runDetailReasoning: string[];
};

export function RunDetailDialog({
  selectedRunId,
  setSelectedRunId,
  runDetailLoading,
  runDetailError,
  runDetail,
  formatDuration,
  formatFullJson,
  userLabelFor,
  showRunReasoning,
  setShowRunReasoning,
  runDetailReasoning,
}: RunDetailDialogProps) {
  if (!selectedRunId) {
    return null;
  }

  return (
    <Dialog open={Boolean(selectedRunId)} onOpenChange={(open) => !open && setSelectedRunId(null)}>
      <DialogContent className="max-w-7xl w-[95vw] max-h-[92vh] overflow-hidden p-0">
        <div className="border-b border-border p-6">
          <DialogHeader>
            <DialogTitle>Run Detail</DialogTitle>
            <DialogDescription>
              Unified execution trace for this request: model, tools, approvals, limits, and result.
            </DialogDescription>
          </DialogHeader>
        </div>
        {runDetailLoading ? (
          <div className="p-6 text-sm text-mutedForeground">Loading run detail...</div>
        ) : runDetailError ? (
          <div className="p-6 text-sm text-mutedForeground">{runDetailError}</div>
        ) : runDetail ? (
          <div className="min-h-0 flex-1 overflow-hidden p-6">
            <div className="grid gap-4 md:grid-cols-4">
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Status</p>
                <div className="mt-2">
                  <Badge
                    variant={
                      runDetail.run.status === "failed"
                        ? "danger"
                        : runDetail.run.status === "limited"
                          ? "warning"
                          : "success"
                    }
                  >
                    {runDetail.run.status}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-mutedForeground">Duration: {formatDuration(runDetail.run.duration_ms)}</p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Model</p>
                <p className="mt-2 text-sm">{runDetail.run.model ?? "—"}</p>
                <p className="mt-1 text-xs text-mutedForeground">{runDetail.run.origin}</p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Tokens</p>
                <p className="mt-2 text-sm">{formatNumber(runDetail.run.total_tokens ?? 0)} total</p>
                <p className="mt-1 text-xs text-mutedForeground">
                  In {formatNumber(runDetail.run.input_tokens ?? 0)} · Out {formatNumber(runDetail.run.output_tokens ?? 0)}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Cost & Tools</p>
                <p className="mt-2 text-sm">{formatCurrency(runDetail.run.cost ?? 0)}</p>
                <p className="mt-1 text-xs text-mutedForeground">{formatNumber(runDetail.run.tool_calls ?? 0)} tool call(s)</p>
              </div>
            </div>
            {(runDetail.run.error || runDetail.run.limit_reason) && (
              <div className="mt-4 rounded-2xl border border-border bg-muted/30 p-4 text-sm">
                {runDetail.run.error ? <p className="text-foreground">Error: {runDetail.run.error}</p> : null}
                {runDetail.run.limit_reason ? (
                  <p className="text-foreground">
                    Limit: {runDetail.run.limit_reason}
                    {runDetail.limit_detail ? ` · ${runDetail.limit_detail}` : ""}
                  </p>
                ) : null}
              </div>
            )}
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <div className="md:col-span-1">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Events</p>
                <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                  <div className="space-y-3">
                    {runDetail.events.length ? (
                      runDetail.events.map((event) => (
                        <div key={event.id} className="rounded-xl border border-border bg-card p-3">
                          <p className="text-xs font-semibold">{event.event_type}</p>
                          <p className="mt-1 text-[11px] text-mutedForeground">{formatRelativeTime(event.created_at)}</p>
                          <pre className="mt-2 text-[11px] text-mutedForeground whitespace-pre-wrap">
                            {formatJsonPreview(event.payload, 1200)}
                          </pre>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-mutedForeground">No events recorded.</p>
                    )}
                  </div>
                </ScrollArea>
              </div>
              <div className="md:col-span-2 grid gap-4">
                <div className="flex items-center justify-end">
                  <div className="flex items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2">
                    <span className="text-xs text-mutedForeground">Show reasoning</span>
                    <Switch checked={showRunReasoning} onCheckedChange={setShowRunReasoning} />
                  </div>
                </div>
                {showRunReasoning && runDetailReasoning.length ? (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Reasoning</p>
                    <ScrollArea className="mt-2 h-[20vh] rounded-2xl border border-border bg-muted/40 p-3">
                      <pre className="text-xs text-foreground whitespace-pre-wrap">{runDetailReasoning.join("\n\n")}</pre>
                    </ScrollArea>
                  </div>
                ) : null}
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input</p>
                    <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                      <pre className="text-xs text-foreground whitespace-pre-wrap">{runDetail.input_text || "—"}</pre>
                    </ScrollArea>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
                    <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                      <pre className="text-xs text-foreground whitespace-pre-wrap">{runDetail.output_text || "—"}</pre>
                    </ScrollArea>
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Tool runs in this request</p>
                  <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                    <div className="space-y-3">
                      {runDetail.tool_runs.length ? (
                        runDetail.tool_runs.map((tool) => (
                          <div key={tool.id} className="rounded-xl border border-border bg-card p-3">
                            <div className="flex items-center justify-between">
                              <p className="text-sm font-semibold">{tool.tool}</p>
                              <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>{tool.status}</Badge>
                            </div>
                            <p className="mt-1 text-xs text-mutedForeground">
                              {formatRelativeTime(tool.created_at)} · Approved by {tool.approved_by ? userLabelFor(tool.approved_by) : "auto"} · Executor{" "}
                              {tool.executor_id ?? "—"}
                            </p>
                            <div className="mt-2 grid gap-2 md:grid-cols-2">
                              <pre className="rounded-lg border border-border bg-muted/40 p-2 text-[11px] text-mutedForeground whitespace-pre-wrap">
                                {formatFullJson(tool.input)}
                              </pre>
                              <pre className="rounded-lg border border-border bg-muted/40 p-2 text-[11px] text-mutedForeground whitespace-pre-wrap">
                                {formatFullJson(tool.output)}
                              </pre>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className="text-xs text-mutedForeground">No tool runs linked to this request.</p>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              </div>
            </div>
          </div>
        ) : null}
        <div className="flex justify-end border-t border-border p-4">
          <Button variant="outline" onClick={() => setSelectedRunId(null)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

type SessionDetailDialogProps = {
  selectedSessionId: string | null;
  closeSessionDetail: () => void;
  sessionDetailLoading: boolean;
  sessionDetailError: string | null;
  sessionDetail: SessionDetail | null;
  profileLabelFor: (userId: string | null | undefined, profileId?: string | null, fallbackSlug?: string | null) => string;
  renderUser: (userId: string) => ReactNode;
  showSessionReasoning: boolean;
  setShowSessionReasoning: (value: boolean) => void;
  sessionTimeline: SessionTimelineItem[];
  messageReasoning: (meta: Record<string, unknown> | undefined) => string[];
  userLabelFor: (userId: string) => string;
  sessionMessagesEndRef: MutableRefObject<HTMLDivElement | null>;
  summaryStatusVariant: (detail: SessionDetail) => "secondary" | "warning" | "success" | "danger";
  summaryStatusLabel: (detail: SessionDetail) => string;
  summaryStatusHint: (detail: SessionDetail) => string;
};

export function SessionDetailDialog({
  selectedSessionId,
  closeSessionDetail,
  sessionDetailLoading,
  sessionDetailError,
  sessionDetail,
  profileLabelFor,
  renderUser,
  showSessionReasoning,
  setShowSessionReasoning,
  sessionTimeline,
  messageReasoning,
  userLabelFor,
  sessionMessagesEndRef,
  summaryStatusVariant,
  summaryStatusLabel,
  summaryStatusHint,
}: SessionDetailDialogProps) {
  if (!selectedSessionId) {
    return null;
  }

  return (
    <Dialog open={Boolean(selectedSessionId)} onOpenChange={(open) => !open && closeSessionDetail()}>
      <DialogContent className="max-w-7xl w-[98vw] max-h-[92vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>Session detail</DialogTitle>
          <DialogDescription>Review conversation history, tool runs, and metadata for this session.</DialogDescription>
        </DialogHeader>
        {sessionDetailLoading ? (
          <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
            Loading session detail...
          </div>
        ) : sessionDetailError ? (
          <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
            {sessionDetailError}
          </div>
        ) : sessionDetail ? (
          <div className="grid gap-6 overflow-hidden">
            <div className="grid gap-4 md:grid-cols-4">
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Session</p>
                <p className="mt-2 text-sm font-semibold">{sessionDetail.id}</p>
                <p className="mt-1 text-xs text-mutedForeground">Status: {sessionDetail.status}</p>
                <p className="mt-1 text-xs text-mutedForeground">
                  Profile: {profileLabelFor(sessionDetail.user_id, sessionDetail.agent_profile_id, sessionDetail.agent_profile_slug)}
                </p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">User</p>
                <div className="mt-2">{renderUser(sessionDetail.user_id)}</div>
                <p className="mt-1 text-xs text-mutedForeground">Last active {formatRelativeTime(sessionDetail.last_active_at)}</p>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Usage</p>
                <div className="mt-2 space-y-1 text-xs text-mutedForeground">
                  <p>Model: {sessionDetail.last_model ?? "—"}</p>
                  <p>Context: {formatNumber(sessionDetail.last_input_tokens ?? 0)} tokens</p>
                  <p>Last output: {formatNumber(sessionDetail.last_output_tokens ?? 0)} tokens</p>
                  <p>Total tokens: {formatNumber(sessionDetail.total_tokens ?? 0)}</p>
                  <p>Total cost: {formatCurrency(sessionDetail.total_cost ?? 0)}</p>
                </div>
              </div>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Archive Summary</p>
                <div className="mt-2 space-y-2 text-xs text-mutedForeground">
                  <div className="flex items-center gap-2">
                    <span className="text-foreground/80">Status</span>
                    <Badge variant={summaryStatusVariant(sessionDetail)}>{summaryStatusLabel(sessionDetail)}</Badge>
                  </div>
                  <p className="leading-relaxed">{summaryStatusHint(sessionDetail)}</p>
                  <div className="space-y-1 rounded-2xl bg-muted/40 px-3 py-2">
                    <p>
                      Attempts: <span className="text-foreground">{sessionDetail.summary_attempts ?? 0}</span>
                    </p>
                    <p>
                      Next retry:{" "}
                      <span className="text-foreground">
                        {sessionDetail.summary_next_retry_at ? formatRelativeTime(sessionDetail.summary_next_retry_at) : "—"}
                      </span>
                    </p>
                    <p>
                      Finished:{" "}
                      <span className="text-foreground">
                        {sessionDetail.summary_completed_at ? formatRelativeTime(sessionDetail.summary_completed_at) : "—"}
                      </span>
                    </p>
                    <p className="break-all">
                      File: <span className="text-foreground">{sessionDetail.summary_path ?? "—"}</span>
                    </p>
                  </div>
                  {sessionDetail.summary_last_error ? (
                    <div className="rounded-2xl border border-rose-200/60 bg-rose-500/5 px-3 py-2 text-rose-700 dark:border-rose-900/50 dark:text-rose-300">
                      <p className="text-[11px] uppercase tracking-[0.2em]">Last Error</p>
                      <p className="mt-1 whitespace-pre-wrap break-words">{sessionDetail.summary_last_error}</p>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
            <Tabs defaultValue="messages">
              <TabsList>
                <TabsTrigger value="messages">Messages</TabsTrigger>
                <TabsTrigger value="tools">Tool runs</TabsTrigger>
              </TabsList>
              <TabsContent value="messages">
                <div className="mb-3 flex items-center justify-end">
                  <div className="flex items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2">
                    <span className="text-xs text-mutedForeground">Show reasoning</span>
                    <Switch checked={showSessionReasoning} onCheckedChange={setShowSessionReasoning} />
                  </div>
                </div>
                <ScrollArea className="h-[60vh] md:h-[65vh] rounded-2xl border border-border bg-card p-4">
                  <div className="space-y-4">
                    {sessionTimeline.map((item) => {
                      if (item.type === "message") {
                        const message = item.data;
                        const reasoning = messageReasoning(message.meta);
                        return (
                          <div key={item.id} className="rounded-2xl border border-border bg-muted/40 p-4">
                            <div className="flex items-center justify-between text-xs text-mutedForeground">
                              <span className="uppercase tracking-[0.2em]">{message.role}</span>
                              <span>{formatRelativeTime(message.created_at)}</span>
                            </div>
                            {showSessionReasoning && reasoning.length ? (
                              <div className="mt-2 rounded-2xl border border-border bg-card p-3">
                                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Reasoning</p>
                                <pre className="mt-2 text-xs text-mutedForeground whitespace-pre-wrap">{reasoning.join("\n\n")}</pre>
                              </div>
                            ) : null}
                            <p className="mt-2 text-sm text-foreground whitespace-pre-wrap">{message.content}</p>
                          </div>
                        );
                      }
                      const tool = item.data;
                      return (
                        <div key={item.id} className="rounded-2xl border border-border bg-card p-4">
                          <div className="flex items-center justify-between text-xs text-mutedForeground">
                            <span className="uppercase tracking-[0.2em]">Tool · {tool.tool}</span>
                            <span>{formatRelativeTime(tool.created_at)}</span>
                          </div>
                          <div className="mt-2 flex items-center gap-2 text-xs text-mutedForeground">
                            <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>{tool.status}</Badge>
                            <span>Approved by {tool.approved_by ? userLabelFor(tool.approved_by) : "auto"}</span>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
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
                        </div>
                      );
                    })}
                    <div ref={sessionMessagesEndRef} />
                  </div>
                </ScrollArea>
              </TabsContent>
              <TabsContent value="tools">
                <ScrollArea className="h-[60vh] md:h-[65vh] rounded-2xl border border-border bg-card p-4">
                  <div className="space-y-4">
                    {sessionDetail.tool_runs.length ? (
                      sessionDetail.tool_runs.map((tool) => (
                        <div key={tool.id} className="rounded-2xl border border-border bg-muted/40 p-4">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-semibold">{tool.tool}</p>
                            <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>{tool.status}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-mutedForeground">
                            {formatRelativeTime(tool.created_at)} · Approved by {tool.approved_by ? userLabelFor(tool.approved_by) : "auto"}
                          </p>
                          <div className="mt-3 grid gap-4 md:grid-cols-2">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input</p>
                              <pre className="mt-2 rounded-2xl border border-border bg-card p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                                {formatJsonPreview(tool.input)}
                              </pre>
                            </div>
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
                              <pre className="mt-2 rounded-2xl border border-border bg-card p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                                {formatJsonPreview(tool.output)}
                              </pre>
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                        No tool runs in this session.
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={closeSessionDetail}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
