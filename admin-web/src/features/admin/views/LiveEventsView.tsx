import type { MutableRefObject } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { StateMessage } from "@/features/admin/components/StateMessage";
import { liveEventKindLabel, liveEventLevelVariant } from "@/features/admin/utils/liveEvents";
import type { AdminLiveEvent, ExecutorItem } from "@/lib/types";
import { formatJsonPreview, formatNumber, formatRelativeTime } from "@/lib/utils";

type LiveEventsViewProps = {
  liveEvents: AdminLiveEvent[];
  filteredLiveEvents: AdminLiveEvent[];
  liveEventKinds: string[];
  liveEventsLoading: boolean;
  liveEventsError: string | null;
  liveEventsPaused: boolean;
  onLiveEventsPausedChange: (value: boolean) => void;
  liveEventsAutoScroll: boolean;
  onLiveEventsAutoScrollChange: (value: boolean) => void;
  liveEventSearch: string;
  onLiveEventSearchChange: (value: string) => void;
  liveEventLevelFilter: string;
  onLiveEventLevelFilterChange: (value: string) => void;
  liveEventKindFilter: string;
  onLiveEventKindFilterChange: (value: string) => void;
  clearLiveEvents: () => void;
  openSessionDetail: (sessionId: string) => void;
  openRunDetail: (runId: string) => void;
  openAgentJobDetail: (jobId: string) => void;
  openExecutorDetail: (executor: ExecutorItem) => void;
  executorsData: ExecutorItem[];
  liveEventsEndRef: MutableRefObject<HTMLDivElement | null>;
};

export function LiveEventsView({
  liveEvents,
  filteredLiveEvents,
  liveEventKinds,
  liveEventsLoading,
  liveEventsError,
  liveEventsPaused,
  onLiveEventsPausedChange,
  liveEventsAutoScroll,
  onLiveEventsAutoScrollChange,
  liveEventSearch,
  onLiveEventSearchChange,
  liveEventLevelFilter,
  onLiveEventLevelFilterChange,
  liveEventKindFilter,
  onLiveEventKindFilterChange,
  clearLiveEvents,
  openSessionDetail,
  openRunDetail,
  openAgentJobDetail,
  openExecutorDetail,
  executorsData,
  liveEventsEndRef,
}: LiveEventsViewProps) {
  return (
    <div className="grid gap-8">
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Buffered events</p>
            <p className="mt-3 text-3xl font-semibold">{formatNumber(liveEvents.length)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Visible</p>
            <p className="mt-3 text-3xl font-semibold">{formatNumber(filteredLiveEvents.length)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Warnings</p>
            <p className="mt-3 text-3xl font-semibold">
              {formatNumber(liveEvents.filter((event) => event.level === "warning").length)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Errors</p>
            <p className="mt-3 text-3xl font-semibold">
              {formatNumber(liveEvents.filter((event) => event.level === "error").length)}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Live event stream</CardTitle>
              <CardDescription>
                Structured runtime activity from jobs, executors, approvals, prompts, schedules, and session finalization.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-sm text-mutedForeground">
                <span>Pause</span>
                <Switch checked={liveEventsPaused} onCheckedChange={onLiveEventsPausedChange} />
              </div>
              <div className="flex items-center gap-2 text-sm text-mutedForeground">
                <span>Auto-scroll</span>
                <Switch checked={liveEventsAutoScroll} onCheckedChange={onLiveEventsAutoScrollChange} />
              </div>
              <Button variant="outline" onClick={clearLiveEvents}>
                Clear view
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_220px_260px]">
            <Input
              value={liveEventSearch}
              onChange={(event) => onLiveEventSearchChange(event.target.value)}
              placeholder="Search message, IDs, transport, or JSON payload"
            />
            <Select value={liveEventLevelFilter} onValueChange={onLiveEventLevelFilterChange}>
              <SelectTrigger>
                <SelectValue placeholder="Level" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All levels</SelectItem>
                <SelectItem value="info">Info</SelectItem>
                <SelectItem value="success">Success</SelectItem>
                <SelectItem value="warning">Warning</SelectItem>
                <SelectItem value="error">Error</SelectItem>
              </SelectContent>
            </Select>
            <Select value={liveEventKindFilter} onValueChange={onLiveEventKindFilterChange}>
              <SelectTrigger>
                <SelectValue placeholder="Kind" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All event kinds</SelectItem>
                {liveEventKinds.map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {liveEventKindLabel(kind)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {liveEventsError ? <StateMessage tone="danger" compact>{liveEventsError}</StateMessage> : null}

          <ScrollArea className="h-[68vh] rounded-2xl border border-border">
            <div className="space-y-3 p-4">
              {liveEventsLoading ? (
                <StateMessage>Connecting to the live event stream...</StateMessage>
              ) : filteredLiveEvents.length ? (
                filteredLiveEvents.map((event) => {
                  const linkedExecutor = event.executor_id
                    ? executorsData.find((executor) => executor.id === event.executor_id) ?? null
                    : null;
                  return (
                    <div key={event.id} className="rounded-2xl border border-border bg-card p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={liveEventLevelVariant(event.level)}>{event.level}</Badge>
                            <Badge variant="outline">{liveEventKindLabel(event.kind)}</Badge>
                            <span className="text-xs text-mutedForeground">{formatRelativeTime(event.created_at)}</span>
                          </div>
                          <div>
                            <p className="text-sm font-semibold">{event.title}</p>
                            <p className="mt-1 text-sm text-mutedForeground">{event.message}</p>
                          </div>
                        </div>
                        <span className="text-xs text-mutedForeground">{new Date(event.created_at).toLocaleString()}</span>
                      </div>

                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        {event.session_id ? <Badge variant="outline">session: {event.session_id}</Badge> : null}
                        {event.run_id ? <Badge variant="outline">run: {event.run_id}</Badge> : null}
                        {event.job_id ? <Badge variant="outline">job: {event.job_id}</Badge> : null}
                        {event.tool_run_id ? <Badge variant="outline">tool: {event.tool_run_id}</Badge> : null}
                        {event.executor_id ? <Badge variant="outline">executor: {event.executor_id}</Badge> : null}
                        {event.user_id ? <Badge variant="outline">user: {event.user_id}</Badge> : null}
                        {event.transport ? <Badge variant="outline">transport: {event.transport}</Badge> : null}
                      </div>

                      {(event.session_id || event.run_id || event.job_id || linkedExecutor) ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {event.session_id ? (
                            <Button size="sm" variant="outline" onClick={() => openSessionDetail(event.session_id ?? "")}>
                              Open session
                            </Button>
                          ) : null}
                          {event.run_id ? (
                            <Button size="sm" variant="outline" onClick={() => openRunDetail(event.run_id ?? "")}>
                              Open run
                            </Button>
                          ) : null}
                          {event.job_id ? (
                            <Button size="sm" variant="outline" onClick={() => openAgentJobDetail(event.job_id ?? "")}>
                              Open job
                            </Button>
                          ) : null}
                          {linkedExecutor ? (
                            <Button size="sm" variant="outline" onClick={() => openExecutorDetail(linkedExecutor)}>
                              Open executor
                            </Button>
                          ) : null}
                        </div>
                      ) : null}

                      {Object.keys(event.data ?? {}).length ? (
                        <details className="mt-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.18em] text-mutedForeground">
                            Payload
                          </summary>
                          <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs text-mutedForeground">
                            {formatJsonPreview(event.data, 4000)}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  );
                })
              ) : (
                <StateMessage>No live events match the current filters.</StateMessage>
              )}
              <div ref={liveEventsEndRef} />
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
