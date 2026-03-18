import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  Bot,
  Cable,
  Clock3,
  Database,
  Globe,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Plus,
  Search,
  Shield,
  Trash2,
  Wrench,
  RefreshCcw,
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
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { formatBytes, formatCurrency, formatJsonPreview, formatNumber, formatRelativeTime } from "@/lib/utils";
import {
  api,
  API_BASE,
  clearStoredApiKey,
  getStoredApiKey,
  setApiAuthFailureHandler,
  setStoredApiKey,
} from "@/lib/api";
import type { NavItemId } from "@/components/navigation";
import type {
  AgentJobDetail,
  AgentJobListItem,
  ChannelListItem,
  ConfigMcpServerItem,
  ConfigModelItem,
  ConfigProviderItem,
  ExecutorItem,
  MemoryEntry,
  OverviewResponse,
  RunTraceDetail,
  SandboxStatus,
  ConfigResponse,
  ScheduledJobItem,
  SecretItem,
  SessionDetail,
  SessionListItem,
  ToolRunListItem,
  UserListItem,
} from "@/lib/types";

const views: Record<NavItemId, string> = {
  overview: "Overview",
  sessions: "Sessions",
  tools: "Tool Runs",
  "agent-jobs": "Background Jobs",
  jobs: "Scheduled Jobs",
  memory: "Memory",
  secrets: "Secrets",
  users: "Users",
  sandbox: "Executors",
  settings: "Settings",
};

type OverviewRange = "today" | "24h" | "week" | "month" | "year";
type TableRange = "all" | "today" | "week" | "month";
type SettingsTabId = "core" | "models" | "automation" | "execution" | "integrations" | "advanced";
type StructuredValueType = "string" | "number" | "boolean" | "json";
type StructuredValueRow = {
  keyPath: string;
  valueType: StructuredValueType;
  value: string;
};

const SESSIONS_PAGE_SIZE = 25;
const TOOL_RUNS_PAGE_SIZE = 15;
const SCHEDULED_JOB_MODEL_MAIN = "__main_chain__";

const rangeStart = (range: TableRange): number | null => {
  const now = new Date();
  if (range === "all") {
    return null;
  }
  if (range === "today") {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  if (range === "week") {
    const start = new Date(now);
    const day = (start.getDay() + 6) % 7;
    start.setDate(start.getDate() - day);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  start.setHours(0, 0, 0, 0);
  return start.getTime();
};

const inRange = (value: string | null | undefined, range: TableRange): boolean => {
  const start = rangeStart(range);
  if (start == null) {
    return true;
  }
  if (!value) {
    return false;
  }
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) {
    return false;
  }
  return ts >= start;
};

const SETTINGS_TEXTAREA_FIELDS = new Set([
  "heartbeat_prompt",
  "user_approved_message",
  "cors_origins",
  "prompt_context_files",
  "tool_approval_tools",
]);

const SETTINGS_TAB_META: Record<
  SettingsTabId,
  { label: string; icon: typeof Activity; categories: string[] }
> = {
  core: {
    label: "Core",
    icon: Activity,
    categories: ["database", "prompt", "context", "logging", "users"],
  },
  models: {
    label: "Models",
    icon: Bot,
    categories: ["models", "reasoning"],
  },
  automation: {
    label: "Automation",
    icon: Clock3,
    categories: ["heartbeat", "jobs", "sub_agents", "scheduler"],
  },
  execution: {
    label: "Execution",
    icon: Wrench,
    categories: ["browser", "sandbox", "workspace", "tools"],
  },
  integrations: {
    label: "Integrations",
    icon: Globe,
    categories: ["web_search", "discord"],
  },
  advanced: {
    label: "Advanced",
    icon: Shield,
    categories: ["cors"],
  },
};

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const inferStructuredValueType = (value: unknown): StructuredValueType => {
  if (typeof value === "number") {
    return "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  if (typeof value === "string") {
    return "string";
  }
  return "json";
};

const stringifyStructuredValue = (value: unknown, valueType: StructuredValueType): string => {
  if (valueType === "json") {
    return JSON.stringify(value ?? {}, null, 2);
  }
  return String(value ?? "");
};

const flattenStructuredObject = (value: unknown, prefix = ""): StructuredValueRow[] => {
  if (!isPlainObject(value)) {
    return [];
  }
  const rows: StructuredValueRow[] = [];
  for (const [key, entryValue] of Object.entries(value)) {
    const keyPath = prefix ? `${prefix}.${key}` : key;
    if (isPlainObject(entryValue) && Object.keys(entryValue).length > 0) {
      rows.push(...flattenStructuredObject(entryValue, keyPath));
      continue;
    }
    const valueType = inferStructuredValueType(entryValue);
    rows.push({
      keyPath,
      valueType,
      value: stringifyStructuredValue(entryValue, valueType),
    });
  }
  return rows;
};

const parseStructuredValue = (row: StructuredValueRow): unknown => {
  if (row.valueType === "number") {
    const parsed = Number(row.value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (row.valueType === "boolean") {
    return row.value === "true";
  }
  if (row.valueType === "json") {
    return row.value.trim() ? JSON.parse(row.value) : {};
  }
  return row.value;
};

const expandStructuredRows = (rows: StructuredValueRow[]): Record<string, unknown> => {
  const result: Record<string, unknown> = {};
  for (const row of rows) {
    const trimmedPath = row.keyPath.trim();
    if (!trimmedPath) {
      continue;
    }
    const segments = trimmedPath
      .split(".")
      .map((segment) => segment.trim())
      .filter(Boolean);
    if (!segments.length) {
      continue;
    }
    let cursor: Record<string, unknown> = result;
    for (const segment of segments.slice(0, -1)) {
      const existing = cursor[segment];
      if (!isPlainObject(existing)) {
        cursor[segment] = {};
      }
      cursor = cursor[segment] as Record<string, unknown>;
    }
    cursor[segments[segments.length - 1]] = parseStructuredValue(row);
  }
  return result;
};

const uniqueStructuredKey = (existing: string[], base: string): string => {
  if (!existing.includes(base)) {
    return base;
  }
  let index = 2;
  while (existing.includes(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
};

const buildConfigDraft = (data: ConfigResponse): Record<string, unknown> => {
  const nextDraft: Record<string, unknown> = {};
  data.categories.forEach((category) => {
    category.fields.forEach((field) => {
      nextDraft[field.key] = field.value ?? "";
    });
  });
  nextDraft.providers = data.providers ?? [];
  nextDraft.models = data.models ?? [];
  nextDraft.mcp_servers = data.mcp_servers ?? [];
  return nextDraft;
};

export default function App() {
  const [active, setActive] = useState<NavItemId>("overview");
  const [filter, setFilter] = useState("all");
  const [sessionsRange, setSessionsRange] = useState<TableRange>("today");
  const [sessionsPage, setSessionsPage] = useState<number>(1);
  const [toolRunsRange, setToolRunsRange] = useState<TableRange>("today");
  const [toolRunsPage, setToolRunsPage] = useState<number>(1);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState<boolean>(false);
  const [overviewRange, setOverviewRange] = useState<OverviewRange>("week");
  const [sessionsData, setSessionsData] = useState<SessionListItem[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(false);
  const [toolRunsData, setToolRunsData] = useState<ToolRunListItem[]>([]);
  const [toolRunsError, setToolRunsError] = useState<string | null>(null);
  const [toolRunsLoading, setToolRunsLoading] = useState<boolean>(false);
  const [selectedToolRun, setSelectedToolRun] = useState<ToolRunListItem | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunTraceDetail | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState<boolean>(false);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);
  const [showRunReasoning, setShowRunReasoning] = useState<boolean>(false);
  const [toolRunToolFilter, setToolRunToolFilter] = useState<string>("all");
  const [toolRunUserFilter, setToolRunUserFilter] = useState<string>("all");
  const [toolRunExecutorFilter, setToolRunExecutorFilter] = useState<string>("all");
  const [showToolRunReasoning, setShowToolRunReasoning] = useState<boolean>(false);
  const [memoryData, setMemoryData] = useState<MemoryEntry[]>([]);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryLoading, setMemoryLoading] = useState<boolean>(false);
  const [secretsData, setSecretsData] = useState<SecretItem[]>([]);
  const [secretsError, setSecretsError] = useState<string | null>(null);
  const [secretsLoading, setSecretsLoading] = useState<boolean>(false);
  const [secretUserId, setSecretUserId] = useState<string>("");
  const [secretUserLabel, setSecretUserLabel] = useState<string>("");
  const [secretName, setSecretName] = useState<string>("");
  const [secretValue, setSecretValue] = useState<string>("");
  const [secretSaving, setSecretSaving] = useState<boolean>(false);
  const [selectedMemory, setSelectedMemory] = useState<MemoryEntry | null>(null);
  const [memoryDetailContent, setMemoryDetailContent] = useState<string>("");
  const [memoryDetailLoading, setMemoryDetailLoading] = useState<boolean>(false);
  const [memoryUserId, setMemoryUserId] = useState<string>("");
  const [memoryReindexing, setMemoryReindexing] = useState<boolean>(false);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null);
  const [sessionDetailError, setSessionDetailError] = useState<string | null>(null);
  const [sessionDetailLoading, setSessionDetailLoading] = useState<boolean>(false);
  const [showSessionReasoning, setShowSessionReasoning] = useState<boolean>(false);
  const [jobsData, setJobsData] = useState<ScheduledJobItem[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsLoading, setJobsLoading] = useState<boolean>(false);
  const [agentJobsData, setAgentJobsData] = useState<AgentJobListItem[]>([]);
  const [agentJobsError, setAgentJobsError] = useState<string | null>(null);
  const [agentJobsLoading, setAgentJobsLoading] = useState<boolean>(false);
  const [agentJobStatusFilter, setAgentJobStatusFilter] = useState<string>("all");
  const [agentJobUserFilter, setAgentJobUserFilter] = useState<string>("all");
  const [selectedAgentJobId, setSelectedAgentJobId] = useState<string | null>(null);
  const [selectedAgentJob, setSelectedAgentJob] = useState<AgentJobDetail | null>(null);
  const [selectedAgentJobLoading, setSelectedAgentJobLoading] = useState<boolean>(false);
  const [selectedAgentJobError, setSelectedAgentJobError] = useState<string | null>(null);
  const [usersData, setUsersData] = useState<UserListItem[]>([]);
  const [usersLoading, setUsersLoading] = useState<boolean>(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [userUpdating, setUserUpdating] = useState<Record<string, boolean>>({});
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null);
  const [executorsData, setExecutorsData] = useState<ExecutorItem[]>([]);
  const [sandboxLoading, setSandboxLoading] = useState<boolean>(false);
  const [sandboxError, setSandboxError] = useState<string | null>(null);
  const [executorOnboardingOpen, setExecutorOnboardingOpen] = useState<boolean>(false);
  const [executorOnboardingLoading, setExecutorOnboardingLoading] = useState<boolean>(false);
  const [executorOnboardingError, setExecutorOnboardingError] = useState<string | null>(null);
  const [executorDetailOpen, setExecutorDetailOpen] = useState<boolean>(false);
  const [selectedExecutor, setSelectedExecutor] = useState<ExecutorItem | null>(null);
  const [executorDetailSaving, setExecutorDetailSaving] = useState<boolean>(false);
  const [executorDetailDeleting, setExecutorDetailDeleting] = useState<boolean>(false);
  const [executorDetailError, setExecutorDetailError] = useState<string | null>(null);
  const [executorDetailForm, setExecutorDetailForm] = useState({
    name: "",
  });
  const [executorOnboardingResult, setExecutorOnboardingResult] = useState<{
    executorId: string;
    executorName: string;
    token: string;
    command: string;
    configYaml: string;
  } | null>(null);
  const [executorForm, setExecutorForm] = useState({
    user_id: "",
    name: "",
    api_url: API_BASE,
    workspace_root: "workspace",
  });
  const [configData, setConfigData] = useState<ConfigResponse | null>(null);
  const [configDraft, setConfigDraft] = useState<Record<string, unknown>>({});
  const [configLoading, setConfigLoading] = useState<boolean>(false);
  const [configSaving, setConfigSaving] = useState<boolean>(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [draggingModelChain, setDraggingModelChain] = useState<{ fieldKey: string; index: number } | null>(null);
  const [openProviderItems, setOpenProviderItems] = useState<Record<number, boolean>>({});
  const [openModelItems, setOpenModelItems] = useState<Record<number, boolean>>({});
  const [openMcpItems, setOpenMcpItems] = useState<Record<number, boolean>>({});
  const [settingsTab, setSettingsTab] = useState<SettingsTabId>("core");
  const [settingsQuery, setSettingsQuery] = useState<string>("");
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
    model: SCHEDULED_JOB_MODEL_MAIN,
    schedule_type: "cron",
    schedule_expr: "",
    schedule_date: "",
    schedule_time: "",
    enabled: true,
  });
  const [adminApiKey, setAdminApiKey] = useState<string>(() => getStoredApiKey());
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState<boolean>(() => !getStoredApiKey().trim());
  const [apiKeyDraft, setApiKeyDraft] = useState<string>(() => getStoredApiKey());
  const [apiKeyDialogError, setApiKeyDialogError] = useState<string | null>(null);
  const [apiKeySaving, setApiKeySaving] = useState<boolean>(false);
  const [isDark, setIsDark] = useState<boolean>(() => {
    const stored = localStorage.getItem("theme");
    return stored ? stored === "dark" : true;
  });
  const sessionMessagesEndRef = useRef<HTMLDivElement | null>(null);

  const activeLabel = views[active];
  const apiReady = adminApiKey.trim().length > 0;
  const maskedAdminApiKey = apiReady ? `••••${adminApiKey.slice(-4)}` : "Not configured";

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    localStorage.setItem("theme", isDark ? "dark" : "light");
  }, [isDark]);

  useEffect(() => {
    setApiAuthFailureHandler((error) => {
      clearStoredApiKey();
      setAdminApiKey("");
      setApiKeyDraft("");
      setApiKeyDialogError(error.message || "The admin API key was rejected.");
      setApiKeyDialogOpen(true);
    });
    return () => {
      setApiAuthFailureHandler(null);
    };
  }, []);

  useEffect(() => {
    if (!apiReady || active !== "overview") {
      return;
    }
    let isMounted = true;
    setOverviewLoading(true);
    setOverviewError(null);
    api
      .getOverview(overviewRange)
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
  }, [active, overviewRange, apiReady]);

  const overviewSessions = overview?.live_sessions ?? [];
  const overviewToolRuns = overview?.tool_approvals ?? [];
  const overviewHealth = overview?.system_health ?? [];
  const overviewCost = overview?.cost_trajectory ?? [];
  const sandboxContainers = sandboxStatus?.containers ?? [];
  const sandboxWorkspaces = sandboxStatus?.workspaces ?? [];
  const visibleExecutors = executorsData.filter((executor) => executor.kind !== "docker");
  const onlineExecutors = visibleExecutors.filter((executor) => executor.online && !executor.disabled).length;
  const approvedUsers = usersData.filter((user) => user.approved);
  const configProviders = (Array.isArray(configDraft.providers) ? configDraft.providers : []) as ConfigProviderItem[];
  const configModels = (Array.isArray(configDraft.models) ? configDraft.models : []) as ConfigModelItem[];
  const configMcpServers = (Array.isArray(configDraft.mcp_servers) ? configDraft.mcp_servers : []) as ConfigMcpServerItem[];
  const availableModelSelectors = useMemo(
    () =>
      configModels
        .filter((model) => model.provider?.trim() && model.name?.trim())
        .map((model) => `${model.provider.trim()}/${model.name.trim()}`),
    [configModels],
  );
  const settingsQueryNormalized = settingsQuery.trim().toLowerCase();
  const filteredConfigCategories = useMemo(() => {
    if (!configData) {
      return [] as ConfigResponse["categories"];
    }
    return configData.categories
      .map((category) => {
        if (!settingsQueryNormalized) {
          return category;
        }
        const categoryMatches = category.label.toLowerCase().includes(settingsQueryNormalized);
        const fields = category.fields.filter((field) => {
          const haystack = [
            field.label,
            field.key,
            field.description ?? "",
          ]
            .join(" ")
            .toLowerCase();
          return categoryMatches || haystack.includes(settingsQueryNormalized);
        });
        return { ...category, fields };
      })
      .filter((category) => category.fields.length > 0);
  }, [configData, settingsQueryNormalized]);
  const settingsCategoriesByTab = useMemo(() => {
    const entries = Object.entries(SETTINGS_TAB_META).map(([tabId, meta]) => {
      const categories = filteredConfigCategories.filter((category) => meta.categories.includes(category.id));
      return [tabId, categories] as const;
    });
    return Object.fromEntries(entries) as Record<SettingsTabId, ConfigResponse["categories"]>;
  }, [filteredConfigCategories]);
  const settingsProviderCount = configProviders.length;
  const settingsModelCount = configModels.length;
  const settingsMcpCount = configMcpServers.length;
  const sessionsByLastActive = useMemo(() => {
    const toTs = (value: string | null | undefined) => {
      if (!value) return 0;
      const parsed = Date.parse(value);
      return Number.isNaN(parsed) ? 0 : parsed;
    };
    return [...sessionsData].sort((a, b) => {
      const diff = toTs(b.last_active_at) - toTs(a.last_active_at);
      if (diff !== 0) {
        return diff;
      }
      if (a.status === b.status) {
        return 0;
      }
      if (a.status === "active") {
        return -1;
      }
      if (b.status === "active") {
        return 1;
      }
      return 0;
    });
  }, [sessionsData]);
  const visibleSessions = useMemo(() => {
    return sessionsByLastActive.filter((session) => inRange(session.last_active_at, sessionsRange));
  }, [sessionsByLastActive, sessionsRange]);
  const sessionsPageCount = Math.max(1, Math.ceil(visibleSessions.length / SESSIONS_PAGE_SIZE));
  const pagedSessions = useMemo(() => {
    const clampedPage = Math.min(sessionsPage, sessionsPageCount);
    const start = (clampedPage - 1) * SESSIONS_PAGE_SIZE;
    return visibleSessions.slice(start, start + SESSIONS_PAGE_SIZE);
  }, [visibleSessions, sessionsPage, sessionsPageCount]);
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
    if (!apiReady || active !== "sessions") {
      return;
    }
    refreshSessions();
  }, [active, filter, apiReady]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");
    if (sessionId) {
      setSelectedSessionId(sessionId);
    }
  }, []);

  useEffect(() => {
    if (!apiReady || !selectedSessionId) {
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
  }, [selectedSessionId, apiReady]);

  useEffect(() => {
    if (!selectedSessionId || !sessionDetail) {
      return;
    }
    const scrollToBottom = () => {
      sessionMessagesEndRef.current?.scrollIntoView({ block: "end" });
    };
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(scrollToBottom);
    });
    return () => cancelAnimationFrame(raf);
  }, [selectedSessionId, sessionDetail]);

  useEffect(() => {
    if (!apiReady || active !== "tools") {
      setSelectedToolRun(null);
      setSelectedRunId(null);
      return;
    }
    refreshToolRuns();
  }, [active, apiReady]);

  useEffect(() => {
    if (!apiReady || !selectedRunId) {
      setRunDetail(null);
      setRunDetailError(null);
      return;
    }
    setRunDetailLoading(true);
    setRunDetailError(null);
    api
      .getRunDetail(selectedRunId)
      .then((data) => {
        setRunDetail(data);
      })
      .catch((error: Error) => {
        setRunDetailError(error.message);
      })
      .finally(() => {
        setRunDetailLoading(false);
      });
  }, [selectedRunId, apiReady]);

  useEffect(() => {
    if (!apiReady || !selectedAgentJobId) {
      setSelectedAgentJob(null);
      setSelectedAgentJobError(null);
      return;
    }
    setSelectedAgentJobLoading(true);
    setSelectedAgentJobError(null);
    api
      .getAgentJob(selectedAgentJobId)
      .then((data) => {
        setSelectedAgentJob(data);
      })
      .catch((error: Error) => {
        setSelectedAgentJobError(error.message);
      })
      .finally(() => {
        setSelectedAgentJobLoading(false);
      });
  }, [selectedAgentJobId, apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "memory") {
      return;
    }
    const userId =
      memoryUserId && usersData.some((user) => user.id === memoryUserId)
        ? memoryUserId
        : usersData[0]?.id;
    if (!userId) {
      setMemoryData([]);
      setMemoryError("No users found yet.");
      setMemoryLoading(false);
      return;
    }
    if (userId !== memoryUserId) {
      setMemoryUserId(userId);
    }
    refreshMemory(userId);
  }, [active, usersData, apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "secrets") {
      return;
    }
    const userId = secretUserId || usersData[0]?.id;
    if (!userId) {
      setSecretsData([]);
      setSecretsError("No users found yet.");
      setSecretsLoading(false);
      return;
    }
    if (userId !== secretUserId) {
      setSecretUserId(userId);
      setSecretUserLabel(userLabelFor(userId));
    }
    refreshSecrets(userId);
  }, [active, usersData, secretUserId, apiReady]);

  useEffect(() => {
    if (!apiReady || !selectedMemory?.source) {
      setMemoryDetailContent("");
      return;
    }
    setMemoryDetailLoading(true);
    api
      .getMemoryFile(selectedMemory.source, memoryUserId)
      .then((data) => {
        setMemoryDetailContent(data.content);
      })
      .catch((error: Error) => {
        setMemoryError(error.message);
      })
      .finally(() => {
        setMemoryDetailLoading(false);
      });
  }, [selectedMemory, memoryUserId, apiReady]);

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

  const handleSecretSave = async () => {
    if (!secretUserId) {
      setSecretsError("No user selected for secrets.");
      return;
    }
    if (!secretName.trim() || !secretValue) {
      setSecretsError("Secret name and value are required.");
      return;
    }
    setSecretSaving(true);
    setSecretsError(null);
    try {
      await api.upsertSecret({
        user_id: secretUserId,
        name: secretName.trim(),
        value: secretValue,
      });
      setSecretName("");
      setSecretValue("");
      refreshSecrets(secretUserId);
    } catch (error) {
      setSecretsError((error as Error).message);
    } finally {
      setSecretSaving(false);
    }
  };

  const handleSecretDelete = async (name: string) => {
    if (!secretUserId) {
      setSecretsError("No user selected for secrets.");
      return;
    }
    try {
      await api.deleteSecret(secretUserId, name);
      refreshSecrets(secretUserId);
    } catch (error) {
      setSecretsError((error as Error).message);
    }
  };

  const updateConfigValue = (key: string, value: unknown) => {
    setConfigDraft((prev) => ({ ...prev, [key]: value }));
  };

  const updateStructuredObjectRows = (
    currentValue: Record<string, unknown> | undefined,
    nextRows: StructuredValueRow[],
    onValid: (value: Record<string, unknown>) => void,
    errorMessage: string,
  ) => {
    try {
      const nextValue = expandStructuredRows(nextRows);
      onValid(nextValue);
      setConfigError(null);
    } catch {
      onValid(currentValue ?? {});
      setConfigError(errorMessage);
    }
  };

  const updateStructuredRow = (
    rows: StructuredValueRow[],
    index: number,
    patch: Partial<StructuredValueRow>,
  ): StructuredValueRow[] => rows.map((row, currentIndex) => (
    currentIndex === index ? { ...row, ...patch } : row
  ));

  const reorderListValues = (values: string[], fromIndex: number, toIndex: number): string[] => {
    if (
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex >= values.length ||
      toIndex >= values.length
    ) {
      return values;
    }
    const next = [...values];
    const [item] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, item);
    return next;
  };

  const saveConfig = async () => {
    if (!configData) {
      return;
    }
    setConfigSaving(true);
    setConfigError(null);
    try {
      const response = await api.updateConfig({
        ...configDraft,
        providers: configProviders,
        models: configModels,
        mcp_servers: configMcpServers,
      });
      setConfigData(response);
      setConfigDraft(buildConfigDraft(response));
    } catch (error) {
      setConfigError((error as Error).message);
    } finally {
      setConfigSaving(false);
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

  const handleUserDeny = async (userId: string) => {
    setUserUpdating((prev) => ({ ...prev, [userId]: true }));
    setUsersError(null);
    try {
      await api.deleteUser(userId);
      setUsersData((prev) => prev.filter((user) => user.id !== userId));
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

  const refreshAgentJobs = () => {
    setAgentJobsLoading(true);
    setAgentJobsError(null);
    api
      .getAgentJobs()
      .then((data) => {
        setAgentJobsData(data);
      })
      .catch((error: Error) => {
        setAgentJobsError(error.message);
      })
      .finally(() => {
        setAgentJobsLoading(false);
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

  const refreshSandbox = () => {
    setSandboxLoading(true);
    setSandboxError(null);
    Promise.all([api.getSandboxStatus(), api.getExecutors()])
      .then(([sandboxData, executors]) => {
        setSandboxStatus(sandboxData);
        setExecutorsData(executors);
      })
      .catch((error: Error) => {
        setSandboxError(error.message);
      })
      .finally(() => {
        setSandboxLoading(false);
      });
  };

  const runExecutorOnboarding = async () => {
    const userId = executorForm.user_id.trim();
    const name = executorForm.name.trim();
    if (!userId) {
      setExecutorOnboardingError("Select an approved user.");
      return;
    }
    if (!name) {
      setExecutorOnboardingError("Executor name is required.");
      return;
    }

    setExecutorOnboardingLoading(true);
    setExecutorOnboardingError(null);
    setExecutorOnboardingResult(null);

    try {
      const executor = await api.createExecutor({
        user_id: userId,
        name,
        kind: "node",
      });
      const token = await api.createExecutorToken({
        user_id: userId,
        executor_id: executor.id,
      });

      const apiUrl = executorForm.api_url.trim().replace(/\/+$/, "");
      const workspaceRoot = executorForm.workspace_root.trim() || "workspace";
      const command =
        `skitter-node --api-url "${apiUrl}" ` +
        `--token "${token.token}" ` +
        `--name "${executor.name}" ` +
        `--workspace-root "${workspaceRoot}" --write-config`;
      const configYaml =
        `api_url: ${apiUrl}\n` +
        `token: ${token.token}\n` +
        `name: ${executor.name}\n` +
        `workspace_root: ${workspaceRoot}\n` +
        `heartbeat_seconds: 10\n` +
        `reconnect_seconds: 3\n` +
        `request_timeout_seconds: 300\n` +
        `capabilities:\n` +
        `  tools:\n` +
        `    - read\n` +
        `    - write\n` +
        `    - edit\n` +
        `    - list\n` +
        `    - delete\n` +
        `    - download\n` +
        `    - http_fetch\n` +
        `    - shell\n` +
        `    - browser\n` +
        `    - browser_action\n`;

      setExecutorOnboardingResult({
        executorId: executor.id,
        executorName: executor.name,
        token: token.token,
        command,
        configYaml,
      });
      refreshSandbox();
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExecutorOnboardingError(message);
    } finally {
      setExecutorOnboardingLoading(false);
    }
  };

  const openExecutorDetail = (executor: ExecutorItem) => {
    setSelectedExecutor(executor);
    setExecutorDetailForm({
      name: executor.name ?? "",
    });
    setExecutorDetailError(null);
    setExecutorDetailOpen(true);
  };

  const saveExecutorDetail = async () => {
    if (!selectedExecutor) {
      return;
    }
    const name = executorDetailForm.name.trim();
    if (!name) {
      setExecutorDetailError("Executor name is required.");
      return;
    }
    setExecutorDetailSaving(true);
    setExecutorDetailError(null);
    try {
      const updated = await api.updateExecutor(selectedExecutor.id, {
        name,
      });
      setExecutorsData((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setSelectedExecutor(updated);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExecutorDetailError(message);
    } finally {
      setExecutorDetailSaving(false);
    }
  };

  const disableExecutor = async () => {
    if (!selectedExecutor) {
      return;
    }
    setExecutorDetailDeleting(true);
    setExecutorDetailError(null);
    try {
      const updated = await api.disableExecutor(selectedExecutor.id);
      setExecutorsData((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setSelectedExecutor(updated);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExecutorDetailError(message);
    } finally {
      setExecutorDetailDeleting(false);
    }
  };

  const enableExecutor = async () => {
    if (!selectedExecutor) {
      return;
    }
    setExecutorDetailDeleting(true);
    setExecutorDetailError(null);
    try {
      const updated = await api.enableExecutor(selectedExecutor.id);
      setExecutorsData((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setSelectedExecutor(updated);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExecutorDetailError(message);
    } finally {
      setExecutorDetailDeleting(false);
    }
  };

  const deleteExecutor = async () => {
    if (!selectedExecutor) {
      return;
    }
    const confirmed = window.confirm(
      `Delete executor "${selectedExecutor.name}" permanently?\nThis cannot be undone.`
    );
    if (!confirmed) {
      return;
    }
    setExecutorDetailDeleting(true);
    setExecutorDetailError(null);
    try {
      await api.deleteExecutor(selectedExecutor.id);
      setExecutorDetailOpen(false);
      setSelectedExecutor(null);
      refreshSandbox();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExecutorDetailError(message);
    } finally {
      setExecutorDetailDeleting(false);
    }
  };

  const refreshOverview = () => {
    setOverviewLoading(true);
    setOverviewError(null);
    api
      .getOverview(overviewRange)
      .then((data) => {
        setOverview(data);
      })
      .catch((error: Error) => {
        setOverviewError(error.message);
      })
      .finally(() => {
        setOverviewLoading(false);
      });
  };

  const refreshToolRuns = () => {
    setToolRunsLoading(true);
    setToolRunsError(null);
    api
      .getToolRuns()
      .then((data) => {
        setToolRunsData(data);
      })
      .catch((error: Error) => {
        setToolRunsError(error.message);
      })
      .finally(() => {
        setToolRunsLoading(false);
      });
  };

  const refreshSessions = () => {
    setSessionsLoading(true);
    setSessionsError(null);
    api
      .getSessions(filter)
      .then((data) => {
        setSessionsData(data);
      })
      .catch((error: Error) => {
        setSessionsError(error.message);
      })
      .finally(() => {
        setSessionsLoading(false);
      });
  };

  const refreshMemory = (targetUserId?: string) => {
    const resolvedUserId = targetUserId || memoryUserId;
    if (!resolvedUserId) {
      setMemoryError("No user selected for memory.");
      return;
    }
    setMemoryLoading(true);
    setMemoryError(null);
    api
      .getMemory(resolvedUserId)
      .then((data) => {
        setMemoryData(data);
      })
      .catch((error: Error) => {
        setMemoryError(error.message);
      })
      .finally(() => {
        setMemoryLoading(false);
      });
  };

  const refreshSecrets = (targetUserId?: string) => {
    const resolvedUserId = targetUserId || secretUserId;
    if (!resolvedUserId) {
      setSecretsError("No user selected for secrets.");
      return;
    }
    setSecretsLoading(true);
    setSecretsError(null);
    api
      .getSecrets(resolvedUserId)
      .then((data) => {
        setSecretsData(data);
      })
      .catch((error: Error) => {
        setSecretsError(error.message);
      })
      .finally(() => {
        setSecretsLoading(false);
      });
  };

  const refreshConfig = () => {
    setConfigLoading(true);
    setConfigError(null);
    api
      .getConfig()
      .then((data) => {
        setConfigData(data);
        setConfigDraft(buildConfigDraft(data));
      })
      .catch((error: Error) => {
        setConfigError(error.message);
      })
      .finally(() => {
        setConfigLoading(false);
      });
  };

  const handleRefreshActive = () => {
    switch (active) {
      case "overview":
        refreshOverview();
        break;
      case "sessions":
        refreshSessions();
        break;
      case "tools":
        refreshToolRuns();
        break;
      case "agent-jobs":
        refreshAgentJobs();
        break;
      case "jobs":
        refreshJobs();
        break;
      case "memory":
        refreshMemory();
        break;
      case "secrets":
        refreshSecrets();
        break;
      case "users":
        refreshUsers();
        break;
      case "sandbox":
        refreshSandbox();
        break;
      case "settings":
        refreshConfig();
        break;
      default:
        break;
    }
  };

  useEffect(() => {
    if (!apiReady) {
      return;
    }
    refreshDirectories();
  }, [apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "agent-jobs") {
      setSelectedAgentJobId(null);
      return;
    }
    refreshAgentJobs();
  }, [active, apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "jobs") {
      return;
    }
    refreshJobs();
    if (!configData) {
      refreshConfig();
    }
  }, [active, apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "users") {
      return;
    }
    refreshUsers();
  }, [active, apiReady]);

  useEffect(() => {
    if (!apiReady || active !== "sandbox") {
      return;
    }
    refreshSandbox();
  }, [active, apiReady]);

  useEffect(() => {
    if (executorForm.user_id) {
      return;
    }
    const firstApproved = usersData.find((user) => user.approved);
    if (!firstApproved) {
      return;
    }
    setExecutorForm((current) => ({ ...current, user_id: firstApproved.id }));
  }, [usersData, executorForm.user_id]);

  useEffect(() => {
    if (!apiReady || active !== "settings") {
      return;
    }
    refreshConfig();
  }, [active, apiReady]);

  useEffect(() => {
    setSessionsPage(1);
  }, [sessionsRange, filter]);

  useEffect(() => {
    if (sessionsPage > sessionsPageCount) {
      setSessionsPage(sessionsPageCount);
    }
  }, [sessionsPage, sessionsPageCount]);

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

  const toolRunTools = useMemo(() => {
    return Array.from(
      new Set(toolRunsData.map((tool) => tool.tool).filter((tool): tool is string => Boolean(tool)))
    ).sort((a, b) => a.localeCompare(b));
  }, [toolRunsData]);

  const toolRunUsers = useMemo(() => {
    return Array.from(
      new Set(
        toolRunsData
          .map((tool) => tool.requested_by)
          .filter((userId): userId is string => Boolean(userId))
      )
    ).sort((a, b) => userLabelFor(a).localeCompare(userLabelFor(b)));
  }, [toolRunsData, usersData]);

  const toolRunExecutors = useMemo(() => {
    return Array.from(
      new Set(
        toolRunsData
          .map((tool) => tool.executor_id || "")
          .filter((executorId): executorId is string => Boolean(executorId))
      )
    ).sort((a, b) => a.localeCompare(b));
  }, [toolRunsData]);

  const filteredToolRuns = useMemo(() => {
    return toolRunsData.filter((tool) => {
      if (toolRunToolFilter !== "all" && tool.tool !== toolRunToolFilter) {
        return false;
      }
      if (toolRunUserFilter !== "all" && tool.requested_by !== toolRunUserFilter) {
        return false;
      }
      if (toolRunExecutorFilter !== "all" && (tool.executor_id || "") !== toolRunExecutorFilter) {
        return false;
      }
      return true;
    });
  }, [toolRunsData, toolRunToolFilter, toolRunUserFilter, toolRunExecutorFilter]);
  const visibleToolRuns = useMemo(() => {
    return filteredToolRuns.filter((tool) => inRange(tool.created_at, toolRunsRange));
  }, [filteredToolRuns, toolRunsRange]);
  const toolRunsPageCount = Math.max(1, Math.ceil(visibleToolRuns.length / TOOL_RUNS_PAGE_SIZE));
  const pagedToolRuns = useMemo(() => {
    const clampedPage = Math.min(toolRunsPage, toolRunsPageCount);
    const start = (clampedPage - 1) * TOOL_RUNS_PAGE_SIZE;
    return visibleToolRuns.slice(start, start + TOOL_RUNS_PAGE_SIZE);
  }, [visibleToolRuns, toolRunsPage, toolRunsPageCount]);

  useEffect(() => {
    setToolRunsPage(1);
  }, [toolRunsRange, toolRunToolFilter, toolRunUserFilter, toolRunExecutorFilter]);

  useEffect(() => {
    if (toolRunsPage > toolRunsPageCount) {
      setToolRunsPage(toolRunsPageCount);
    }
  }, [toolRunsPage, toolRunsPageCount]);

  const openApiKeyDialog = () => {
    setApiKeyDraft(adminApiKey);
    setApiKeyDialogError(null);
    setApiKeyDialogOpen(true);
  };

  const closeApiKeyDialog = () => {
    if (!apiReady) {
      return;
    }
    setApiKeyDraft(adminApiKey);
    setApiKeyDialogError(null);
    setApiKeyDialogOpen(false);
  };

  const clearAdminApiKey = () => {
    clearStoredApiKey();
    setAdminApiKey("");
    setApiKeyDraft("");
    setApiKeyDialogError(null);
    setApiKeyDialogOpen(true);
  };

  const saveAdminApiKey = async () => {
    const cleaned = apiKeyDraft.trim();
    if (!cleaned) {
      setApiKeyDialogError("Admin API key is required.");
      return;
    }

    setApiKeySaving(true);
    setApiKeyDialogError(null);
    try {
      await api.validateAdminApiKey(cleaned);
      setStoredApiKey(cleaned);
      setAdminApiKey(cleaned);
      setApiKeyDraft(cleaned);
      setApiKeyDialogOpen(false);
      refreshDirectories();
      handleRefreshActive();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setApiKeyDialogError(message);
    } finally {
      setApiKeySaving(false);
    }
  };

  const agentJobUsers = useMemo(() => {
    return Array.from(
      new Set(
        agentJobsData
          .map((job) => job.user_id)
          .filter((userId): userId is string => Boolean(userId))
      )
    ).sort((a, b) => userLabelFor(a).localeCompare(userLabelFor(b)));
  }, [agentJobsData, usersData]);

  const agentJobStatuses = useMemo(() => {
    return Array.from(
      new Set(
        agentJobsData
          .map((job) => job.status)
          .filter((status): status is string => Boolean(status))
      )
    ).sort((a, b) => a.localeCompare(b));
  }, [agentJobsData]);

  const filteredAgentJobs = useMemo(() => {
    return agentJobsData.filter((job) => {
      if (agentJobStatusFilter !== "all" && job.status !== agentJobStatusFilter) {
        return false;
      }
      if (agentJobUserFilter !== "all" && job.user_id !== agentJobUserFilter) {
        return false;
      }
      return true;
    });
  }, [agentJobsData, agentJobStatusFilter, agentJobUserFilter]);

  const agentJobStatusCounts = useMemo(() => {
    return agentJobsData.reduce<Record<string, number>>((acc, job) => {
      acc[job.status] = (acc[job.status] ?? 0) + 1;
      return acc;
    }, {});
  }, [agentJobsData]);

  const formatFullJson = (value: unknown) => {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return String(value ?? "");
    }
  };

  const normalizeReasoning = (value: unknown): string[] => {
    if (typeof value === "string") {
      const normalized = value.trim();
      return normalized ? [normalized] : [];
    }
    if (!Array.isArray(value)) {
      return [];
    }
    const chunks: string[] = [];
    for (const item of value) {
      if (typeof item !== "string") {
        continue;
      }
      const normalized = item.trim();
      if (normalized) {
        chunks.push(normalized);
      }
    }
    return chunks;
  };

  const messageReasoning = (meta: Record<string, unknown> | undefined): string[] => {
    if (!meta) {
      return [];
    }
    return normalizeReasoning(meta.reasoning);
  };

  const toolRunReasoning = (tool: ToolRunListItem): string[] => {
    return normalizeReasoning(tool.reasoning);
  };

  const runDetailReasoning = useMemo(() => {
    if (!runDetail) {
      return [];
    }
    const chunks: string[] = [];
    const seen = new Set<string>();
    for (const event of runDetail.events) {
      if (event.event_type !== "reasoning") {
        continue;
      }
      const payload = event.payload as Record<string, unknown> | undefined;
      const eventChunks = normalizeReasoning(payload?.chunks);
      for (const chunk of eventChunks) {
        if (seen.has(chunk)) {
          continue;
        }
        seen.add(chunk);
        chunks.push(chunk);
      }
    }
    return chunks;
  }, [runDetail]);

  const extractAgentJobTranscript = (job: AgentJobDetail | null): Array<{ role: string; content: string }> => {
    if (!job) {
      return [];
    }
    const worker = (job.result as Record<string, unknown>)?.worker;
    if (!worker || typeof worker !== "object") {
      return [];
    }
    const transcript = (worker as Record<string, unknown>).transcript;
    if (!Array.isArray(transcript)) {
      return [];
    }
    return transcript
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
      .map((item) => ({
        role: String(item.role ?? "message"),
        content: String(item.content ?? ""),
      }))
      .filter((item) => Boolean(item.content));
  };

  const formatDuration = (durationMs?: number | null) => {
    if (!durationMs || durationMs <= 0) {
      return "—";
    }
    if (durationMs < 1000) {
      return `${durationMs} ms`;
    }
    const seconds = durationMs / 1000;
    if (seconds < 60) {
      return `${seconds.toFixed(1)} s`;
    }
    const minutes = Math.floor(seconds / 60);
    const rem = Math.round(seconds % 60);
    return `${minutes}m ${rem}s`;
  };

  const computeAgentJobDurationMs = (job: AgentJobListItem): number | null => {
    if (!job.started_at) {
      return null;
    }
    const startMs = new Date(job.started_at).getTime();
    if (!Number.isFinite(startMs)) {
      return null;
    }
    const endMs = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
    if (!Number.isFinite(endMs) || endMs < startMs) {
      return null;
    }
    return endMs - startMs;
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
      model: SCHEDULED_JOB_MODEL_MAIN,
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
      model: job.model || SCHEDULED_JOB_MODEL_MAIN,
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
          model: jobForm.model,
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
          model: jobForm.model,
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

  const renderConfigInput = (field: ConfigResponse["categories"][number]["fields"][number]) => {
    if (field.key === "main_model" || field.key === "heartbeat_model") {
      const chain = Array.isArray(configDraft[field.key])
        ? (configDraft[field.key] as string[])
        : typeof configDraft[field.key] === "string" && configDraft[field.key]
          ? String(configDraft[field.key])
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : [];
      const remainingOptions = availableModelSelectors.filter((item) => !chain.includes(item));

      return (
        <div className="space-y-3">
          <div className="space-y-2 rounded-2xl border border-border/70 bg-background/70 p-3">
            {chain.length ? (
              chain.map((item, index) => (
                <div
                  key={`${field.key}-${item}-${index}`}
                  draggable
                  onDragStart={() => setDraggingModelChain({ fieldKey: field.key, index })}
                  onDragEnd={() => setDraggingModelChain(null)}
                  onDragOver={(event) => {
                    if (draggingModelChain?.fieldKey === field.key) {
                      event.preventDefault();
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    if (!draggingModelChain || draggingModelChain.fieldKey !== field.key) {
                      return;
                    }
                    updateConfigValue(field.key, reorderListValues(chain, draggingModelChain.index, index));
                    setDraggingModelChain(null);
                  }}
                  className="flex items-center gap-3 rounded-xl border border-border/60 bg-card/90 px-3 py-2"
                >
                  <button
                    type="button"
                    className="cursor-grab text-mutedForeground transition hover:text-foreground active:cursor-grabbing"
                    aria-label="Drag to reorder"
                  >
                    <GripVertical className="h-4 w-4" />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{item}</p>
                    <p className="text-xs text-mutedForeground">Priority {index + 1}</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => updateConfigValue(field.key, chain.filter((_, currentIndex) => currentIndex !== index))}
                  >
                    Remove
                  </Button>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-mutedForeground">
                No models in this chain.
              </div>
            )}
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <Select
              value={undefined}
              onValueChange={(value) => {
                if (!value) {
                  return;
                }
                updateConfigValue(field.key, [...chain, value]);
              }}
            >
              <SelectTrigger className="md:max-w-md">
                <SelectValue placeholder={remainingOptions.length ? "Add model to chain" : "No unused models available"} />
              </SelectTrigger>
              <SelectContent>
                {remainingOptions.length ? (
                  remainingOptions.map((option) => (
                    <SelectItem key={`${field.key}-option-${option}`} value={option}>
                      {option}
                    </SelectItem>
                  ))
                ) : (
                  <SelectItem value="__none" disabled>
                    No unused models available
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
            <p className="text-xs text-mutedForeground">Drag entries to reorder the fallback chain.</p>
          </div>
        </div>
      );
    }
    if (field.type === "boolean") {
      return (
        <Switch
          checked={Boolean(configDraft[field.key])}
          onCheckedChange={(value) => updateConfigValue(field.key, value)}
        />
      );
    }
    if (field.type === "number") {
      return (
        <Input
          type="number"
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          step={field.step ?? 1}
          value={String(configDraft[field.key] ?? "")}
          onChange={(event) => updateConfigValue(field.key, Number(event.target.value))}
        />
      );
    }
    if (field.type === "list") {
      return (
        <Textarea
          rows={3}
          placeholder="item1, item2"
          value={Array.isArray(configDraft[field.key])
            ? (configDraft[field.key] as string[]).join(", ")
            : String(configDraft[field.key] ?? "")}
          onChange={(event) => updateConfigValue(field.key, event.target.value)}
        />
      );
    }
    if (SETTINGS_TEXTAREA_FIELDS.has(field.key)) {
      return (
        <Textarea
          rows={4}
          placeholder={field.secret ? "••••••••" : undefined}
          value={String(configDraft[field.key] ?? "")}
          onChange={(event) => updateConfigValue(field.key, event.target.value)}
        />
      );
    }
    return (
      <Input
        type={field.secret ? "password" : "text"}
        placeholder={field.secret ? "••••••••" : undefined}
        value={String(configDraft[field.key] ?? "")}
        onChange={(event) => updateConfigValue(field.key, event.target.value)}
      />
    );
  };

  const renderConfigCategoryCard = (category: ConfigResponse["categories"][number]) => (
    <Card key={category.id} className="border-border/80 bg-card/95 shadow-sm">
      <CardHeader className="space-y-1">
        <CardTitle className="text-base">{category.label}</CardTitle>
        <CardDescription>
          {category.fields.length} option{category.fields.length === 1 ? "" : "s"}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        {category.fields.map((field) => (
          <div
            key={field.key}
            className="rounded-2xl border border-border/70 bg-muted/20 p-4"
          >
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  {field.label}
                </label>
                <p className="mt-1 text-[11px] text-mutedForeground">{field.key}</p>
              </div>
              {field.type === "boolean" ? renderConfigInput(field) : null}
            </div>
            {field.type !== "boolean" ? renderConfigInput(field) : null}
            {field.description ? (
              <p className="mt-2 text-xs leading-relaxed text-mutedForeground">{field.description}</p>
            ) : null}
          </div>
        ))}
      </CardContent>
    </Card>
  );

  const updateProviderItem = (
    index: number,
    key: keyof ConfigProviderItem,
    value: string,
  ) => {
    const next = configProviders.map((item, currentIndex) =>
      currentIndex === index ? { ...item, [key]: value } : item
    );
    updateConfigValue("providers", next);
  };

  const addProviderItem = () => {
    setOpenProviderItems((prev) => ({ ...prev, [configProviders.length]: true }));
    updateConfigValue("providers", [
      ...configProviders,
      { name: "", api_type: "openai", api_base: "", api_key: "" },
    ]);
  };

  const removeProviderItem = (index: number) => {
    setOpenProviderItems((prev) => {
      const next: Record<number, boolean> = {};
      for (const [key, value] of Object.entries(prev)) {
        const numericKey = Number(key);
        if (numericKey < index) next[numericKey] = value;
        if (numericKey > index) next[numericKey - 1] = value;
      }
      return next;
    });
    updateConfigValue(
      "providers",
      configProviders.filter((_, currentIndex) => currentIndex !== index)
    );
  };

  const updateModelItem = (
    index: number,
    key: keyof ConfigModelItem,
    value: string | number | Record<string, unknown>,
  ) => {
    const next = configModels.map((item, currentIndex) =>
      currentIndex === index ? { ...item, [key]: value } : item
    );
    updateConfigValue("models", next);
  };

  const addModelItem = () => {
    setOpenModelItems((prev) => ({ ...prev, [configModels.length]: true }));
    updateConfigValue("models", [
      ...configModels,
      {
        name: "",
        provider: configProviders[0]?.name ?? "",
        model_id: "",
        input_cost_per_1m: 0,
        output_cost_per_1m: 0,
        reasoning: {},
      },
    ]);
  };

  const removeModelItem = (index: number) => {
    setOpenModelItems((prev) => {
      const next: Record<number, boolean> = {};
      for (const [key, value] of Object.entries(prev)) {
        const numericKey = Number(key);
        if (numericKey < index) next[numericKey] = value;
        if (numericKey > index) next[numericKey - 1] = value;
      }
      return next;
    });
    updateConfigValue(
      "models",
      configModels.filter((_, currentIndex) => currentIndex !== index)
    );
  };

  const updateMcpServerItem = (
    index: number,
    key: keyof ConfigMcpServerItem,
    value: unknown,
  ) => {
    const next = configMcpServers.map((item, currentIndex) =>
      currentIndex === index ? { ...item, [key]: value } : item
    );
    updateConfigValue("mcp_servers", next);
  };

  const addMcpServerItem = () => {
    setOpenMcpItems((prev) => ({ ...prev, [configMcpServers.length]: true }));
    updateConfigValue("mcp_servers", [
      ...configMcpServers,
      {
        name: "",
        description: "",
        transport: "stdio",
        command: "",
        args: [],
        url: "",
        headers: {},
        env: {},
        cwd: "",
        enabled: true,
        startup_timeout_seconds: 15,
        request_timeout_seconds: 120,
      },
    ]);
  };

  const removeMcpServerItem = (index: number) => {
    setOpenMcpItems((prev) => {
      const next: Record<number, boolean> = {};
      for (const [key, value] of Object.entries(prev)) {
        const numericKey = Number(key);
        if (numericKey < index) next[numericKey] = value;
        if (numericKey > index) next[numericKey - 1] = value;
      }
      return next;
    });
    updateConfigValue(
      "mcp_servers",
      configMcpServers.filter((_, currentIndex) => currentIndex !== index)
    );
  };

  const renderStructuredEditorShell = ({
    title,
    description,
    count,
    icon: Icon,
    onAdd,
    addLabel,
    children,
  }: {
    title: string;
    description: string;
    count: number;
    icon: typeof Activity;
    onAdd: () => void;
    addLabel: string;
    children: ReactNode;
  }) => (
    <Card className="border-border/80 bg-card/95 shadow-sm">
      <CardHeader className="space-y-1">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl border border-border/70 bg-muted/30 p-2 text-mutedForeground">
              <Icon className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base">{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{count}</Badge>
            <Button size="sm" variant="outline" onClick={onAdd}>
              <Plus className="mr-2 h-4 w-4" />
              {addLabel}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {children}
      </CardContent>
    </Card>
  );

  const renderProvidersEditor = () => (
    renderStructuredEditorShell({
      title: "Providers",
      description: "Provider endpoints, API types, and credentials.",
      count: settingsProviderCount,
      icon: Globe,
      onAdd: addProviderItem,
      addLabel: "Add provider",
      children: configProviders.length ? (
        configProviders.map((provider, index) => {
          const isOpen = openProviderItems[index] === true;
          return (
          <div key={`provider-${index}`} className="rounded-2xl border border-border/70 bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
                onClick={() => setOpenProviderItems((prev) => ({ ...prev, [index]: !isOpen }))}
              >
                {isOpen ? <ChevronDown className="h-4 w-4 text-mutedForeground" /> : <ChevronRight className="h-4 w-4 text-mutedForeground" />}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{provider.name || `Provider ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">{provider.api_base || "API endpoint and authentication"}</p>
                </div>
              </button>
              <Button size="sm" variant="outline" onClick={() => removeProviderItem(index)}>
                <Trash2 className="mr-2 h-4 w-4" />
                Remove
              </Button>
            </div>
            {isOpen ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Name</label>
                <Input
                  value={provider.name ?? ""}
                  onChange={(event) => updateProviderItem(index, "name", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">API Type</label>
                <Select
                  value={provider.api_type || "openai"}
                  onValueChange={(value) => updateProviderItem(index, "api_type", value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select API type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="openai">openai</SelectItem>
                    <SelectItem value="anthropic">anthropic</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">API Base</label>
                <Input
                  value={provider.api_base ?? ""}
                  onChange={(event) => updateProviderItem(index, "api_base", event.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">API Key</label>
                <Input
                  type="password"
                  placeholder="Leave blank to keep existing secret"
                  value={provider.api_key ?? ""}
                  onChange={(event) => updateProviderItem(index, "api_key", event.target.value)}
                />
              </div>
            </div>
            ) : null}
          </div>
        )})
      ) : (
        <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
          No providers configured.
        </div>
      ),
    })
  );

  const renderModelsEditor = () => (
    renderStructuredEditorShell({
      title: "Models",
      description: "Model registry, costs, and per-model reasoning overrides.",
      count: settingsModelCount,
      icon: Bot,
      onAdd: addModelItem,
      addLabel: "Add model",
      children: configModels.length ? (
        configModels.map((model, index) => {
          const reasoningRows = flattenStructuredObject(model.reasoning ?? {});
          const isOpen = openModelItems[index] === true;
          return (
          <div key={`model-${index}`} className="rounded-2xl border border-border/70 bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
                onClick={() => setOpenModelItems((prev) => ({ ...prev, [index]: !isOpen }))}
              >
                {isOpen ? <ChevronDown className="h-4 w-4 text-mutedForeground" /> : <ChevronRight className="h-4 w-4 text-mutedForeground" />}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{model.name || `Model ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">{model.provider ? `${model.provider}/${model.name || `model-${index + 1}`}` : "Model selector, provider, pricing"}</p>
                </div>
              </button>
              <Button size="sm" variant="outline" onClick={() => removeModelItem(index)}>
                <Trash2 className="mr-2 h-4 w-4" />
                Remove
              </Button>
            </div>
            {isOpen ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Name</label>
                <Input
                  value={model.name ?? ""}
                  onChange={(event) => updateModelItem(index, "name", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Provider</label>
                <Select
                  value={model.provider ?? ""}
                  onValueChange={(value) => updateModelItem(index, "provider", value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select provider" />
                  </SelectTrigger>
                  <SelectContent>
                    {configProviders.length ? (
                      configProviders.map((provider, providerIndex) => (
                        <SelectItem
                          key={`${provider.name || "provider"}-${providerIndex}`}
                          value={provider.name || `provider-${providerIndex}`}
                        >
                          {provider.name || `provider-${providerIndex}`}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__none" disabled>
                        No providers available
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Model ID</label>
                <Input
                  value={model.model_id ?? ""}
                  onChange={(event) => updateModelItem(index, "model_id", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input cost / 1M</label>
                <Input
                  type="number"
                  step="0.0001"
                  value={String(model.input_cost_per_1m ?? 0)}
                  onChange={(event) => updateModelItem(index, "input_cost_per_1m", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output cost / 1M</label>
                <Input
                  type="number"
                  step="0.0001"
                  value={String(model.output_cost_per_1m ?? 0)}
                  onChange={(event) => updateModelItem(index, "output_cost_per_1m", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Reasoning Overrides</label>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const nextRows = [
                        ...reasoningRows,
                        {
                          keyPath: uniqueStructuredKey(reasoningRows.map((row) => row.keyPath), "provider.setting"),
                          valueType: "string" as const,
                          value: "",
                        },
                      ];
                      updateStructuredObjectRows(
                        model.reasoning,
                        nextRows,
                        (value) => updateModelItem(index, "reasoning", value),
                        "Model reasoning overrides contain invalid values.",
                      );
                    }}
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Add override
                  </Button>
                </div>
                <div className="space-y-3 rounded-2xl border border-border/70 bg-background/70 p-3">
                  {reasoningRows.length ? (
                    reasoningRows.map((row, rowIndex) => (
                      <div key={`model-reasoning-${index}-${rowIndex}`} className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_160px_minmax(0,1fr)_auto] md:items-start">
                        <Input
                          value={row.keyPath}
                          placeholder="anthropic.budget_tokens"
                          onChange={(event) =>
                            updateStructuredObjectRows(
                              model.reasoning,
                              updateStructuredRow(reasoningRows, rowIndex, { keyPath: event.target.value }),
                              (value) => updateModelItem(index, "reasoning", value),
                              "Model reasoning overrides contain invalid values.",
                            )
                          }
                        />
                        <Select
                          value={row.valueType}
                          onValueChange={(value) =>
                            updateStructuredObjectRows(
                              model.reasoning,
                              updateStructuredRow(reasoningRows, rowIndex, { valueType: value as StructuredValueType }),
                              (nextValue) => updateModelItem(index, "reasoning", nextValue),
                              "Model reasoning overrides contain invalid values.",
                            )
                          }
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Type" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="string">String</SelectItem>
                            <SelectItem value="number">Number</SelectItem>
                            <SelectItem value="boolean">Boolean</SelectItem>
                            <SelectItem value="json">JSON</SelectItem>
                          </SelectContent>
                        </Select>
                        {row.valueType === "boolean" ? (
                          <Select
                            value={row.value === "true" ? "true" : "false"}
                            onValueChange={(value) =>
                              updateStructuredObjectRows(
                                model.reasoning,
                                updateStructuredRow(reasoningRows, rowIndex, { value }),
                                (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                "Model reasoning overrides contain invalid values.",
                              )
                            }
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Boolean" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="true">true</SelectItem>
                              <SelectItem value="false">false</SelectItem>
                            </SelectContent>
                          </Select>
                        ) : row.valueType === "json" ? (
                          <Textarea
                            className="min-h-[88px] font-mono text-xs"
                            value={row.value}
                            onChange={(event) =>
                              updateStructuredObjectRows(
                                model.reasoning,
                                updateStructuredRow(reasoningRows, rowIndex, { value: event.target.value }),
                                (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                "Model reasoning overrides contain invalid JSON.",
                              )
                            }
                          />
                        ) : (
                          <Input
                            type={row.valueType === "number" ? "number" : "text"}
                            value={row.value}
                            onChange={(event) =>
                              updateStructuredObjectRows(
                                model.reasoning,
                                updateStructuredRow(reasoningRows, rowIndex, { value: event.target.value }),
                                (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                "Model reasoning overrides contain invalid values.",
                              )
                            }
                          />
                        )}
                        <Button
                          size="icon"
                          variant="outline"
                          onClick={() =>
                            updateStructuredObjectRows(
                              model.reasoning,
                              reasoningRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                              (value) => updateModelItem(index, "reasoning", value),
                              "Model reasoning overrides contain invalid values.",
                            )
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-mutedForeground">
                      No per-model reasoning overrides configured.
                    </div>
                  )}
                </div>
              </div>
            </div>
            ) : null}
          </div>
        )})
      ) : (
        <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
          No models configured.
        </div>
      ),
    })
  );

  const renderMcpServersEditor = () => (
    renderStructuredEditorShell({
      title: "MCP Servers",
      description: "Configured MCP servers with transport, discovery text, and runtime settings.",
      count: settingsMcpCount,
      icon: Cable,
      onAdd: addMcpServerItem,
      addLabel: "Add MCP server",
      children: configMcpServers.length ? (
        configMcpServers.map((server, index) => {
          const headerRows = Object.entries(server.headers ?? {}).map(([key, value]) => ({
            keyPath: key,
            valueType: "string" as const,
            value: String(value ?? ""),
          }));
          const envRows = Object.entries(server.env ?? {}).map(([key, value]) => ({
            keyPath: key,
            valueType: "string" as const,
            value: String(value ?? ""),
          }));
          const isOpen = openMcpItems[index] === true;
          return (
          <div key={`mcp-${index}`} className="rounded-2xl border border-border/70 bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
                onClick={() => setOpenMcpItems((prev) => ({ ...prev, [index]: !isOpen }))}
              >
                {isOpen ? <ChevronDown className="h-4 w-4 text-mutedForeground" /> : <ChevronRight className="h-4 w-4 text-mutedForeground" />}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{server.name || `MCP Server ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">{server.transport === "http" ? (server.url || "HTTP transport") : (server.command || "stdio transport")}</p>
                </div>
              </button>
              <div className="flex items-center gap-3">
                <Switch
                  checked={Boolean(server.enabled)}
                  onCheckedChange={(value) => updateMcpServerItem(index, "enabled", value)}
                />
                <Button size="sm" variant="outline" onClick={() => removeMcpServerItem(index)}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  Remove
                </Button>
              </div>
            </div>
            {isOpen ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Name</label>
                <Input
                  value={server.name ?? ""}
                  onChange={(event) => updateMcpServerItem(index, "name", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Transport</label>
                <Select
                  value={server.transport || "stdio"}
                  onValueChange={(value) => updateMcpServerItem(index, "transport", value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select transport" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="stdio">stdio</SelectItem>
                    <SelectItem value="http">http</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Description</label>
                <Textarea
                  rows={3}
                  value={server.description ?? ""}
                  onChange={(event) => updateMcpServerItem(index, "description", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Command</label>
                <Input
                  value={server.command ?? ""}
                  onChange={(event) => updateMcpServerItem(index, "command", event.target.value)}
                  disabled={(server.transport || "stdio") !== "stdio"}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Args</label>
                <Input
                  value={(server.args ?? []).join(", ")}
                  onChange={(event) =>
                    updateMcpServerItem(
                      index,
                      "args",
                      event.target.value
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean)
                    )
                  }
                  disabled={(server.transport || "stdio") !== "stdio"}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">URL</label>
                <Input
                  value={server.url ?? ""}
                  onChange={(event) => updateMcpServerItem(index, "url", event.target.value)}
                  disabled={(server.transport || "stdio") !== "http"}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Working Directory</label>
                <Input
                  value={server.cwd ?? ""}
                  onChange={(event) => updateMcpServerItem(index, "cwd", event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Startup Timeout</label>
                <Input
                  type="number"
                  step="1"
                  value={String(server.startup_timeout_seconds ?? 15)}
                  onChange={(event) => updateMcpServerItem(index, "startup_timeout_seconds", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Request Timeout</label>
                <Input
                  type="number"
                  step="1"
                  value={String(server.request_timeout_seconds ?? 120)}
                  onChange={(event) => updateMcpServerItem(index, "request_timeout_seconds", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Headers</label>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateMcpServerItem(index, "headers", {
                        ...(server.headers ?? {}),
                        [uniqueStructuredKey(Object.keys(server.headers ?? {}), "HEADER_NAME")]: "",
                      })
                    }
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Add header
                  </Button>
                </div>
                <div className="space-y-3 rounded-2xl border border-border/70 bg-background/70 p-3">
                  {headerRows.length ? (
                    headerRows.map((row, rowIndex) => (
                      <div key={`mcp-header-${index}-${rowIndex}`} className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center">
                        <Input
                          value={row.keyPath}
                          placeholder="Authorization"
                          onChange={(event) => {
                            const nextRows = headerRows.map((entry, currentIndex) => (
                              currentIndex === rowIndex ? { ...entry, keyPath: event.target.value } : entry
                            ));
                            updateStructuredObjectRows(
                              server.headers,
                              nextRows,
                              (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                              "MCP headers contain invalid values.",
                            );
                          }}
                        />
                        <Input
                          value={row.value}
                          placeholder="Bearer ..."
                          onChange={(event) => {
                            const nextRows = headerRows.map((entry, currentIndex) => (
                              currentIndex === rowIndex ? { ...entry, value: event.target.value } : entry
                            ));
                            updateStructuredObjectRows(
                              server.headers,
                              nextRows,
                              (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                              "MCP headers contain invalid values.",
                            );
                          }}
                        />
                        <Button
                          size="icon"
                          variant="outline"
                          onClick={() =>
                            updateStructuredObjectRows(
                              server.headers,
                              headerRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                              (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                              "MCP headers contain invalid values.",
                            )
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-mutedForeground">
                      No request headers configured.
                    </div>
                  )}
                </div>
              </div>
              <div className="space-y-2 md:col-span-2">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Environment</label>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateMcpServerItem(index, "env", {
                        ...(server.env ?? {}),
                        [uniqueStructuredKey(Object.keys(server.env ?? {}), "ENV_VAR")]: "",
                      })
                    }
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Add env var
                  </Button>
                </div>
                <div className="space-y-3 rounded-2xl border border-border/70 bg-background/70 p-3">
                  {envRows.length ? (
                    envRows.map((row, rowIndex) => (
                      <div key={`mcp-env-${index}-${rowIndex}`} className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center">
                        <Input
                          value={row.keyPath}
                          placeholder="API_TOKEN"
                          onChange={(event) => {
                            const nextRows = envRows.map((entry, currentIndex) => (
                              currentIndex === rowIndex ? { ...entry, keyPath: event.target.value } : entry
                            ));
                            updateStructuredObjectRows(
                              server.env,
                              nextRows,
                              (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                              "MCP environment contains invalid values.",
                            );
                          }}
                        />
                        <Input
                          value={row.value}
                          onChange={(event) => {
                            const nextRows = envRows.map((entry, currentIndex) => (
                              currentIndex === rowIndex ? { ...entry, value: event.target.value } : entry
                            ));
                            updateStructuredObjectRows(
                              server.env,
                              nextRows,
                              (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                              "MCP environment contains invalid values.",
                            );
                          }}
                        />
                        <Button
                          size="icon"
                          variant="outline"
                          onClick={() =>
                            updateStructuredObjectRows(
                              server.env,
                              envRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                              (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                              "MCP environment contains invalid values.",
                            )
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-border bg-muted/30 px-3 py-4 text-sm text-mutedForeground">
                      No environment overrides configured.
                    </div>
                  )}
                </div>
              </div>
            </div>
            ) : null}
          </div>
        )})
      ) : (
        <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
          No MCP servers configured.
        </div>
      ),
    })
  );

  return (
    <div className="app-shell">
      <Sidebar active={active} onSelect={setActive} />
      <div className="flex flex-col gap-8 px-10 py-10 pl-[300px]">
        <div className="mx-auto flex w-full max-w-[1520px] flex-col gap-8">
          <Topbar isDark={isDark} onToggleTheme={setIsDark} />
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="data-chip text-[10px] text-mutedForeground">{activeLabel}</div>
            </div>
            <div className="flex items-center gap-3">
              <Button variant="outline" onClick={apiReady ? handleRefreshActive : openApiKeyDialog}>
                <RefreshCcw className="mr-2 h-4 w-4" />
                {apiReady ? "Refresh data" : "Set API key"}
              </Button>
            </div>
          </div>

          {!apiReady ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-col gap-4 p-6 md:flex-row md:items-center md:justify-between">
                <div className="space-y-1">
                  <p className="text-sm font-semibold">Admin API key required</p>
                  <p className="text-sm text-mutedForeground">
                    Enter the Skitter admin API key to unlock the dashboard. It is stored only in this browser.
                  </p>
                </div>
                <Button onClick={openApiKeyDialog}>Enter API key</Button>
              </CardContent>
            </Card>
          ) : null}

        {active === "overview" && (
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
                    <Select
                      value={overviewRange}
                      onValueChange={(value) => setOverviewRange(value as OverviewRange)}
                    >
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
                    <div className="flex h-52 items-center justify-center rounded-2xl border border-dashed border-border bg-muted/40 text-sm text-mutedForeground">
                      Loading cost data...
                    </div>
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

            <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,0.8fr)]">
              <Card className="min-w-0">
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
                            <TableCell>{formatNumber(session.total_tokens ?? 0)}</TableCell>
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

              <Card className="min-w-0">
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
                    <Select value={sessionsRange} onValueChange={(value) => setSessionsRange(value as TableRange)}>
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
                      <TableRow>
                        <TableCell colSpan={8} className="text-center text-sm text-mutedForeground">
                          Loading sessions...
                        </TableCell>
                      </TableRow>
                    ) : sessionsError ? (
                      <TableRow>
                        <TableCell colSpan={8} className="text-center text-sm text-mutedForeground">
                          {sessionsError}
                        </TableCell>
                      </TableRow>
                    ) : visibleSessions.length ? (
                      pagedSessions.map((session) => (
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
                          <TableCell className="text-mutedForeground">
                            {formatNumber(session.last_input_tokens ?? 0)}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatNumber(session.total_tokens ?? 0)}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatCurrency(session.total_cost ?? 0)}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatRelativeTime(session.last_active_at)}
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={8} className="text-center text-sm text-mutedForeground">
                          {sessionsData.length
                            ? "No sessions found for the selected timeframe."
                            : "No sessions found."}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
                {!sessionsLoading && !sessionsError && visibleSessions.length ? (
                  <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-4 text-xs text-mutedForeground">
                    <span>
                      Showing {(Math.min(sessionsPage, sessionsPageCount) - 1) * SESSIONS_PAGE_SIZE + 1}
                      –{Math.min(Math.min(sessionsPage, sessionsPageCount) * SESSIONS_PAGE_SIZE, visibleSessions.length)}
                      {" "}of {visibleSessions.length}
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={sessionsPage <= 1}
                        onClick={() => setSessionsPage((page) => Math.max(1, page - 1))}
                      >
                        Previous
                      </Button>
                      <span>
                        Page {Math.min(sessionsPage, sessionsPageCount)} of {sessionsPageCount}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={sessionsPage >= sessionsPageCount}
                        onClick={() => setSessionsPage((page) => Math.min(sessionsPageCount, page + 1))}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                ) : null}
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
                <div className="flex flex-wrap items-center gap-3">
                  <Select value={toolRunToolFilter} onValueChange={setToolRunToolFilter}>
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
                  <Select value={toolRunUserFilter} onValueChange={setToolRunUserFilter}>
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
                  <Select value={toolRunExecutorFilter} onValueChange={setToolRunExecutorFilter}>
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
                  <Select value={toolRunsRange} onValueChange={(value) => setToolRunsRange(value as TableRange)}>
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
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setToolRunToolFilter("all");
                      setToolRunUserFilter("all");
                      setToolRunExecutorFilter("all");
                      setToolRunsRange("today");
                    }}
                  >
                    Clear filters
                  </Button>
                  <div className="ml-auto flex items-center gap-2 rounded-xl border border-border bg-muted/40 px-3 py-2">
                    <span className="text-xs text-mutedForeground">Show reasoning</span>
                    <Switch checked={showToolRunReasoning} onCheckedChange={setShowToolRunReasoning} />
                  </div>
                </div>
                {toolRunsLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading tool runs...
                  </div>
                ) : toolRunsError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {toolRunsError}
                  </div>
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
                      {showToolRunReasoning && toolRunReasoning(tool).length ? (
                        <div className="mt-4">
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Reasoning
                          </p>
                          <pre className="mt-2 rounded-2xl border border-border bg-muted/40 p-3 text-xs text-mutedForeground whitespace-pre-wrap">
                            {toolRunReasoning(tool).join("\n\n")}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {toolRunsData.length
                      ? "No tool runs match the selected filters and timeframe."
                      : "No tool runs found."}
                  </div>
                )}
                {!toolRunsLoading && !toolRunsError && visibleToolRuns.length ? (
                  <div className="flex items-center justify-between gap-3 border-t border-border pt-4 text-xs text-mutedForeground">
                    <span>
                      Showing {(Math.min(toolRunsPage, toolRunsPageCount) - 1) * TOOL_RUNS_PAGE_SIZE + 1}
                      –{Math.min(Math.min(toolRunsPage, toolRunsPageCount) * TOOL_RUNS_PAGE_SIZE, visibleToolRuns.length)}
                      {" "}of {visibleToolRuns.length}
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={toolRunsPage <= 1}
                        onClick={() => setToolRunsPage((page) => Math.max(1, page - 1))}
                      >
                        Previous
                      </Button>
                      <span>
                        Page {Math.min(toolRunsPage, toolRunsPageCount)} of {toolRunsPageCount}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={toolRunsPage >= toolRunsPageCount}
                        onClick={() => setToolRunsPage((page) => Math.min(toolRunsPageCount, page + 1))}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "agent-jobs" && (
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
                  <CardTitle>
                    {formatNumber((agentJobStatusCounts.failed ?? 0) + (agentJobStatusCounts.timeout ?? 0))}
                  </CardTitle>
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
                  <Select value={agentJobStatusFilter} onValueChange={setAgentJobStatusFilter}>
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
                  <Select value={agentJobUserFilter} onValueChange={setAgentJobUserFilter}>
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
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-sm text-mutedForeground">
                          Loading background jobs...
                        </TableCell>
                      </TableRow>
                    ) : agentJobsError ? (
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-sm text-mutedForeground">
                          {agentJobsError}
                        </TableCell>
                      </TableRow>
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
                            <p
                              className="truncate"
                              title={`${job.target_scope_type}:${job.target_scope_id}`}
                            >
                              {job.target_scope_type}:{job.target_scope_id}
                            </p>
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatRelativeTime(job.created_at)}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatDuration(computeAgentJobDurationMs(job))}
                          </TableCell>
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
                      <TableRow>
                        <TableCell colSpan={10} className="text-center text-sm text-mutedForeground">
                          {agentJobsData.length
                            ? "No background jobs match the selected filters."
                            : "No background jobs found."}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
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
                        <TableCell colSpan={7} className="text-center text-sm text-mutedForeground">
                          Loading jobs...
                        </TableCell>
                      </TableRow>
                    ) : jobsError ? (
                      <TableRow>
                        <TableCell colSpan={7} className="text-center text-sm text-mutedForeground">
                          {jobsError}
                        </TableCell>
                      </TableRow>
                    ) : jobsData.length ? (
                      jobsData.map((job) => (
                        <TableRow key={job.id}>
                          <TableCell className="font-semibold">{job.name}</TableCell>
                          <TableCell>{renderUser(job.user_id)}</TableCell>
                          <TableCell className="font-mono text-xs">
                            <div>{job.schedule_type === "date" ? "DATE" : "CRON"} · {job.schedule_expr}</div>
                            <div className="mt-1 text-[11px] text-mutedForeground">
                              Model: {job.model === SCHEDULED_JOB_MODEL_MAIN ? "Main model chain" : job.model}
                            </div>
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
                        <TableCell colSpan={7} className="text-center text-sm text-mutedForeground">
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
                  <div className="grid gap-2">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Model
                    </label>
                    <Select
                      value={jobForm.model}
                      onValueChange={(value) => setJobForm((prev) => ({ ...prev, model: value }))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select model" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={SCHEDULED_JOB_MODEL_MAIN}>Main model chain (dynamic)</SelectItem>
                        {availableModelSelectors.map((selector) => (
                          <SelectItem key={`scheduled-job-model-${selector}`} value={selector}>
                            {selector}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-mutedForeground">
                      Main model chain is resolved when the job runs, so future config changes apply automatically.
                    </p>
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
                <div className="grid gap-2 md:max-w-sm">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    User
                  </label>
                  <Select
                    value={memoryUserId || usersData[0]?.id || "none"}
                    onValueChange={(value) => {
                      if (value === "none") {
                        setMemoryUserId("");
                        setMemoryData([]);
                        setMemoryError("No user selected for memory.");
                        setSelectedMemory(null);
                        return;
                      }
                      setMemoryUserId(value);
                      setSelectedMemory(null);
                      refreshMemory(value);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select user" />
                    </SelectTrigger>
                    <SelectContent>
                      {usersData.length ? (
                        usersData.map((user) => (
                          <SelectItem key={user.id} value={user.id}>
                            {userLabelFor(user.id)}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="none">No users available</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>

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

        {active === "secrets" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Secrets"
                  subtitle="Per-user keys and tokens for skills. Values are write-only."
                  actionLabel={secretsLoading ? "Refreshing..." : "Refresh"}
                  onAction={secretsLoading ? undefined : () => refreshSecrets()}
                />
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      User
                    </label>
                    <Input
                      list="skitter-secret-users"
                      value={secretUserLabel}
                      onChange={(event) => {
                        const value = event.target.value;
                        setSecretUserLabel(value);
                        setSecretUserId(value ? resolveUserId(value, secretUserId) : "");
                      }}
                      placeholder="Select a user"
                    />
                    <datalist id="skitter-secret-users">
                      {usersData.map((user) => (
                        <option
                          key={user.id}
                          value={`@${user.display_name ?? user.username ?? user.transport_user_id}`}
                          label={user.transport_user_id}
                        />
                      ))}
                    </datalist>
                    <p className="text-xs text-mutedForeground">
                      {secretUserId
                        ? `Selected: ${userLabelFor(secretUserId)} (${secretUserId})`
                        : "Type to search by name or paste a user id."}
                    </p>
                  </div>
                  <div className="grid gap-2">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Secret name
                    </label>
                    <Input
                      value={secretName}
                      onChange={(event) => setSecretName(event.target.value)}
                      placeholder="EXAMPLE_API_KEY"
                    />
                    <p className="text-xs text-mutedForeground">
                      Use this name inside skills.
                    </p>
                  </div>
                </div>
                <div className="grid gap-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Secret value
                  </label>
                  <Input
                    type="password"
                    value={secretValue}
                    onChange={(event) => setSecretValue(event.target.value)}
                    placeholder="••••••••"
                  />
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-mutedForeground">
                      Values are stored encrypted and never shown again.
                    </p>
                    <Button onClick={handleSecretSave} disabled={secretSaving}>
                      {secretSaving ? "Saving..." : "Save secret"}
                    </Button>
                  </div>
                </div>
                {secretsError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {secretsError}
                  </div>
                ) : null}
                {secretsLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading secrets...
                  </div>
                ) : secretsData.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>Updated</TableHead>
                        <TableHead>Last used</TableHead>
                        <TableHead></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {secretsData.map((secret) => (
                        <TableRow key={secret.name}>
                          <TableCell className="font-semibold">{secret.name}</TableCell>
                          <TableCell className="text-mutedForeground">
                            {formatRelativeTime(secret.updated_at)}
                          </TableCell>
                          <TableCell className="text-mutedForeground">
                            {secret.last_used_at ? formatRelativeTime(secret.last_used_at) : "—"}
                          </TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => handleSecretDelete(secret.name)}
                            >
                              Delete
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    No secrets yet.
                  </div>
                )}
              </CardContent>
            </Card>
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
                                <>
                                  <Button
                                    size="sm"
                                    onClick={() => handleUserApproval(user.id, true)}
                                    disabled={userUpdating[user.id]}
                                  >
                                    {userUpdating[user.id] ? "Approving..." : "Approve"}
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="danger"
                                    onClick={() => handleUserDeny(user.id)}
                                    disabled={userUpdating[user.id]}
                                  >
                                    {userUpdating[user.id] ? "Denying..." : "Deny"}
                                  </Button>
                                </>
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
                <SectionHeader
                  title="Executors & workspaces"
                  subtitle="Per-user storage, live containers, and executor nodes."
                  actionLabel={sandboxLoading ? "Refreshing..." : "Refresh"}
                  onAction={sandboxLoading ? undefined : refreshSandbox}
                />
              </CardHeader>
              <CardContent className="space-y-6">
                {sandboxLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading sandbox status...
                  </div>
                ) : sandboxError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {sandboxError}
                  </div>
                ) : (
                  <>
                    <div className="flex justify-end">
                      <Button
                        onClick={() => {
                          setExecutorOnboardingError(null);
                          setExecutorOnboardingResult(null);
                          setExecutorOnboardingOpen(true);
                        }}
                      >
                        Add executor node
                      </Button>
                    </div>

                    <div className="grid gap-4 md:grid-cols-3">
                      <div className="rounded-2xl border border-border bg-card p-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">
                          Total workspace
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {sandboxStatus?.total_workspace_human ?? "0 B"}
                        </p>
                        <p className="text-xs text-mutedForeground">
                          {sandboxWorkspaces.length} workspaces
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border bg-card p-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">
                          Containers
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {sandboxContainers.length}
                        </p>
                        <p className="text-xs text-mutedForeground">
                          {sandboxContainers.filter((c) => c.status === "running").length} running
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border bg-card p-4">
                        <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">
                          Executors
                        </p>
                        <p className="mt-2 text-2xl font-semibold">{visibleExecutors.length}</p>
                        <p className="text-xs text-mutedForeground">{onlineExecutors} online</p>
                      </div>
                    </div>

                    <div className="grid gap-4 lg:grid-cols-2">
                      <div className="rounded-2xl border border-border bg-card p-4">
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-semibold">Workspaces</p>
                          <Badge variant="secondary">
                            {formatBytes(sandboxStatus?.total_workspace_bytes ?? 0)}
                          </Badge>
                        </div>
                        <div className="mt-3">
                          {sandboxWorkspaces.length ? (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>User</TableHead>
                                  <TableHead>Size</TableHead>
                                  <TableHead>Updated</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {sandboxWorkspaces.map((workspace) => (
                                  <TableRow key={workspace.user_id}>
                                    <TableCell className="font-semibold">
                                      {renderUser(workspace.user_id)}
                                    </TableCell>
                                    <TableCell>{workspace.size_human}</TableCell>
                                    <TableCell className="text-mutedForeground">
                                      {formatRelativeTime(workspace.updated_at)}
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          ) : (
                            <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-4 text-sm text-mutedForeground">
                              No workspaces found yet.
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-border bg-card p-4">
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-semibold">Sandbox containers</p>
                          <Badge variant="secondary">{sandboxContainers.length}</Badge>
                        </div>
                        <div className="mt-3">
                          {sandboxContainers.length ? (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>Container</TableHead>
                                  <TableHead>Status</TableHead>
                                  <TableHead>User</TableHead>
                                  <TableHead>Last active</TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {sandboxContainers.map((container) => (
                                  <TableRow key={container.id}>
                                    <TableCell className="text-xs">
                                      <div className="font-semibold">{container.name}</div>
                                      <div className="text-mutedForeground">{container.ports?.[0] ?? "—"}</div>
                                    </TableCell>
                                    <TableCell>
                                      <Badge
                                        variant={container.status === "running" ? "success" : "warning"}
                                      >
                                        {container.status}
                                      </Badge>
                                    </TableCell>
                                    <TableCell className="text-xs">
                                      {container.user_id ? renderUser(container.user_id) : "—"}
                                    </TableCell>
                                    <TableCell className="text-xs text-mutedForeground">
                                      {formatRelativeTime(container.last_activity_at)}
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          ) : (
                            <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-4 text-sm text-mutedForeground">
                              No sandbox containers found.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-border bg-card p-4">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-semibold">Executors</p>
                        <Badge variant="secondary">{visibleExecutors.length}</Badge>
                      </div>
                      <div className="mt-3">
                        {visibleExecutors.length ? (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>Name</TableHead>
                                <TableHead>Kind</TableHead>
                                <TableHead>User</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead>Host</TableHead>
                                <TableHead>Last seen</TableHead>
                                <TableHead className="text-right">Actions</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {visibleExecutors.map((executor) => (
                                <TableRow key={executor.id}>
                                  <TableCell className="text-xs">
                                    <div className="font-semibold">{executor.name}</div>
                                    <div className="text-mutedForeground">{executor.id}</div>
                                  </TableCell>
                                  <TableCell className="text-xs">{executor.kind}</TableCell>
                                  <TableCell className="text-xs">{renderUser(executor.owner_user_id)}</TableCell>
                                  <TableCell>
                                    <Badge
                                      variant={
                                        executor.disabled
                                          ? "warning"
                                          : executor.online
                                            ? "success"
                                            : "secondary"
                                      }
                                    >
                                      {executor.disabled ? "disabled" : executor.online ? "online" : executor.status}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="text-xs text-mutedForeground">
                                    {executor.hostname || executor.platform || "—"}
                                  </TableCell>
                                  <TableCell className="text-xs text-mutedForeground">
                                    {formatRelativeTime(executor.last_seen_at)}
                                  </TableCell>
                                  <TableCell className="text-right">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => openExecutorDetail(executor)}
                                    >
                                      Details
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        ) : (
                          <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-4 text-sm text-mutedForeground">
                            No non-docker executors found.
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {active === "settings" && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <SectionHeader
                  title="Admin API Access"
                  subtitle="The admin API key is stored client-side in this browser and used for API requests."
                  actionLabel={apiReady ? "Edit key" : "Set key"}
                  onAction={openApiKeyDialog}
                />
              </CardHeader>
              <CardContent className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge variant={apiReady ? "success" : "warning"}>
                      {apiReady ? "Configured" : "Required"}
                    </Badge>
                    <span className="font-mono text-sm">{maskedAdminApiKey}</span>
                  </div>
                  <p className="text-sm text-mutedForeground">API base: {API_BASE}</p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button variant="outline" onClick={openApiKeyDialog}>
                    {apiReady ? "Edit key" : "Set key"}
                  </Button>
                  {apiReady ? (
                    <Button variant="outline" onClick={clearAdminApiKey}>
                      Clear key
                    </Button>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <SectionHeader
                  title="Configuration"
                  subtitle="Review, filter, and edit the live YAML configuration."
                  actionLabel={configSaving ? "Saving..." : "Save changes"}
                  onAction={configSaving ? undefined : saveConfig}
                />
              </CardHeader>
              <CardContent className="space-y-6">
                {configLoading ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    Loading configuration...
                  </div>
                ) : configError ? (
                  <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                    {configError}
                  </div>
                ) : (
                  <div className="space-y-6">
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                      <div className="rounded-3xl border border-border/80 bg-card px-5 py-4 shadow-sm">
                        <div className="flex items-center gap-3">
                          <div className="rounded-2xl border border-border/70 bg-muted/30 p-2 text-mutedForeground">
                            <Database className="h-4 w-4" />
                          </div>
                          <div>
                            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Categories</p>
                            <p className="mt-1 text-2xl font-semibold">{configData?.categories.length ?? 0}</p>
                          </div>
                        </div>
                      </div>
                      <div className="rounded-3xl border border-border/80 bg-card px-5 py-4 shadow-sm">
                        <div className="flex items-center gap-3">
                          <div className="rounded-2xl border border-border/70 bg-muted/30 p-2 text-mutedForeground">
                            <Bot className="h-4 w-4" />
                          </div>
                          <div>
                            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Models</p>
                            <p className="mt-1 text-2xl font-semibold">{settingsModelCount}</p>
                          </div>
                        </div>
                      </div>
                      <div className="rounded-3xl border border-border/80 bg-card px-5 py-4 shadow-sm">
                        <div className="flex items-center gap-3">
                          <div className="rounded-2xl border border-border/70 bg-muted/30 p-2 text-mutedForeground">
                            <Globe className="h-4 w-4" />
                          </div>
                          <div>
                            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Providers</p>
                            <p className="mt-1 text-2xl font-semibold">{settingsProviderCount}</p>
                          </div>
                        </div>
                      </div>
                      <div className="rounded-3xl border border-border/80 bg-card px-5 py-4 shadow-sm">
                        <div className="flex items-center gap-3">
                          <div className="rounded-2xl border border-border/70 bg-muted/30 p-2 text-mutedForeground">
                            <Cable className="h-4 w-4" />
                          </div>
                          <div>
                            <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">MCP Servers</p>
                            <p className="mt-1 text-2xl font-semibold">{settingsMcpCount}</p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                      <div className="relative w-full lg:max-w-md">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mutedForeground" />
                        <Input
                          className="pl-9"
                          placeholder="Filter settings, descriptions, or keys"
                          value={settingsQuery}
                          onChange={(event) => setSettingsQuery(event.target.value)}
                        />
                      </div>
                      <p className="text-xs text-mutedForeground">
                        Secret fields stay masked unless you enter a new value.
                      </p>
                    </div>

                    <Tabs value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTabId)}>
                      <TabsList className="grid h-auto w-full grid-cols-2 gap-2 rounded-3xl bg-muted/40 p-2 lg:grid-cols-6">
                        {Object.entries(SETTINGS_TAB_META).map(([tabId, meta]) => {
                          const Icon = meta.icon;
                          return (
                            <TabsTrigger
                              key={tabId}
                              value={tabId}
                              className="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs"
                            >
                              <Icon className="h-4 w-4" />
                              {meta.label}
                            </TabsTrigger>
                          );
                        })}
                      </TabsList>

                      {(Object.keys(SETTINGS_TAB_META) as SettingsTabId[]).map((tabId) => (
                        <TabsContent key={tabId} value={tabId} className="mt-6 space-y-6">
                          {tabId === "models" ? (
                            <div className="grid gap-6 xl:grid-cols-2">
                              {renderProvidersEditor()}
                              {renderModelsEditor()}
                            </div>
                          ) : null}
                          {tabId === "integrations" ? (
                            <div className="grid gap-6">
                              {renderMcpServersEditor()}
                            </div>
                          ) : null}
                          <div className="grid gap-6">
                            {settingsCategoriesByTab[tabId].length ? (
                              settingsCategoriesByTab[tabId].map((category) => renderConfigCategoryCard(category))
                            ) : (
                              <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                                No settings match this tab{settingsQueryNormalized ? " and the current filter" : ""}.
                              </div>
                            )}
                          </div>
                        </TabsContent>
                      ))}
                    </Tabs>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {active !== "overview" && active !== "sessions" && active !== "tools" && active !== "agent-jobs" && active !== "jobs" && active !== "memory" && active !== "secrets" && active !== "users" && active !== "sandbox" && active !== "settings" && (
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

        <Dialog
          open={apiKeyDialogOpen}
          onOpenChange={(open) => {
            if (!open) {
              closeApiKeyDialog();
              return;
            }
            openApiKeyDialog();
          }}
        >
          <DialogContent
            onEscapeKeyDown={(event) => {
              if (!apiReady) {
                event.preventDefault();
              }
            }}
            onPointerDownOutside={(event) => {
              if (!apiReady) {
                event.preventDefault();
              }
            }}
          >
            <DialogHeader>
              <DialogTitle>{apiReady ? "Edit admin API key" : "Unlock admin UI"}</DialogTitle>
              <DialogDescription>
                Enter the Skitter admin API key for this browser. We validate it before saving it locally.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  API base
                </label>
                <Input value={API_BASE} readOnly />
              </div>
              <div className="grid gap-2">
                <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  Admin API key
                </label>
                <Input
                  type="password"
                  value={apiKeyDraft}
                  onChange={(event) => setApiKeyDraft(event.target.value)}
                  placeholder="skitter admin key"
                  autoFocus
                />
              </div>
              {apiKeyDialogError ? (
                <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-3 text-sm text-mutedForeground">
                  {apiKeyDialogError}
                </div>
              ) : (
                <p className="text-sm text-mutedForeground">
                  Stored in this browser using local storage. Avoid using this on shared or untrusted machines.
                </p>
              )}
              <div className="flex flex-wrap justify-end gap-3">
                {apiReady ? (
                  <Button variant="outline" onClick={closeApiKeyDialog}>
                    Cancel
                  </Button>
                ) : null}
                <Button onClick={saveAdminApiKey} disabled={apiKeySaving}>
                  {apiKeySaving ? "Checking..." : apiReady ? "Save key" : "Unlock admin UI"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog
          open={executorOnboardingOpen}
          onOpenChange={(open) => {
            setExecutorOnboardingOpen(open);
            if (!open) {
              setExecutorOnboardingError(null);
              setExecutorOnboardingResult(null);
            }
          }}
        >
          <DialogContent className="w-[94vw] max-w-4xl max-h-[88vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Add Executor Node</DialogTitle>
              <DialogDescription>
                Create a node executor, mint a token, and generate a launch command.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">User</p>
                <Select
                  value={executorForm.user_id || "none"}
                  onValueChange={(value) =>
                    setExecutorForm((current) => ({
                      ...current,
                      user_id: value === "none" ? "" : value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select user" />
                  </SelectTrigger>
                  <SelectContent>
                    {approvedUsers.length ? (
                      approvedUsers.map((user) => (
                        <SelectItem key={user.id} value={user.id}>
                          {userLabelFor(user.id)}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="none">No approved users</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Executor name</p>
                <Input
                  value={executorForm.name}
                  onChange={(event) =>
                    setExecutorForm((current) => ({ ...current, name: event.target.value }))
                  }
                  placeholder="macbook-main"
                />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Workspace root</p>
                <Input
                  value={executorForm.workspace_root}
                  onChange={(event) =>
                    setExecutorForm((current) => ({
                      ...current,
                      workspace_root: event.target.value,
                    }))
                  }
                  placeholder="workspace"
                />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">API URL</p>
                <Input
                  value={executorForm.api_url}
                  onChange={(event) =>
                    setExecutorForm((current) => ({ ...current, api_url: event.target.value }))
                  }
                  placeholder="http://localhost:8000"
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={runExecutorOnboarding} disabled={executorOnboardingLoading}>
                {executorOnboardingLoading ? "Generating..." : "Create Token"}
              </Button>
              {executorOnboardingError ? (
                <span className="text-sm text-danger">{executorOnboardingError}</span>
              ) : null}
            </div>

            {executorOnboardingResult ? (
              <div className="grid gap-3 lg:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Launch command</p>
                  <Textarea
                    className="mt-2 min-h-[120px] font-mono text-xs"
                    readOnly
                    value={executorOnboardingResult.command}
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        void navigator.clipboard
                          .writeText(executorOnboardingResult.command)
                          .catch(() => undefined);
                      }}
                    >
                      Copy command
                    </Button>
                    <span className="text-xs text-mutedForeground">
                      Executor `{executorOnboardingResult.executorName}` created.
                    </span>
                  </div>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Config YAML</p>
                  <Textarea
                    className="mt-2 min-h-[120px] font-mono text-xs"
                    readOnly
                    value={executorOnboardingResult.configYaml}
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        void navigator.clipboard
                          .writeText(executorOnboardingResult.configYaml)
                          .catch(() => undefined);
                      }}
                    >
                      Copy YAML
                    </Button>
                    <span className="text-xs text-mutedForeground">
                      Token is shown once. Save it now.
                    </span>
                  </div>
                </div>
              </div>
            ) : null}
          </DialogContent>
        </Dialog>

        <Dialog
          open={executorDetailOpen}
          onOpenChange={(open) => {
            setExecutorDetailOpen(open);
            if (!open) {
              setExecutorDetailError(null);
              setSelectedExecutor(null);
            }
          }}
        >
          <DialogContent className="w-[94vw] max-w-3xl max-h-[88vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Executor details</DialogTitle>
              <DialogDescription>
                Edit executor metadata or disable this executor.
              </DialogDescription>
            </DialogHeader>
            {selectedExecutor ? (
              <div className="space-y-5">
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Executor ID</p>
                    <Input value={selectedExecutor.id} readOnly />
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Owner</p>
                    <Input value={userLabelFor(selectedExecutor.owner_user_id)} readOnly />
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Name</p>
                    <Input
                      value={executorDetailForm.name}
                      onChange={(event) =>
                        setExecutorDetailForm((current) => ({ ...current, name: event.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Kind</p>
                    <Input value={selectedExecutor.kind} readOnly />
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Platform</p>
                    <Input value={selectedExecutor.platform ?? "—"} readOnly />
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Hostname</p>
                    <Input value={selectedExecutor.hostname ?? "—"} readOnly />
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button onClick={saveExecutorDetail} disabled={executorDetailSaving || executorDetailDeleting}>
                    {executorDetailSaving ? "Saving..." : "Save changes"}
                  </Button>
                </div>

                <div className="rounded-2xl border border-danger/40 bg-danger/5 p-4 space-y-3">
                  <p className="text-sm font-semibold text-danger">Executor Controls</p>
                  <p className="text-xs text-mutedForeground">
                    Disable revokes executor tokens. Delete removes the executor permanently.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {selectedExecutor.disabled ? (
                      <Button
                        variant="outline"
                        onClick={enableExecutor}
                        disabled={executorDetailDeleting || executorDetailSaving}
                      >
                        {executorDetailDeleting ? "Enabling..." : "Enable executor"}
                      </Button>
                    ) : (
                      <Button
                        variant="danger"
                        onClick={disableExecutor}
                        disabled={executorDetailDeleting || executorDetailSaving}
                      >
                        {executorDetailDeleting ? "Disabling..." : "Disable executor"}
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      onClick={deleteExecutor}
                      disabled={executorDetailDeleting || executorDetailSaving}
                    >
                      Delete executor
                    </Button>
                  </div>
                </div>

                {executorDetailError ? (
                  <div className="text-sm text-danger">{executorDetailError}</div>
                ) : null}
              </div>
            ) : null}
          </DialogContent>
        </Dialog>

        {selectedAgentJobId && (
          <Dialog
            open={Boolean(selectedAgentJobId)}
            onOpenChange={(open) => {
              if (!open) {
                setSelectedAgentJobId(null);
              }
            }}
          >
            <DialogContent className="w-[98vw] max-w-[1700px] max-h-[92vh] overflow-hidden p-0">
              <div className="border-b border-border p-6">
                <DialogHeader>
                  <DialogTitle>Background Job Detail</DialogTitle>
                  <DialogDescription>
                    Full execution details for job `{selectedAgentJobId}`.
                  </DialogDescription>
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
                        {formatNumber(selectedAgentJob.tool_calls_used ?? 0)} tools ·{" "}
                        {formatCurrency(selectedAgentJob.cost ?? 0)}
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
                        {selectedAgentJob.delivered_at
                          ? formatRelativeTime(selectedAgentJob.delivered_at)
                          : "Not delivered yet"}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border bg-card p-4 md:col-span-5">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Run ID</p>
                      <p className="mt-2 text-sm font-mono">{selectedAgentJob.run_id}</p>
                    </div>
                  </div>
                  {(selectedAgentJob.error || selectedAgentJob.delivery_error) && (
                    <div className="border-b border-border px-6 py-4 text-sm">
                      {selectedAgentJob.error ? (
                        <p className="text-foreground">Execution error: {selectedAgentJob.error}</p>
                      ) : null}
                      {selectedAgentJob.delivery_error ? (
                        <p className="text-foreground">Delivery error: {selectedAgentJob.delivery_error}</p>
                      ) : null}
                    </div>
                  )}
                  <div className="grid min-h-0 flex-1 gap-4 p-6 md:grid-cols-3">
                    <div className="min-h-0">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Payload
                      </p>
                      <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                        <pre className="text-xs text-foreground whitespace-pre-wrap">
                          {formatFullJson(selectedAgentJob.payload)}
                        </pre>
                      </ScrollArea>
                    </div>
                    <div className="min-h-0">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Limits
                      </p>
                      <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                        <pre className="text-xs text-foreground whitespace-pre-wrap">
                          {formatFullJson(selectedAgentJob.limits)}
                        </pre>
                      </ScrollArea>
                    </div>
                    <div className="min-h-0">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Result
                      </p>
                      <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                        <pre className="text-xs text-foreground whitespace-pre-wrap">
                          {formatFullJson(selectedAgentJob.result)}
                        </pre>
                      </ScrollArea>
                    </div>
                  </div>
                  <div className="grid gap-4 border-t border-border px-6 py-4 md:grid-cols-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Worker transcript
                      </p>
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
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                        Tool runs
                      </p>
                      <ScrollArea className="mt-2 h-[30vh] rounded-2xl border border-border bg-muted/40 p-3">
                        <div className="space-y-3">
                          {selectedAgentJob.tool_runs.length ? (
                            selectedAgentJob.tool_runs.map((tool) => (
                              <div key={tool.id} className="rounded-xl border border-border bg-card p-3">
                                <div className="flex items-center justify-between">
                                  <p className="text-sm font-semibold">{tool.tool}</p>
                                  <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>
                                    {tool.status}
                                  </Badge>
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
        )}

        {selectedToolRun && (
          <Dialog
            open={Boolean(selectedToolRun)}
            onOpenChange={(open) => {
              if (!open) {
                setSelectedToolRun(null);
              }
            }}
          >
            <DialogContent className="w-[98vw] max-w-[1700px] max-h-[92vh] overflow-hidden p-0">
              <div className="border-b border-border p-6">
                <DialogHeader>
                  <DialogTitle>Tool Run Details</DialogTitle>
                  <DialogDescription>
                    Full input and output payload for `{selectedToolRun.tool}`.
                  </DialogDescription>
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
                    <pre className="text-xs text-foreground whitespace-pre-wrap">
                      {formatFullJson(selectedToolRun.input)}
                    </pre>
                  </ScrollArea>
                </div>
                <div className="min-h-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
                  <ScrollArea className="mt-2 h-[52vh] rounded-2xl border border-border bg-muted/40 p-3">
                    <pre className="text-xs text-foreground whitespace-pre-wrap">
                      {formatFullJson(selectedToolRun.output)}
                    </pre>
                  </ScrollArea>
                </div>
                {showToolRunReasoning && toolRunReasoning(selectedToolRun).length ? (
                  <div className="min-h-0 md:col-span-2">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Reasoning
                    </p>
                    <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                      <pre className="text-xs text-foreground whitespace-pre-wrap">
                        {toolRunReasoning(selectedToolRun).join("\n\n")}
                      </pre>
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
        )}

        {selectedRunId && (
          <Dialog
            open={Boolean(selectedRunId)}
            onOpenChange={(open) => {
              if (!open) {
                setSelectedRunId(null);
              }
            }}
          >
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
                      <p className="mt-2 text-sm">
                        {formatNumber(runDetail.run.total_tokens ?? 0)} total
                      </p>
                      <p className="mt-1 text-xs text-mutedForeground">
                        In {formatNumber(runDetail.run.input_tokens ?? 0)} · Out{" "}
                        {formatNumber(runDetail.run.output_tokens ?? 0)}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border bg-card p-4">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Cost & Tools</p>
                      <p className="mt-2 text-sm">{formatCurrency(runDetail.run.cost ?? 0)}</p>
                      <p className="mt-1 text-xs text-mutedForeground">
                        {formatNumber(runDetail.run.tool_calls ?? 0)} tool call(s)
                      </p>
                    </div>
                  </div>
                  {(runDetail.run.error || runDetail.run.limit_reason) && (
                    <div className="mt-4 rounded-2xl border border-border bg-muted/30 p-4 text-sm">
                      {runDetail.run.error ? (
                        <p className="text-foreground">Error: {runDetail.run.error}</p>
                      ) : null}
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
                                <p className="mt-1 text-[11px] text-mutedForeground">
                                  {formatRelativeTime(event.created_at)}
                                </p>
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
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Reasoning
                          </p>
                          <ScrollArea className="mt-2 h-[20vh] rounded-2xl border border-border bg-muted/40 p-3">
                            <pre className="text-xs text-foreground whitespace-pre-wrap">
                              {runDetailReasoning.join("\n\n")}
                            </pre>
                          </ScrollArea>
                        </div>
                      ) : null}
                      <div className="grid gap-4 md:grid-cols-2">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Input</p>
                          <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                            <pre className="text-xs text-foreground whitespace-pre-wrap">
                              {runDetail.input_text || "—"}
                            </pre>
                          </ScrollArea>
                        </div>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Output</p>
                          <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                            <pre className="text-xs text-foreground whitespace-pre-wrap">
                              {runDetail.output_text || "—"}
                            </pre>
                          </ScrollArea>
                        </div>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                          Tool runs in this request
                        </p>
                        <ScrollArea className="mt-2 h-[24vh] rounded-2xl border border-border bg-muted/40 p-3">
                          <div className="space-y-3">
                            {runDetail.tool_runs.length ? (
                              runDetail.tool_runs.map((tool) => (
                                <div key={tool.id} className="rounded-xl border border-border bg-card p-3">
                                  <div className="flex items-center justify-between">
                                    <p className="text-sm font-semibold">{tool.tool}</p>
                                    <Badge variant={tool.status === "failed" ? "danger" : "secondary"}>
                                      {tool.status}
                                    </Badge>
                                  </div>
                                  <p className="mt-1 text-xs text-mutedForeground">
                                    {formatRelativeTime(tool.created_at)} · Approved by{" "}
                                    {tool.approved_by ? userLabelFor(tool.approved_by) : "auto"} · Executor{" "}
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
        )}

        {selectedSessionId && (
          <Dialog open={!!selectedSessionId} onOpenChange={(open) => !open && closeSessionDetail()}>
            <DialogContent className="max-w-7xl w-[98vw] max-h-[92vh] overflow-hidden">
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
                <div className="grid gap-6 overflow-hidden">
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="rounded-2xl border border-border bg-card p-4">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Session</p>
                      <p className="mt-2 text-sm font-semibold">{sessionDetail.id}</p>
                      <p className="mt-1 text-xs text-mutedForeground">
                        Status: {sessionDetail.status}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border bg-card p-4">
                      <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">User</p>
                      <div className="mt-2">{renderUser(sessionDetail.user_id)}</div>
                      <p className="mt-1 text-xs text-mutedForeground">
                        Last active {formatRelativeTime(sessionDetail.last_active_at)}
                      </p>
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
                                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                        Reasoning
                                      </p>
                                      <pre className="mt-2 text-xs text-mutedForeground whitespace-pre-wrap">
                                        {reasoning.join("\n\n")}
                                      </pre>
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
            Connected to Skitter API
          </div>
          <div>v0.1.0 · Admin preview</div>
        </footer>
        </div>
      </div>
    </div>
  );
}
