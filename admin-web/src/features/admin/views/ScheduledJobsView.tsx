import { SectionHeader } from "@/components/SectionHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TableMessageRow } from "@/features/admin/components/TableMessageRow";
import type { ScheduledJobItem } from "@/lib/types";
import { formatRelativeTime } from "@/lib/utils";

type ScheduledJobsViewProps = {
  jobsLoading: boolean;
  jobsError: string | null;
  jobsData: ScheduledJobItem[];
  openNewJob: () => void;
  openEditJob: (job: ScheduledJobItem) => void;
  deleteJob: (job: ScheduledJobItem) => Promise<void>;
  renderUser: (userId: string) => React.ReactNode;
  channelLabelFor: (channelId: string, accountKey?: string | null) => string;
  mainModelLabelValue: string;
};

export function ScheduledJobsView({
  jobsLoading,
  jobsError,
  jobsData,
  openNewJob,
  openEditJob,
  deleteJob,
  renderUser,
  channelLabelFor,
  mainModelLabelValue,
}: ScheduledJobsViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader
            title="Scheduled jobs"
            subtitle="Automations running on cron or one-shot schedules."
            actionLabel="New job"
            onAction={openNewJob}
          />
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Channel</TableHead>
                <TableHead>Next run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobsLoading ? (
                <TableMessageRow colSpan={7}>Loading jobs...</TableMessageRow>
              ) : jobsError ? (
                <TableMessageRow colSpan={7}>{jobsError}</TableMessageRow>
              ) : jobsData.length ? (
                jobsData.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-semibold">{job.name}</TableCell>
                    <TableCell>{renderUser(job.user_id)}</TableCell>
                    <TableCell className="font-mono text-xs">
                      <div>{job.schedule_type === "date" ? "DATE" : "CRON"} · {job.schedule_expr}</div>
                      <div className="mt-1 text-[11px] text-mutedForeground">
                        Model: {job.model === mainModelLabelValue ? "Main model chain" : job.model}
                      </div>
                    </TableCell>
                    <TableCell>{channelLabelFor(job.channel_id, job.target_transport_account_key)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatRelativeTime(job.next_run_at)}</TableCell>
                    <TableCell>
                      <Badge variant={job.enabled ? "success" : "secondary"}>{job.enabled ? "active" : "paused"}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={() => openEditJob(job)}>
                          Edit
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => void deleteJob(job)}>
                          Delete
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableMessageRow colSpan={7}>No scheduled jobs yet.</TableMessageRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
