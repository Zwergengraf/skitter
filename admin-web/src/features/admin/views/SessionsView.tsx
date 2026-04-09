import { SectionHeader } from "@/components/SectionHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PaginationFooter } from "@/features/admin/components/PaginationFooter";
import { TableMessageRow } from "@/features/admin/components/TableMessageRow";
import type { TableRange } from "@/features/admin/types";
import type { SessionListItem } from "@/lib/types";
import { formatCurrency, formatNumber, formatRelativeTime } from "@/lib/utils";

type SessionsViewProps = {
  filter: string;
  onFilterChange: (value: string) => void;
  sessionsRange: TableRange;
  onSessionsRangeChange: (value: TableRange) => void;
  sessionsLoading: boolean;
  sessionsError: string | null;
  sessionsData: SessionListItem[];
  visibleSessions: SessionListItem[];
  pagedSessions: SessionListItem[];
  sessionsPage: number;
  sessionsPageCount: number;
  onPreviousPage: () => void;
  onNextPage: () => void;
  openSessionDetail: (sessionId: string) => void;
  renderUser: (userId: string) => React.ReactNode;
  profileLabelFor: (userId: string | null | undefined, profileId?: string | null, fallbackSlug?: string | null) => string;
};

export function SessionsView({
  filter,
  onFilterChange,
  sessionsRange,
  onSessionsRangeChange,
  sessionsLoading,
  sessionsError,
  sessionsData,
  visibleSessions,
  pagedSessions,
  sessionsPage,
  sessionsPageCount,
  onPreviousPage,
  onNextPage,
  openSessionDetail,
  renderUser,
  profileLabelFor,
}: SessionsViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader title="Session control" subtitle="Manage live and historical user conversations." />
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Tabs defaultValue={filter} onValueChange={onFilterChange}>
              <TabsList>
                <TabsTrigger value="all">All</TabsTrigger>
                <TabsTrigger value="active">Active</TabsTrigger>
                <TabsTrigger value="idle">Idle</TabsTrigger>
                <TabsTrigger value="paused">Paused</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex items-center gap-3">
              <Select value={sessionsRange} onValueChange={(value) => onSessionsRangeChange(value as TableRange)}>
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
              <Button variant="outline">Export</Button>
            </div>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Session</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Profile</TableHead>
                <TableHead>Transport</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Context</TableHead>
                <TableHead>Total tokens</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Last active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessionsLoading ? (
                <TableMessageRow colSpan={9}>Loading sessions...</TableMessageRow>
              ) : sessionsError ? (
                <TableMessageRow colSpan={9}>{sessionsError}</TableMessageRow>
              ) : visibleSessions.length ? (
                pagedSessions.map((session) => (
                  <TableRow key={session.id} className="cursor-pointer" onClick={() => openSessionDetail(session.id)}>
                    <TableCell className="font-semibold">{session.id}</TableCell>
                    <TableCell>{renderUser(session.user)}</TableCell>
                    <TableCell className="text-mutedForeground">
                      {profileLabelFor(session.user, session.agent_profile_id, session.agent_profile_slug)}
                    </TableCell>
                    <TableCell className="uppercase text-mutedForeground">{session.transport}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          session.status === "active"
                            ? "success"
                            : session.status === "idle"
                              ? "secondary"
                              : "warning"
                        }
                      >
                        {session.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-mutedForeground">{formatNumber(session.last_input_tokens ?? 0)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatNumber(session.total_tokens ?? 0)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatCurrency(session.total_cost ?? 0)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatRelativeTime(session.last_active_at)}</TableCell>
                  </TableRow>
                ))
              ) : (
                <TableMessageRow colSpan={9}>
                  {sessionsData.length ? "No sessions found for the selected timeframe." : "No sessions found."}
                </TableMessageRow>
              )}
            </TableBody>
          </Table>
          {!sessionsLoading && !sessionsError && visibleSessions.length ? (
            <PaginationFooter
              page={sessionsPage}
              pageCount={sessionsPageCount}
              pageSize={25}
              totalCount={visibleSessions.length}
              onPrevious={onPreviousPage}
              onNext={onNextPage}
            />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
