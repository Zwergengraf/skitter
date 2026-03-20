import type {
  IncidentRow,
  MemoryRow,
  Metric,
  ScheduledJobRow,
  ServiceStatus,
  SessionRow,
  ToolRunRow,
} from "./types";

export const metrics: Metric[] = [
  { label: "Active sessions", value: 18, delta: "+4 today", trend: "up" },
  { label: "Tool runs", value: 146, delta: "+12%", trend: "up" },
  { label: "Avg latency", value: "1.7s", delta: "-0.4s", trend: "down" },
  { label: "Daily cost", value: "$12.84", delta: "+$2.10", trend: "up" },
];

export const services: ServiceStatus[] = [
  { name: "API", status: "healthy", detail: "200ms p95" },
  { name: "Scheduler", status: "healthy", detail: "12 jobs queued" },
  { name: "Sandbox", status: "warning", detail: "1 worker busy" },
  { name: "Browser", status: "healthy", detail: "Brave persistent" },
];

export const sessions: SessionRow[] = [
  {
    id: "sess_1d2f",
    user: "@user",
    transport: "discord",
    lastActive: "2 min ago",
    state: "active",
    tokens: 8421,
  },
  {
    id: "sess_9b31",
    user: "@founder",
    transport: "web",
    lastActive: "12 min ago",
    state: "idle",
    tokens: 3511,
  },
  {
    id: "sess_7f04",
    user: "@ops",
    transport: "discord",
    lastActive: "38 min ago",
    state: "paused",
    tokens: 1450,
  },
];

export const toolRuns: ToolRunRow[] = [
  {
    id: "tool_1",
    tool: "shell",
    status: "pending",
    requestedBy: "@user",
    createdAt: "Just now",
  },
  {
    id: "tool_2",
    tool: "browser_action",
    status: "running",
    requestedBy: "@founder",
    createdAt: "3 min ago",
  },
  {
    id: "tool_3",
    tool: "filesystem",
    status: "completed",
    requestedBy: "@ops",
    createdAt: "25 min ago",
  },
];

export const scheduledJobs: ScheduledJobRow[] = [
  {
    id: "job_1",
    name: "Morning news brief",
    schedule: "0 9 * * *",
    channel: "DM",
    nextRun: "Today, 09:00",
    status: "active",
  },
  {
    id: "job_2",
    name: "Weekly cost report",
    schedule: "0 8 * * 1",
    channel: "#ops",
    nextRun: "Mon, 08:00",
    status: "active",
  },
  {
    id: "job_3",
    name: "Memory reindex",
    schedule: "0 */6 * * *",
    channel: "DM",
    nextRun: "In 3h",
    status: "paused",
  },
];

export const memoryRows: MemoryRow[] = [
  {
    id: "mem_1",
    summary: "Feb 4 summary: sandbox, embeddings, approvals",
    updatedAt: "Today",
    embeddings: 12,
  },
  {
    id: "mem_2",
    summary: "Feb 3 summary: Discord sessions restored",
    updatedAt: "Yesterday",
    embeddings: 9,
  },
];

export const incidents: IncidentRow[] = [
  {
    id: "inc_1",
    title: "Browser screenshot timeout at 30s",
    severity: "medium",
    timestamp: "1h ago",
  },
  {
    id: "inc_2",
    title: "Brave sandbox pull delayed",
    severity: "low",
    timestamp: "Yesterday",
  },
];
