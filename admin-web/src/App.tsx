import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronsUpDown,
  CloudCog,
  FolderKanban,
  RefreshCcw,
  Rocket,
  Server,
} from "lucide-react";

import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusPill } from "@/components/StatusPill";
import { CostChart } from "@/components/CostChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { formatJsonPreview, formatRelativeTime } from "@/lib/utils";
import { api } from "@/lib/api";
import { incidents } from "@/lib/mock";
import type { NavItemId } from "@/components/navigation";
import type {
  ChannelListItem,
  MemoryEntry,
  OverviewResponse,
  ScheduledJobItem,
  SessionDetail,
  SessionListItem,
  ToolRunListItem,
  UserListItem,
} from "@/lib/types";

const views: Record<NavItemId, string> = {
  overview: "Overview",
  sessions: "Sessions",
  tools: "Tool Runs",
  jobs: "Scheduled Jobs",
  memory: "Memory",
  users: "Users",
  sandbox: "Sandbox",
  security: "Approvals",
  settings: "Settings",
  activity: "Activity",
};

export default function App() {
  const [active, setActive] = useState<NavItemId>("overview");
  const [filter, setFilter] = useState("all");
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState<boolean>(false);
  const [sessionsData, setSessionsData] = useState<SessionListItem[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(false);
  const [toolRunsData, setToolRunsData] = useState<ToolRunListItem[]>([]);
  const [toolRunsError, setToolRunsError] = useState<string | null>(null);
  const [toolRunsLoading, setToolRunsLoading] = useState<boolean>(false);
  const [memoryData, setMemoryData] = useState<MemoryEntry[]>([]);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryLoading, setMemoryLoading] = useState<boolean>(false);
  const [selectedMemory, setSelectedMemory] = useState<MemoryEntry | null>(null);
  const [memoryDetailContent, setMemoryDetailContent] = useState<string>("");
  const [memoryDetailLoading, setMemoryDetailLoading] = useState<boolean>(false);
  const [memoryUserId, setMemoryUserId] = useState<string>("");
  const [memoryReindexing, setMemoryReindexing] = useState<boolean>(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null);
  const [sessionDetailError, setSessionDetailError] = useState<string | null>(null);
  const [sessionDetailLoading, setSessionDetailLoading] = useState<boolean>(false);
  const [jobsData, setJobsData] = useState<ScheduledJobItem[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsLoading, setJobsLoading] = useState<boolean>(false);
  const [usersData, setUsersData] = useState<UserListItem[]>([]);
  const [usersLoading, setUsersLoading] = useState<boolean>(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [userUpdating, setUserUpdating] = useState<Record<string, boolean>>({});
  const [channelsData, setChannelsData] = useState<ChannelListItem[]>([]);
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [jobDialogOpen, setJobDialogOpen] = useState(false);
  const [jobSaving, setJobSaving] = useState(false);
  const [editingJob, setEditingJob] = useState<ScheduledJobItem | null>(null);
  const [jobForm, setJobForm] = useState({
    user_id: "",
    user_label: "",
    channel_id: "",
    channel_label: "",
    name: "",
    prompt: "",
    schedule_type: "cron",
    schedule_expr: "",
    schedule_date: "",
    schedule_time: "",
    enabled: true,
  });
  const [isDark, setIsDark] = useState<boolean>(() => {
    const stored = localStorage.getItem("theme");
    return stored ? stored === "dark" : true;
  });

  const activeLabel = views[active];

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    localStorage.setItem("theme", isDark ? "dark" : "light");
  }, [isDark]);

  useEffect(() => {
    if (active !== "overview") {
      return;
    }
    let isMounted = true;
    setOverviewLoading(true);
    setOverviewError(null);
    api
      .getOverview()
      .then((data) => {
        if (!isMounted) return;
        setOverview(data);
      })
      .catch((error: Error) => {
        if (!isMounted) return;
        setOverviewError(error.message);
      })
      .finally(() => {
        if (!isMounted) return;
        setOverviewLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [active]);

  const overviewSessions = overview?.live_sessions ?? [];
  const overviewToolRuns = overview?.tool_approvals ?? [];
  const overviewHealth = overview?.system_health ?? [];
  const overviewCost = overview?.cost_trajectory ?? [];
  const sessionTimeline = useMemo(() => {
    if (!sessionDetail) {
      return [];
    }
    const timeline = [
      ...sessionDetail.messages.map((message) => ({
        type: "message" as const,
        id: message.id,
        created_at: message.created_at,
        data: message,
      })),
      ...sessionDetail.tool_runs.map((tool) => ({
        type: "tool" as const,
        id: tool.id,
        created_at: tool.created_at,
        data: tool,
      })),
    ];
    return timeline.sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
  }, [sessionDetail]);

  const openSessionDetail = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    const params = new URLSearchParams(window.location.search);
    params.set("session", sessionId);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  };

  const closeSessionDetail = () => {
    setSelectedSessionId(null);
    const params = new URLSearchParams(window.location.search);
    params.delete("session");
    const query = params.toString();
    window.history.replaceState({}, "", query ? `${window.location.pathname}?${query}` : window.location.pathname);
  };

  useEffect(() => {
    if (active !== "sessions") {
      return;
    }
    let isMounted = true;
    setSessionsLoading(true);
    setSessionsError(null);
    api
      .getSessions(filter)
      .then((data) => {
        if (!isMounted) return;
        setSessionsData(data);
      })
      .catch((error: Error) => {
        if (!isMounted) return;
        setSessionsError(error.message);
      })
      .finally(() => {
        if (!isMounted) return;
        setSessionsLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [active, filter]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");
    if (sessionId) {
      setSelectedSessionId(sessionId);
    }
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      setSessionDetail(null);
      setSessionDetailError(null);
      return;
    }
    setSessionDetailLoading(true);
    setSessionDetailError(null);
    api
      .getSessionDetail(selectedSessionId)
      .then((detail) => {
        setSessionDetail(detail);
      })
      .catch((error: Error) => {
        setSessionDetailError(error.message);
      })
      .finally(() => {
        setSessionDetailLoading(false);
      });
  }, [selectedSessionId]);

  useEffect(() => {
    if (active !== "tools") {
      return;
    }
    let isMounted = true;
    setToolRunsLoading(true);
    setToolRunsError(null);
    api
      .getToolRuns()
      .then((data) => {
        if (!isMounted) return;
        setToolRunsData(data);
      })
      .catch((error: Error) => {
        if (!isMounted) return;
        setToolRunsError(error.message);
      })
      .finally(() => {
        if (!isMounted) return;
        setToolRunsLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [active]);

  useEffect(() => {
    if (active !== "memory") {
      return;
    }
    const userId = usersData[0]?.id;
    if (!userId) {
      setMemoryData([]);
      setMemoryError("No users found yet.");
      setMemoryLoading(false);
      return;
    }
    setMemoryUserId(userId);
    setMemoryLoading(true);
    setMemoryError(null);
    api
      .getMemory(userId)
      .then((data) => {
        setMemoryData(data);
      })
      .catch((error: Error) => {
        setMemoryError(error.message);
      })
      .finally(() => {
        setMemoryLoading(false);
      });
  }, [active, usersData]);

  useEffect(() => {
    if (!selectedMemory?.source) {
      setMemoryDetailContent("");
      return;
    }
    setMemoryDetailLoading(true);
    api
      .getMemoryFile(selectedMemory.source)
      .then((data) => {
        setMemoryDetailContent(data.content);
      })
      .catch((error: Error) => {
        setMemoryError(error.message);
      })
      .finally(() => {
        setMemoryDetailLoading(false);
      });
  }, [selectedMemory]);

  const handleMemoryReindex = async () => {
    if (!memoryUserId) {
      setMemoryError("No user selected for reindex.");
      return;
    }
    setMemoryReindexing(true);
    try {
      const stats = await api.reindexMemory(memoryUserId);
      await api.getMemory(memoryUserId).then((data) => setMemoryData(data));
      setMemoryError(`Reindex complete. Indexed: ${stats.indexed}, skipped: ${stats.skipped}, removed: ${stats.removed}.`);
    } catch (error) {
      setMemoryError((error as Error).message);
    } finally {
      setMemoryReindexing(false);
    }
  };

  const handleUserApproval = async (userId: string, approved: boolean) => {
    setUserUpdating((prev) => ({ ...prev, [userId]: true }));
    setUsersError(null);
    try {
      await api.updateUser(userId, { approved });
      setUsersData((prev) =>
        prev.map((user) => (user.id === userId ? { ...user, approved } : user))
      );
    } catch (error) {
      setUsersError((error as Error).message);
    } finally {
      setUserUpdating((prev) => ({ ...prev, [userId]: false }));
    }
  };

  const refreshJobs = () => {
    setJobsLoading(true);
    setJobsError(null);
    api
      .getSchedules()
      .then((data) => {
        setJobsData(data);
      })
      .catch((error: Error) => {
        setJobsError(error.message);
      })
      .finally(() => {
        setJobsLoading(false);
      });
  };

  const refreshDirectories = () => {
    setDirectoryError(null);
    Promise.all([api.getUsers(), api.getChannels()])
      .then(([users, channels]) => {
        setUsersData(users);
        setChannelsData(channels);
      })
      .catch((error: Error) => {
        setDirectoryError(error.message);
      });
  };

  const refreshUsers = () => {
    setUsersLoading(true);
    setUsersError(null);
    api
      .getUsers()
      .then((users) => {
        setUsersData(users);
      })
      .catch((error: Error) => {
        setUsersError(error.message);
      })
      .finally(() => {
        setUsersLoading(false);
      });
  };

  useEffect(() => {
    refreshDirectories();
  }, []);

  useEffect(() => {
    if (active !== "jobs") {
      return;
    }
    refreshJobs();
  }, [active]);

  useEffect(() => {
    if (active !== "users") {
      return;
    }
    refreshUsers();
  }, [active]);

  const userLabelFor = (userId: string) => {
    const user = usersData.find(
      (item) => item.id === userId || item.transport_user_id === userId
    );
    if (!user) {
      return userId;
    }
    const name = user.display_name ?? user.username ?? user.transport_user_id;
    return `@${name}`;
  };

  const userAvatarFor = (userId: string) => {
    const user = usersData.find(
      (item) => item.id === userId || item.transport_user_id === userId
    );
    return user?.avatar_url ?? null;
  };

  const userInitials = (label: string) => {
    if (!label) return "U";
    return label.replace("@", "").slice(0, 2).toUpperCase();
  };

  const renderUser = (userId: string) => {
    const label = userLabelFor(userId);
    const avatar = userAvatarFor(userId);
    return (
      <span className="inline-flex items-center gap-2">
        <Avatar className="h-6 w-6">
          {avatar ? <AvatarImage src={avatar} alt={label} /> : null}
          <AvatarFallback>{userInitials(label)}</AvatarFallback>
        </Avatar>
        <span>{label}</span>
      </span>
    );
  };

  const resolveUserId = (value: string, fallback: string) => {
    if (!value) {
      return fallback;
    }
    const match = usersData.find((user) => {
      const label = `@${user.display_name ?? user.username ?? user.transport_user_id}`;
      return label === value || user.transport_user_id === value || user.id === value;
    });
    return match?.id ?? value;
  };

  const channelLabelFor = (channelId: string) => {
    const channel = channelsData.find((item) => item.id === channelId);
    return channel?.label ?? channelId;
  };

  const resolveChannelId = (value: string, fallback: string) => {
    if (!value) {
      return fallback;
    }
    const match = channelsData.find((channel) => channel.label === value || channel.id === value);
    return match?.id ?? value;
  };

  useEffect(() => {
    if (!jobDialogOpen) {
      return;
    }
    setJobForm((prev) => {
      const nextUserLabel = prev.user_label || userLabelFor(prev.user_id);
      const nextChannelLabel = prev.channel_label || channelLabelFor(prev.channel_id);
      if (nextUserLabel === prev.user_label && nextChannelLabel === prev.channel_label) {
        return prev;
      }
      return {
        ...prev,
        user_label: nextUserLabel,
        channel_label: nextChannelLabel,
      };
    });
  }, [usersData, channelsData, jobDialogOpen]);

  const buildDateSchedule = (date: string, time: string) => {
    if (!date || !time) {
      return "";
    }
    const normalized = time.length === 5 ? `${time}:00` : time;
    return `${date}T${normalized}`;
  };

  const openNewJob = () => {
    setEditingJob(null);
    setJobForm({
      user_id: "",
      user_label: "",
      channel_id: "",
      channel_label: "",
      name: "",
      prompt: "",
      schedule_type: "cron",
      schedule_expr: "",
      schedule_date: "",
      schedule_time: "",
      enabled: true,
    });
    setJobDialogOpen(true);
  };

  const openEditJob = (job: ScheduledJobItem) => {
    const scheduleDate = job.schedule_type === "date" ? job.schedule_expr.split("T")[0] ?? "" : "";
    const scheduleTime = job.schedule_type === "date" ? job.schedule_expr.split("T")[1]?.slice(0, 5) ?? "" : "";
    setEditingJob(job);
    setJobForm({
      user_id: job.user_id,
      user_label: userLabelFor(job.user_id),
      channel_id: job.channel_id,
      channel_label: channelLabelFor(job.channel_id),
      name: job.name,
      prompt: job.prompt,
      schedule_type: job.schedule_type,
      schedule_expr: job.schedule_expr,
      schedule_date: scheduleDate,
      schedule_time: scheduleTime,
      enabled: job.enabled,
    });
    setJobDialogOpen(true);
  };

  const saveJob = async () => {
    setJobSaving(true);
    try {
      const scheduleExpr =
        jobForm.schedule_type === "date"
          ? buildDateSchedule(jobForm.schedule_date, jobForm.schedule_time)
          : jobForm.schedule_expr;
      const resolvedUserId = resolveUserId(jobForm.user_label, jobForm.user_id);
      const resolvedChannelId = resolveChannelId(jobForm.channel_label, jobForm.channel_id);
      if (editingJob) {
        await api.updateSchedule(editingJob.id, {
          name: jobForm.name,
          prompt: jobForm.prompt,
          schedule_type: jobForm.schedule_type,
          schedule_expr: scheduleExpr,
          enabled: jobForm.enabled,
          channel_id: resolvedChannelId,
        });
      } else {
        await api.createSchedule({
          user_id: resolvedUserId,
          channel_id: resolvedChannelId,
          name: jobForm.name,
          prompt: jobForm.prompt,
          schedule_type: jobForm.schedule_type,
          schedule_expr: scheduleExpr,
          enabled: jobForm.enabled,
        });
      }
      setJobDialogOpen(false);
      refreshJobs();
    } catch (error) {
      setJobsError((error as Error).message);
    } finally {
      setJobSaving(false);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar active={active} onSelect={setActive} />
      <div className="flex flex-col gap-8 px-10 py-10">
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-8">
          <Topbar isDark={isDark} onToggleTheme={setIsDark} />
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="data-chip text-[10px] text-mutedForeground">{activeLabel}</div>
              <p className="text-sm text-mutedForeground">Last sync 2 minutes ago</p>
            </div>
            <div className="flex items-center gap-3">
              <Button variant="outline">
                <RefreshCcw className="mr-2 h-4 w-4" />
                Refresh data
              </Button>
              <Button>
                <Rocket className="mr-2 h-4 w-4" />
                Deploy updates
              </Button>
            </div>
          </div>

        {active === "overview" && (
          <div className="grid gap-8">
            <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
              <Card>
                <CardHeader>
                  <CardTitle>Cost trajectory</CardTitle>
                  <CardDescription>Token spend across the last 7 days.</CardDescription>
                </CardHeader>
                <CardContent>
                  {overviewLoading ? (
                    <div className="flex h-52 items-center justify-center rounded-2xl border border-dashed border-border bg-muted/40 text-sm text-mutedForeground">
                      Loading cost data...
                    </div>
                  ) : (
                    <CostChart data={overviewCost} />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>System health</CardTitle>
                  <CardDescription>Live signals from each core service.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {overviewError ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      {overviewError}
                    </div>
                  ) : overviewHealth.length ? (
                    overviewHealth.map((service) => (
                      <StatusPill
                        key={service.name}
                        label={service.name}
                        status={service.status}
                        detail={service.detail}
                      />
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      No health data yet.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
              <Card>
                <CardHeader>
                  <SectionHeader
                    title="Live sessions"
                    subtitle="Active conversations across all transports."
                    actionLabel="View all"
                  />
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
                        <TableRow>
                          <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                            Loading sessions...
                          </TableCell>
                        </TableRow>
                      ) : overviewError ? (
                        <TableRow>
                          <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                            {overviewError}
                          </TableCell>
                        </TableRow>
                      ) : overviewSessions.length ? (
                        overviewSessions.map((session) => (
                          <TableRow
                            key={session.id}
                            className="cursor-pointer"
                            onClick={() => openSessionDetail(session.id)}
                          >
                            <TableCell className="font-semibold">{session.id}</TableCell>
                            <TableCell>{renderUser(session.user)}</TableCell>
                            <TableCell className="uppercase text-mutedForeground">
                              {session.transport}
                            </TableCell>
                            <TableCell>
                              <Badge variant={session.status === "active" ? "success" : "secondary"}>
                                {session.status}
                              </Badge>
                            </TableCell>
                            <TableCell>—</TableCell>
                            <TableCell className="text-mutedForeground">
                              {formatRelativeTime(session.last_active_at)}
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                            No active sessions.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <SectionHeader
                    title="Tool approvals"
                    subtitle="Requests waiting on human review."
                  />
                </CardHeader>
                <CardContent className="space-y-4">
                  {overviewLoading ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      Loading approvals...
                    </div>
                  ) : overviewError ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      {overviewError}
                    </div>
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
                          <Badge variant={tool.status === "pending" ? "warning" : "secondary"}>
                            {tool.status}
                          </Badge>
                          <Button size="sm" variant="outline">
                            Review
                          </Button>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      No pending approvals.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {active === "sessions" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Session control"
                  subtitle="Manage live and historical user conversations."
                />
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <Tabs defaultValue="all" onValueChange={(value) => setFilter(value)}>
                    <TabsList>
                      <TabsTrigger value="all">All</TabsTrigger>
                      <TabsTrigger value="active">Active</TabsTrigger>
                      <TabsTrigger value="idle">Idle</TabsTrigger>
                      <TabsTrigger value="paused">Paused</TabsTrigger>
                    </TabsList>
                  </Tabs>
                  <div className="flex items-center gap-3">
                    <Select defaultValue="today">
                      <SelectTrigger className="w-40">
                        <SelectValue placeholder="Timeframe" />
                      </SelectTrigger>
                      <SelectContent>
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
                      <TableHead>Transport</TableHead>
                      <TableHead>State</TableHead>
                      <TableHead>Tokens</TableHead>
                      <TableHead>Last active</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessionsLoading ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          Loading sessions...
                        </TableCell>
                      </TableRow>
                    ) : sessionsError ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          {sessionsError}
                        </TableCell>
                      </TableRow>
                    ) : sessionsData.length ? (
                      sessionsData.map((session) => (
                        <TableRow
                          key={session.id}
                          className="cursor-pointer"
                          onClick={() => openSessionDetail(session.id)}
                        >
                          <TableCell className="font-semibold">{session.id}</TableCell>
                          <TableCell>{renderUser(session.user)}</TableCell>
                          <TableCell className="uppercase text-mutedForeground">
                            {session.transport}
                          </TableCell>
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
                          <TableCell>—</TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatRelativeTime(session.last_active_at)}
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          No sessions found.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        )}

        {active === "tools" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Tool runs"
                  subtitle="Audit all tool activity and intervention points."
                />
              </CardHeader>
              <CardContent className="space-y-4">
                {toolRunsLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading tool runs...
                  </div>
                ) : toolRunsError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {toolRunsError}
                  </div>
                ) : toolRunsData.length ? (
                  toolRunsData.map((tool) => (
                    <div
                      key={tool.id}
                      className="rounded-2xl border border-border bg-card px-5 py-4"
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
                      </div>
                      <div className="mt-4 grid gap-3 text-xs text-mutedForeground md:grid-cols-3">
                        <div>
                          <p className="uppercase tracking-[0.2em] text-mutedForeground">Approved by</p>
                          <p className="mt-1 text-sm text-foreground">{tool.approved_by ?? "—"}</p>
                        </div>
                        <div>
                          <p className="uppercase tracking-[0.2em] text-mutedForeground">Created</p>
                          <p className="mt-1 text-sm text-foreground">{formatRelativeTime(tool.created_at)}</p>
                        </div>
                        <div>
                          <p className="uppercase tracking-[0.2em] text-mutedForeground">Session</p>
                          <button
                            className="mt-1 text-sm text-primary underline-offset-4 hover:underline"
                            onClick={() => openSessionDetail(tool.session_id)}
                          >
                            View session
                          </button>
                        </div>
                      </div>
                      <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Input
                          </p>
                          <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                            {formatJsonPreview(tool.input)}
                          </pre>
                        </div>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Output
                          </p>
                          <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                            {formatJsonPreview(tool.output)}
                          </pre>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    No tool runs found.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "jobs" && (
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
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          Loading jobs...
                        </TableCell>
                      </TableRow>
                    ) : jobsError ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          {jobsError}
                        </TableCell>
                      </TableRow>
                    ) : jobsData.length ? (
                      jobsData.map((job) => (
                        <TableRow key={job.id}>
                          <TableCell className="font-semibold">{job.name}</TableCell>
                          <TableCell>{renderUser(job.user_id)}</TableCell>
                          <TableCell className="font-mono text-xs">
                            {job.schedule_type === "date" ? "DATE" : "CRON"} · {job.schedule_expr}
                          </TableCell>
                          <TableCell>
                            {channelsData.find((channel) => channel.id === job.channel_id)?.label ??
                              job.channel_id}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatRelativeTime(job.next_run_at)}
                          </TableCell>
                          <TableCell>
                            <Badge variant={job.enabled ? "success" : "secondary"}>
                              {job.enabled ? "active" : "paused"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Button size="sm" variant="outline" onClick={() => openEditJob(job)}>
                                Edit
                              </Button>
                              <Button
                                size="sm"
                                variant="danger"
                                onClick={async () => {
                                  if (!confirm(`Delete job \"${job.name}\"?`)) return;
                                  try {
                                    await api.deleteSchedule(job.id);
                                    refreshJobs();
                                  } catch (error) {
                                    setJobsError((error as Error).message);
                                  }
                                }}
                              >
                                Delete
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-mutedForeground">
                          No scheduled jobs yet.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
            <Dialog open={jobDialogOpen} onOpenChange={setJobDialogOpen}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{editingJob ? "Edit job" : "New scheduled job"}</DialogTitle>
                  <DialogDescription>
                    Use cron format for recurring runs, or choose one-shot date.
                  </DialogDescription>
                </DialogHeader>
                {directoryError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-3 text-sm text-mutedForeground">
                    {directoryError}
                  </div>
                ) : null}
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Name
                    </label>
                    <Input
                      value={jobForm.name}
                      onChange={(event) => setJobForm((prev) => ({ ...prev, name: event.target.value }))}
                      placeholder="Morning news brief"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Prompt
                    </label>
                    <Textarea
                      value={jobForm.prompt}
                      onChange={(event) => setJobForm((prev) => ({ ...prev, prompt: event.target.value }))}
                      placeholder="Summarize the latest AI news and send it to me."
                    />
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="grid gap-2">
                      <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Schedule type
                      </label>
                      <Select
                        value={jobForm.schedule_type}
                        onValueChange={(value) =>
                          setJobForm((prev) => ({ ...prev, schedule_type: value }))
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="cron" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="cron">Cron</SelectItem>
                          <SelectItem value="date">One-shot date</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid gap-2">
                      {jobForm.schedule_type === "date" ? (
                        <>
                          <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Run at
                          </label>
                          <div className="grid gap-2 md:grid-cols-2">
                            <Input
                              type="date"
                              value={jobForm.schedule_date}
                              onChange={(event) =>
                                setJobForm((prev) => {
                                  const date = event.target.value;
                                  return {
                                    ...prev,
                                    schedule_date: date,
                                    schedule_expr: buildDateSchedule(date, prev.schedule_time),
                                  };
                                })
                              }
                            />
                            <Input
                              type="time"
                              value={jobForm.schedule_time}
                              onChange={(event) =>
                                setJobForm((prev) => {
                                  const time = event.target.value;
                                  return {
                                    ...prev,
                                    schedule_time: time,
                                    schedule_expr: buildDateSchedule(prev.schedule_date, time),
                                  };
                                })
                              }
                            />
                          </div>
                        </>
                      ) : (
                        <>
                          <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Cron expression
                          </label>
                          <Input
                            value={jobForm.schedule_expr}
                            onChange={(event) =>
                              setJobForm((prev) => ({ ...prev, schedule_expr: event.target.value }))
                            }
                            placeholder="0 9 * * *"
                          />
                        </>
                      )}
                    </div>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="grid gap-2">
                      <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        User
                      </label>
                      <Input
                        list="skitter-users"
                        value={jobForm.user_label}
                        onChange={(event) =>
                          setJobForm((prev) => {
                            const value = event.target.value;
                            return {
                              ...prev,
                              user_label: value,
                              user_id: value ? resolveUserId(value, prev.user_id) : "",
                            };
                          })
                        }
                        placeholder="Select a user"
                      />
                      <datalist id="skitter-users">
                        {usersData.map((user) => (
                          <option
                            key={user.id}
                            value={`@${user.display_name ?? user.username ?? user.transport_user_id}`}
                            label={user.transport_user_id}
                          />
                        ))}
                      </datalist>
                      <p className="text-xs text-mutedForeground">
                        {jobForm.user_id
                          ? `Selected: ${userLabelFor(jobForm.user_id)} (${jobForm.user_id})`
                          : "Type to search by name or paste a user id."}
                      </p>
                    </div>
                    <div className="grid gap-2">
                      <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Channel
                      </label>
                      <Input
                        list="skitter-channels"
                        value={jobForm.channel_label}
                        onChange={(event) =>
                          setJobForm((prev) => {
                            const value = event.target.value;
                            return {
                              ...prev,
                              channel_label: value,
                              channel_id: value ? resolveChannelId(value, prev.channel_id) : "",
                            };
                          })
                        }
                        placeholder="Select a channel"
                      />
                      <datalist id="skitter-channels">
                        {channelsData.map((channel) => (
                          <option key={channel.id} value={channel.label} label={channel.id} />
                        ))}
                      </datalist>
                      <p className="text-xs text-mutedForeground">
                        {jobForm.channel_id
                          ? `Selected: ${channelLabelFor(jobForm.channel_id)} (${jobForm.channel_id})`
                          : "Type to search by label or paste a channel id."}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3">
                    <div>
                      <p className="text-sm font-semibold">Job enabled</p>
                      <p className="text-xs text-mutedForeground">Pause without deleting.</p>
                    </div>
                    <Switch
                      checked={jobForm.enabled}
                      onCheckedChange={(value) => setJobForm((prev) => ({ ...prev, enabled: value }))}
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setJobDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={saveJob} disabled={jobSaving}>
                    {jobSaving ? "Saving..." : editingJob ? "Save changes" : "Create job"}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        )}

        {active === "memory" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Memory vault"
                  subtitle="Summaries indexed from session handoffs."
                  actionLabel={memoryReindexing ? "Reindexing..." : "Reindex"}
                  onAction={memoryReindexing ? undefined : handleMemoryReindex}
                />
              </CardHeader>
              <CardContent className="space-y-4">
                {memoryLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading memory...
                  </div>
                ) : memoryError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {memoryError}
                  </div>
                ) : memoryData.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>File</TableHead>
                        <TableHead>Sessions</TableHead>
                        <TableHead>Updated</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {memoryData.map((row) => (
                        <TableRow
                          key={row.id}
                          className="cursor-pointer"
                          onClick={() => setSelectedMemory(row)}
                        >
                          <TableCell className="font-semibold">
                            <div className="min-w-[200px] whitespace-nowrap">
                              {row.source ?? "unknown"}
                            </div>
                          </TableCell>
                          <TableCell className="text-xs text-mutedForeground">
                            {row.session_ids?.length ? row.session_ids.join(", ") : "—"}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            <div className="whitespace-nowrap">{formatRelativeTime(row.created_at)}</div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    No memory entries yet.
                  </div>
                )}
              </CardContent>
            </Card>
            <Dialog open={!!selectedMemory} onOpenChange={(open) => !open && setSelectedMemory(null)}>
              <DialogContent className="max-w-4xl w-[90vw]">
                <DialogHeader>
                  <DialogTitle>Memory detail</DialogTitle>
                  <DialogDescription>
                    Source: {selectedMemory?.source ?? "unknown"} · Sessions:{" "}
                    {selectedMemory?.session_ids?.length ? selectedMemory.session_ids.join(", ") : "—"}
                  </DialogDescription>
                </DialogHeader>
                <ScrollArea className="h-[420px] rounded-2xl border border-border bg-card p-4">
                  <p className="whitespace-pre-wrap text-sm text-foreground">
                    {memoryDetailLoading ? "Loading..." : memoryDetailContent}
                  </p>
                </ScrollArea>
                <div className="flex justify-end">
                  <Button variant="outline" onClick={() => setSelectedMemory(null)}>
                    Close
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        )}

        {active === "users" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Users"
                  subtitle="Approve new accounts before they can chat."
                  actionLabel={usersLoading ? "Refreshing..." : "Refresh"}
                  onAction={usersLoading ? undefined : refreshUsers}
                />
              </CardHeader>
              <CardContent className="space-y-4">
                {usersLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading users...
                  </div>
                ) : usersError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {usersError}
                  </div>
                ) : usersData.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>User</TableHead>
                        <TableHead>Transport ID</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {usersData.map((user) => (
                        <TableRow key={user.id}>
                          <TableCell className="font-semibold">{renderUser(user.id)}</TableCell>
                          <TableCell className="text-xs text-mutedForeground">
                            {user.transport_user_id}
                          </TableCell>
                          <TableCell>
                            <Badge variant={user.approved ? "success" : "warning"}>
                              {user.approved ? "Approved" : "Pending"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              {!user.approved ? (
                                <Button
                                  size="sm"
                                  onClick={() => handleUserApproval(user.id, true)}
                                  disabled={userUpdating[user.id]}
                                >
                                  {userUpdating[user.id] ? "Approving..." : "Approve"}
                                </Button>
                              ) : (
                                <span className="text-xs text-mutedForeground">—</span>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    No users yet.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "sandbox" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Sandbox & workspace</CardTitle>
                <CardDescription>Containers, mounts, and live usage.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 lg:grid-cols-2">
                <div className="rounded-2xl border border-border bg-card p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold">Workspace usage</p>
                      <p className="text-xs text-mutedForeground">/workspace</p>
                    </div>
                    <Badge variant="secondary">12.4 GB</Badge>
                  </div>
                  <div className="mt-4">
                    <Progress value={64} />
                    <p className="mt-2 text-xs text-mutedForeground">64% of 20GB allocated</p>
                  </div>
                </div>
                <div className="rounded-2xl border border-border bg-card p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold">Browser persistence</p>
                      <p className="text-xs text-mutedForeground">/browser-data</p>
                    </div>
                    <Badge variant="success">Mounted</Badge>
                  </div>
                  <div className="mt-4 flex items-center gap-3 text-sm text-mutedForeground">
                    <Server className="h-4 w-4" />
                    Brave stable, 1920×1080 default viewport
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {active === "security" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Human approvals</CardTitle>
                <CardDescription>Control which tools require explicit consent.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
                {[
                  { label: "Filesystem writes", enabled: true },
                  { label: "Shell execution", enabled: true },
                  { label: "Browser actions", enabled: true },
                  { label: "Sub-agent spawn", enabled: false },
                ].map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-4">
                    <div>
                      <p className="text-sm font-semibold">{item.label}</p>
                      <p className="text-xs text-mutedForeground">Requires DM approval button</p>
                    </div>
                    <Switch defaultChecked={item.enabled} />
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "settings" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Runtime settings</CardTitle>
                <CardDescription>Defaults pulled from .env and runtime config.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-4">
                  <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-4">
                    <div>
                      <p className="text-sm font-semibold">Default timezone</p>
                      <p className="text-xs text-mutedForeground">Scheduler + cron</p>
                    </div>
                    <Badge variant="secondary">America/New_York</Badge>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-4">
                    <div>
                      <p className="text-sm font-semibold">Embeddings model</p>
                      <p className="text-xs text-mutedForeground">OpenAI-compatible</p>
                    </div>
                    <Badge variant="secondary">local-embed</Badge>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-4">
                    <div>
                      <p className="text-sm font-semibold">Browser executable</p>
                      <p className="text-xs text-mutedForeground">Sandbox</p>
                    </div>
                    <Badge variant="secondary">/usr/bin/brave-browser</Badge>
                  </div>
                </div>
                <div className="rounded-2xl border border-border bg-card p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold">Config snapshot</p>
                      <p className="text-xs text-mutedForeground">Latest from runtime</p>
                    </div>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button size="icon" variant="outline">
                            <ChevronsUpDown className="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Copy settings JSON</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <Separator className="my-4" />
                  <ScrollArea className="h-40 rounded-2xl border border-border bg-muted/40 p-3 text-xs font-mono text-mutedForeground">
                    <pre>{`{
  "SKITTER_TOOL_APPROVAL_REQUIRED": true,
  "SKITTER_WORKSPACE_ROOT": "./workspace",
  "SKITTER_BROWSER_EXECUTABLE": "/usr/bin/brave-browser",
  "SKITTER_SCHEDULER_TIMEZONE": "America/New_York"
}`}</pre>
                  </ScrollArea>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {active === "activity" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Recent activity</CardTitle>
                <CardDescription>Incidents, warnings, and human interventions.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {incidents.map((incident) => (
                  <div key={incident.id} className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-4">
                    <div className="flex items-center gap-3">
                      {incident.severity === "high" ? (
                        <AlertTriangle className="h-5 w-5 text-rose-500" />
                      ) : incident.severity === "medium" ? (
                        <AlertTriangle className="h-5 w-5 text-amber-500" />
                      ) : (
                        <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                      )}
                      <div>
                        <p className="text-sm font-semibold">{incident.title}</p>
                        <p className="text-xs text-mutedForeground">{incident.timestamp}</p>
                      </div>
                    </div>
                    <Badge
                      variant={
                        incident.severity === "high"
                          ? "danger"
                          : incident.severity === "medium"
                          ? "warning"
                          : "secondary"
                      }
                    >
                      {incident.severity}
                    </Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "sandbox" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Usage detail</CardTitle>
                <CardDescription>Current worker pool utilization.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-3">
                {[{ label: "Workers", value: "5/8" }, { label: "Pending", value: "2" }, { label: "Queue latency", value: "1.2s" }].map((item) => (
                  <div key={item.label} className="rounded-2xl border border-border bg-card p-4">
                    <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">{item.label}</p>
                    <p className="mt-2 text-2xl font-semibold">{item.value}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "overview" && (
          <Card>
            <CardHeader>
              <SectionHeader
                title="Ready for the next run"
                subtitle="Quick launch common tasks without leaving the panel."
              />
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-3">
              <Dialog>
                <DialogTrigger asChild>
                  <button className="panel-card flex flex-col gap-2 text-left">
                    <div className="flex items-center gap-3 text-primary">
                      <CloudCog className="h-5 w-5" />
                      <p className="text-sm font-semibold">Reindex memory</p>
                    </div>
                    <p className="text-xs text-mutedForeground">
                      Build embeddings from the latest session summaries.
                    </p>
                  </button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Reindex memory</DialogTitle>
                    <DialogDescription>
                      This will reprocess files in workspace/memory.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline">Cancel</Button>
                    <Button>Run now</Button>
                  </div>
                </DialogContent>
              </Dialog>
              <button className="panel-card flex flex-col gap-2 text-left">
                <div className="flex items-center gap-3 text-primary">
                  <FolderKanban className="h-5 w-5" />
                  <p className="text-sm font-semibold">Snapshot workspace</p>
                </div>
                <p className="text-xs text-mutedForeground">
                  Archive current workspace state for audit or restore.
                </p>
              </button>
            </CardContent>
          </Card>
        )}

        {active !== "overview" && active !== "sessions" && active !== "tools" && active !== "jobs" && active !== "memory" && active !== "sandbox" && active !== "security" && active !== "settings" && active !== "activity" && (
          <Card>
            <CardHeader>
              <CardTitle>Coming soon</CardTitle>
              <CardDescription>This section is being wired to live data.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button>Connect API</Button>
            </CardContent>
          </Card>
        )}

        {active === "security" && (
          <Card>
            <CardHeader>
              <CardTitle>Escalation playbooks</CardTitle>
              <CardDescription>Define who is notified when approvals stall.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3">
                <div>
                  <p className="text-sm font-semibold">After 5 minutes</p>
                  <p className="text-xs text-mutedForeground">Ping #ops and DM admin</p>
                </div>
                <Button size="sm" variant="outline">
                  Edit
                </Button>
              </div>
              <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3">
                <div>
                  <p className="text-sm font-semibold">After 15 minutes</p>
                  <p className="text-xs text-mutedForeground">Auto-deny risky tools</p>
                </div>
                <Button size="sm" variant="outline">
                  Edit
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {active === "activity" && (
          <Card>
            <CardHeader>
              <CardTitle>Event stream</CardTitle>
              <CardDescription>Live updates from tool runs and sessions.</CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-56 rounded-2xl border border-border bg-card p-4 text-sm text-mutedForeground">
                <div className="space-y-2">
                  <p>[23:40] Tool shell approved by @gabriel</p>
                  <p>[23:39] Session sess_1d2f summarised and archived</p>
                  <p>[23:38] Browser action complete: screenshot saved</p>
                  <p>[23:37] Scheduler job job_1 queued</p>
                  <p>[23:36] Web fetch success: brave search</p>
                  <p>[23:35] Memory index updated</p>
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        )}

        {selectedSessionId && (
          <Dialog open={!!selectedSessionId} onOpenChange={(open) => !open && closeSessionDetail()}>
            <DialogContent className="max-w-6xl w-[95vw]">
              <DialogHeader>
                <DialogTitle>Session detail</DialogTitle>
                <DialogDescription>
                  Review conversation history, tool runs, and metadata for this session.
                </DialogDescription>
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
                <div className="grid gap-6">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-2xl border border-border bg-card p-4">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Session</p>
                      <p className="mt-2 text-sm font-semibold">{sessionDetail.id}</p>
                      <p className="mt-1 text-xs text-mutedForeground">
                        Status: {sessionDetail.status}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border bg-card p-4">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">User</p>
                      <div className="mt-2">{renderUser(sessionDetail.user)}</div>
                      <p className="mt-1 text-xs text-mutedForeground">
                        Last active {formatRelativeTime(sessionDetail.last_active_at)}
                      </p>
                    </div>
                  </div>
                  <Tabs defaultValue="messages">
                    <TabsList>
                      <TabsTrigger value="messages">Messages</TabsTrigger>
                      <TabsTrigger value="tools">Tool runs</TabsTrigger>
                    </TabsList>
                    <TabsContent value="messages">
                      <ScrollArea className="h-[520px] rounded-2xl border border-border bg-card p-4">
                        <div className="space-y-4">
                          {sessionTimeline.map((item) => {
                            if (item.type === "message") {
                              const message = item.data;
                              return (
                                <div key={item.id} className="rounded-2xl border border-border bg-muted/40 p-4">
                                  <div className="flex items-center justify-between text-xs text-mutedForeground">
                                    <span className="uppercase tracking-[0.2em]">{message.role}</span>
                                    <span>{formatRelativeTime(message.created_at)}</span>
                                  </div>
                                  <p className="mt-2 text-sm text-foreground whitespace-pre-wrap">{message.content}</p>
                                </div>
                              );
                            }
                            const tool = item.data;
                            return (
                              <div key={item.id} className="rounded-2xl border border-border bg-card p-4">
                                <div className="flex items-center justify-between text-xs text-mutedForeground">
                                  <span className="uppercase tracking-[0.2em]">
                                    Tool · {tool.tool}
                                  </span>
                                  <span>{formatRelativeTime(tool.created_at)}</span>
                                </div>
                                <div className="mt-2 flex items-center gap-2 text-xs text-mutedForeground">
                                  <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>
                                    {tool.status}
                                  </Badge>
                                  <span>
                                    Approved by{" "}
                                    {tool.approved_by
                                      ? userLabelFor(tool.approved_by)
                                      : "auto"}
                                  </span>
                                </div>
                                <div className="mt-3 grid gap-3 md:grid-cols-2">
                                  <div>
                                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                      Input
                                    </p>
                                    <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                                      {formatJsonPreview(tool.input)}
                                    </pre>
                                  </div>
                                  <div>
                                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                      Output
                                    </p>
                                    <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                                      {formatJsonPreview(tool.output)}
                                    </pre>
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </ScrollArea>
                    </TabsContent>
                    <TabsContent value="tools">
                      <ScrollArea className="h-[520px] rounded-2xl border border-border bg-card p-4">
                        <div className="space-y-4">
                          {sessionDetail.tool_runs.length ? (
                            sessionDetail.tool_runs.map((tool) => (
                              <div key={tool.id} className="rounded-2xl border border-border bg-muted/40 p-4">
                                <div className="flex items-center justify-between">
                                  <p className="text-sm font-semibold">{tool.tool}</p>
                                  <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>
                                    {tool.status}
                                  </Badge>
                                </div>
                                <p className="mt-1 text-xs text-mutedForeground">
                                  {formatRelativeTime(tool.created_at)} · Approved by{" "}
                                  {tool.approved_by ? userLabelFor(tool.approved_by) : "auto"}
                                </p>
                                <div className="mt-3 grid gap-4 md:grid-cols-2">
                                  <div>
                                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                      Input
                                    </p>
                                    <pre className="mt-2 rounded-2xl border border-border bg-card p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                                      {formatJsonPreview(tool.input)}
                                    </pre>
                                  </div>
                                  <div>
                                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                      Output
                                    </p>
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
        )}

        <footer className="flex items-center justify-between border-t border-border pt-4 text-xs text-mutedForeground">
          <div className="flex items-center gap-2">
            <Activity className="h-3 w-3" />
            Connected to Skittermander API
          </div>
          <div>v0.1.0 · Admin preview</div>
        </footer>
        </div>
      </div>
    </div>
  );
}
