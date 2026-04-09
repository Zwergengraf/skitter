import { SectionHeader } from "@/components/SectionHeader";
import { CostChart } from "@/components/CostChart";
import { StatusPill } from "@/components/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StateMessage } from "@/features/admin/components/StateMessage";
import { TableMessageRow } from "@/features/admin/components/TableMessageRow";
import type { OverviewRange } from "@/features/admin/types";
import type { OverviewCostPoint, OverviewSession, OverviewToolApproval, ServiceStatus } from "@/lib/types";
import { formatNumber, formatRelativeTime } from "@/lib/utils";

type OverviewViewProps = {
  overviewRange: OverviewRange;
  onOverviewRangeChange: (value: OverviewRange) => void;
  overviewLoading: boolean;
  overviewError: string | null;
  overviewCost: OverviewCostPoint[];
  overviewHealth: ServiceStatus[];
  overviewSessions: OverviewSession[];
  overviewToolRuns: OverviewToolApproval[];
  openSessionDetail: (sessionId: string) => void;
  renderUser: (userId: string) => React.ReactNode;
};

export function OverviewView({
  overviewRange,
  onOverviewRangeChange,
  overviewLoading,
  overviewError,
  overviewCost,
  overviewHealth,
  overviewSessions,
  overviewToolRuns,
  openSessionDetail,
  renderUser,
}: OverviewViewProps) {
  return (
    <div className="grid gap-8">
      <div className="grid items-stretch gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,0.8fr)]">
        <Card className="min-w-0 h-full flex flex-col">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>Cost trajectory</CardTitle>
                <CardDescription>
                  {overviewRange === "today" && "Token spend per hour (today)."}
                  {overviewRange === "24h" && "Token spend per hour (last 24 hours)."}
                  {overviewRange === "week" && "Token spend per day (last week)."}
                  {overviewRange === "month" && "Token spend per day (last month)."}
                  {overviewRange === "year" && "Token spend per month (last year)."}
                </CardDescription>
              </div>
              <Select value={overviewRange} onValueChange={(value) => onOverviewRangeChange(value as OverviewRange)}>
                <SelectTrigger className="w-44">
                  <SelectValue placeholder="Time range" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="today">Today</SelectItem>
                  <SelectItem value="24h">Last 24 hours</SelectItem>
                  <SelectItem value="week">Last week</SelectItem>
                  <SelectItem value="month">Last month</SelectItem>
                  <SelectItem value="year">Last year</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent className="flex-1">
            {overviewLoading ? (
              <StateMessage className="flex h-52 items-center justify-center border" compact>
                Loading cost data...
              </StateMessage>
            ) : (
              <CostChart data={overviewCost} />
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 h-full flex flex-col">
          <CardHeader>
            <CardTitle>System health</CardTitle>
            <CardDescription>Live signals from each core service.</CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 flex-1 space-y-3 overflow-hidden">
            {overviewError ? (
              <StateMessage>{overviewError}</StateMessage>
            ) : overviewHealth.length ? (
              overviewHealth.map((service) => (
                <StatusPill key={service.name} label={service.name} status={service.status} detail={service.detail} />
              ))
            ) : (
              <StateMessage>No health data yet.</StateMessage>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,0.8fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <SectionHeader title="Live sessions" subtitle="Active conversations across all transports." actionLabel="View all" />
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Session</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Transport</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>Last active</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {overviewLoading ? (
                  <TableMessageRow colSpan={6}>Loading sessions...</TableMessageRow>
                ) : overviewError ? (
                  <TableMessageRow colSpan={6}>{overviewError}</TableMessageRow>
                ) : overviewSessions.length ? (
                  overviewSessions.map((session) => (
                    <TableRow key={session.id} className="cursor-pointer" onClick={() => openSessionDetail(session.id)}>
                      <TableCell className="font-semibold">{session.id}</TableCell>
                      <TableCell>{renderUser(session.user)}</TableCell>
                      <TableCell className="uppercase text-mutedForeground">{session.transport}</TableCell>
                      <TableCell>
                        <Badge variant={session.status === "active" ? "success" : "secondary"}>{session.status}</Badge>
                      </TableCell>
                      <TableCell>{formatNumber(session.total_tokens ?? 0)}</TableCell>
                      <TableCell className="text-mutedForeground">{formatRelativeTime(session.last_active_at)}</TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableMessageRow colSpan={6}>No active sessions.</TableMessageRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <SectionHeader title="Tool approvals" subtitle="Requests waiting on human review." />
          </CardHeader>
          <CardContent className="space-y-4">
            {overviewLoading ? (
              <StateMessage>Loading approvals...</StateMessage>
            ) : overviewError ? (
              <StateMessage>{overviewError}</StateMessage>
            ) : overviewToolRuns.length ? (
              overviewToolRuns.map((tool) => (
                <div
                  key={tool.id}
                  className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-semibold">{tool.tool}</p>
                    <div className="mt-1 flex items-center gap-2 text-xs text-mutedForeground">
                      {renderUser(tool.requested_by)}
                      <span>· {formatRelativeTime(tool.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={tool.status === "pending" ? "warning" : "secondary"}>{tool.status}</Badge>
                    <Button size="sm" variant="outline">
                      Review
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <StateMessage>No pending approvals.</StateMessage>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
