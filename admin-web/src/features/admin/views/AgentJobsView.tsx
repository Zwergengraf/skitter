import { SectionHeader } from "@/components/SectionHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TableMessageRow } from "@/features/admin/components/TableMessageRow";
import type { AgentJobListItem } from "@/lib/types";
import { formatCurrency, formatNumber, formatRelativeTime } from "@/lib/utils";

type AgentJobsViewProps = {
  agentJobsData: AgentJobListItem[];
  agentJobsLoading: boolean;
  agentJobsError: string | null;
  filteredAgentJobs: AgentJobListItem[];
  agentJobStatuses: string[];
  agentJobUsers: string[];
  agentJobStatusFilter: string;
  onAgentJobStatusFilterChange: (value: string) => void;
  agentJobUserFilter: string;
  onAgentJobUserFilterChange: (value: string) => void;
  agentJobStatusCounts: Record<string, number>;
  renderUser: (userId: string) => React.ReactNode;
  userLabelFor: (userId: string) => string;
  setSelectedAgentJobId: (jobId: string) => void;
  refreshAgentJobs: () => void;
  formatDuration: (durationMs?: number | null) => string;
  computeAgentJobDurationMs: (job: AgentJobListItem) => number | null;
};

export function AgentJobsView({
  agentJobsData,
  agentJobsLoading,
  agentJobsError,
  filteredAgentJobs,
  agentJobStatuses,
  agentJobUsers,
  agentJobStatusFilter,
  onAgentJobStatusFilterChange,
  agentJobUserFilter,
  onAgentJobUserFilterChange,
  agentJobStatusCounts,
  renderUser,
  userLabelFor,
  setSelectedAgentJobId,
  refreshAgentJobs,
  formatDuration,
  computeAgentJobDurationMs,
}: AgentJobsViewProps) {
  return (
    <div className="grid gap-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total</CardDescription>
            <CardTitle>{formatNumber(agentJobsData.length)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Queued</CardDescription>
            <CardTitle>{formatNumber(agentJobStatusCounts.queued ?? 0)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Running</CardDescription>
            <CardTitle>{formatNumber(agentJobStatusCounts.running ?? 0)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Failed / Timeout</CardDescription>
            <CardTitle>{formatNumber((agentJobStatusCounts.failed ?? 0) + (agentJobStatusCounts.timeout ?? 0))}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="min-w-0">
        <CardHeader>
          <SectionHeader
            title="Background jobs"
            subtitle="Queued and completed long-running tasks started by the agent."
            actionLabel="Refresh"
            onAction={refreshAgentJobs}
          />
        </CardHeader>
        <CardContent className="min-w-0 space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Select value={agentJobStatusFilter} onValueChange={onAgentJobStatusFilterChange}>
              <SelectTrigger>
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {agentJobStatuses.map((status) => (
                  <SelectItem key={status} value={status}>
                    {status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={agentJobUserFilter} onValueChange={onAgentJobUserFilterChange}>
              <SelectTrigger>
                <SelectValue placeholder="Filter by user" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All users</SelectItem>
                {agentJobUsers.map((userId) => (
                  <SelectItem key={userId} value={userId}>
                    {userLabelFor(userId)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Table className="min-w-[1040px]">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Tokens</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Delivery</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agentJobsLoading ? (
                <TableMessageRow colSpan={10}>Loading background jobs...</TableMessageRow>
              ) : agentJobsError ? (
                <TableMessageRow colSpan={10}>{agentJobsError}</TableMessageRow>
              ) : filteredAgentJobs.length ? (
                filteredAgentJobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="max-w-[240px]">
                      <p className="truncate font-semibold">{job.name}</p>
                      <p className="text-xs text-mutedForeground">{job.kind}</p>
                    </TableCell>
                    <TableCell>{renderUser(job.user_id)}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          job.status === "failed" || job.status === "cancelled"
                            ? "danger"
                            : job.status === "timeout"
                              ? "warning"
                              : job.status === "running"
                                ? "secondary"
                                : job.status === "queued"
                                  ? "warning"
                                  : "success"
                        }
                      >
                        {job.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[220px] text-xs text-mutedForeground">
                      <p className="truncate" title={`${job.target_scope_type}:${job.target_scope_id}`}>
                        {job.target_scope_type}:{job.target_scope_id}
                      </p>
                    </TableCell>
                    <TableCell className="text-mutedForeground">{formatRelativeTime(job.created_at)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatDuration(computeAgentJobDurationMs(job))}</TableCell>
                    <TableCell>{formatNumber(job.total_tokens ?? 0)}</TableCell>
                    <TableCell>{formatCurrency(job.cost ?? 0)}</TableCell>
                    <TableCell>
                      {job.delivery_error ? (
                        <Badge variant="danger">failed</Badge>
                      ) : job.delivered_at ? (
                        <Badge variant="success">delivered</Badge>
                      ) : (
                        <Badge variant="secondary">pending</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" onClick={() => setSelectedAgentJobId(job.id)}>
                        Details
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableMessageRow colSpan={10}>
                  {agentJobsData.length ? "No background jobs match the selected filters." : "No background jobs found."}
                </TableMessageRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
