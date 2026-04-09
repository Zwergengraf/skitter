import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  Bot,
  Clock3,
  Globe,
  Search,
  Shield,
  Wrench,
  RefreshCcw,
} from "lucide-react";

import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  ConfigCategoryCard,
  McpServersEditor,
  ModelsEditor,
  ProvidersEditor,
} from "@/features/admin/components/SettingsEditors";
import { ApiKeyDialog } from "@/features/admin/dialogs/ApiKeyDialog";
import { ExecutorDetailDialog, ExecutorOnboardingDialog } from "@/features/admin/dialogs/ExecutorDialogs";
import {
  AgentJobDetailDialog,
  RunDetailDialog,
  SessionDetailDialog,
  ToolRunDetailDialog,
} from "@/features/admin/dialogs/RunDialogs";
import { ScheduledJobDialog } from "@/features/admin/dialogs/ScheduledJobDialog";
import { AgentJobsView } from "@/features/admin/views/AgentJobsView";
import { LiveEventsView } from "@/features/admin/views/LiveEventsView";
import { MemoryView } from "@/features/admin/views/MemoryView";
import { OverviewView } from "@/features/admin/views/OverviewView";
import { ProfilesView } from "@/features/admin/views/ProfilesView";
import { ScheduledJobsView } from "@/features/admin/views/ScheduledJobsView";
import { SandboxView } from "@/features/admin/views/SandboxView";
import { SecretsView } from "@/features/admin/views/SecretsView";
import { SessionsView } from "@/features/admin/views/SessionsView";
import { SettingsView } from "@/features/admin/views/SettingsView";
import { ToolRunsView } from "@/features/admin/views/ToolRunsView";
import { UsersView } from "@/features/admin/views/UsersView";
import type {
  ExecutorDeviceFeatureInfo,
  ExecutorPermissionInfo,
  OverviewRange,
  SettingsTabId,
  TableRange,
} from "@/features/admin/types";
import {
  EXECUTOR_DEVICE_FEATURE_LABELS,
  EXECUTOR_DEVICE_FEATURE_ORDER,
  asRecord,
  executorFeatureBadgeLabel,
  executorFeatureBadgeVariant,
  executorPermissionBadgeVariant,
  executorPermissionStatusLabel,
  getExecutorDeviceFeatures,
  getExecutorPermissions,
} from "@/features/admin/utils/executors";
import { buildConfigDraft, isPlainObject } from "@/features/admin/utils/structuredValues";
import { summaryStatusHint, summaryStatusLabel, summaryStatusVariant } from "@/features/admin/utils/sessionSummary";
import { inRange } from "@/features/admin/utils/tableRanges";
import { formatBytes, formatCurrency, formatJsonPreview, formatNumber, formatRelativeTime } from "@/lib/utils";
import {
  api,
  API_BASE,
  clearStoredApiKey,
  getStoredApiKey,
  setApiAuthFailureHandler,
  setStoredApiKey,
  streamAdminEvents,
} from "@/lib/api";
import { applyTheme, getStoredTheme } from "@/lib/theme";
import type { NavItemId } from "@/components/navigation";
import type {
  AdminLiveEvent,
  AgentProfile,
  AgentJobDetail,
  AgentJobListItem,
  ChannelListItem,
  ConfigMcpServerItem,
  ConfigModelItem,
  ConfigProviderItem,
  ExecutorItem,
  MemoryEntry,
  ModelItem,
  OverviewResponse,
  RunTraceDetail,
  SandboxStatus,
  ConfigResponse,
  ScheduledJobItem,
  SecretItem,
  SessionDetail,
  SessionListItem,
  TransportAccountItem,
  TransportBindingItem,
  ToolRunListItem,
  UserListItem,
} from "@/lib/types";

const views: Record<NavItemId, string> = {
  overview: "Overview",
  live: "Live",
  sessions: "Sessions",
  tools: "Tool Runs",
  "agent-jobs": "Background Jobs",
  jobs: "Scheduled Jobs",
  memory: "Memory",
  secrets: "Secrets",
  users: "Users",
  profiles: "Profiles",
  sandbox: "Executors",
  settings: "Settings",
};

const SESSIONS_PAGE_SIZE = 25;
const TOOL_RUNS_PAGE_SIZE = 15;
const SCHEDULED_JOB_MODEL_MAIN = "__main_chain__";
const SECRET_SCOPE_SHARED = "__shared__";

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
    categories: ["models", "reasoning", "embeddings"],
  },
  automation: {
    label: "Automation",
    icon: Clock3,
    categories: ["heartbeat", "jobs", "sub_agents", "scheduler", "limits"],
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

const ASSIGNED_SETTINGS_CATEGORIES = new Set(
  Object.values(SETTINGS_TAB_META).flatMap((meta) => meta.categories)
);

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
  const [liveEvents, setLiveEvents] = useState<AdminLiveEvent[]>([]);
  const [liveEventsLoading, setLiveEventsLoading] = useState<boolean>(false);
  const [liveEventsError, setLiveEventsError] = useState<string | null>(null);
  const [liveEventsPaused, setLiveEventsPaused] = useState<boolean>(false);
  const [liveEventsAutoScroll, setLiveEventsAutoScroll] = useState<boolean>(true);
  const [liveEventLevelFilter, setLiveEventLevelFilter] = useState<string>("all");
  const [liveEventKindFilter, setLiveEventKindFilter] = useState<string>("all");
  const [liveEventSearch, setLiveEventSearch] = useState<string>("");
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
  const [secretProfileId, setSecretProfileId] = useState<string>("");
  const [selectedMemory, setSelectedMemory] = useState<MemoryEntry | null>(null);
  const [memoryDetailContent, setMemoryDetailContent] = useState<string>("");
  const [memoryDetailLoading, setMemoryDetailLoading] = useState<boolean>(false);
  const [memoryUserId, setMemoryUserId] = useState<string>("");
  const [memoryProfileId, setMemoryProfileId] = useState<string>("");
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
  const [profilesByUserId, setProfilesByUserId] = useState<Record<string, AgentProfile[]>>({});
  const [profilesLoadingByUserId, setProfilesLoadingByUserId] = useState<Record<string, boolean>>({});
  const [profilesErrorByUserId, setProfilesErrorByUserId] = useState<Record<string, string | null>>({});
  const [profileManagerUserId, setProfileManagerUserId] = useState<string | null>(null);
  const [profileCreateName, setProfileCreateName] = useState<string>("");
  const [profileCreateSourceSlug, setProfileCreateSourceSlug] = useState<string>("blank");
  const [profileCreateMode, setProfileCreateMode] = useState<"blank" | "settings" | "all">("blank");
  const [profileCreateMakeDefault, setProfileCreateMakeDefault] = useState<boolean>(false);
  const [profileComposerOpen, setProfileComposerOpen] = useState<boolean>(false);
  const [profileListTab, setProfileListTab] = useState<"active" | "archived">("active");
  const [profileSaving, setProfileSaving] = useState<boolean>(false);
  const [profileActionLoading, setProfileActionLoading] = useState<Record<string, boolean>>({});
  const [profileRenameDrafts, setProfileRenameDrafts] = useState<Record<string, string>>({});
  const [profileModelDrafts, setProfileModelDrafts] = useState<Record<string, string>>({});
  const [expandedProfileSections, setExpandedProfileSections] = useState<Record<string, boolean>>({});
  const [modelsData, setModelsData] = useState<ModelItem[]>([]);
  const [modelsLoading, setModelsLoading] = useState<boolean>(false);
  const [transportAccountsByUserId, setTransportAccountsByUserId] = useState<Record<string, TransportAccountItem[]>>({});
  const [transportAccountsLoadingByUserId, setTransportAccountsLoadingByUserId] = useState<Record<string, boolean>>({});
  const [transportAccountsErrorByUserId, setTransportAccountsErrorByUserId] = useState<Record<string, string | null>>({});
  const [transportActionLoading, setTransportActionLoading] = useState<Record<string, boolean>>({});
  const [transportDisplayNameDrafts, setTransportDisplayNameDrafts] = useState<Record<string, string>>({});
  const [transportTokenDrafts, setTransportTokenDrafts] = useState<Record<string, string>>({});
  const [bindingsByAccountKey, setBindingsByAccountKey] = useState<Record<string, TransportBindingItem[]>>({});
  const [bindingsLoadingByAccountKey, setBindingsLoadingByAccountKey] = useState<Record<string, boolean>>({});
  const [bindingDrafts, setBindingDrafts] = useState<
    Record<string, { guild_id: string; surface_id: string; mode: string; agent_profile_id: string }>
  >({});
  const [sharedDefaultBindingsExpanded, setSharedDefaultBindingsExpanded] = useState<boolean>(false);
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
  const selectedExecutorDeviceFeatures = useMemo(
    () => (selectedExecutor ? getExecutorDeviceFeatures(selectedExecutor) : null),
    [selectedExecutor]
  );
  const selectedExecutorPermissions = useMemo(
    () => (selectedExecutor ? getExecutorPermissions(selectedExecutor) : null),
    [selectedExecutor]
  );
  const selectedExecutorTools = useMemo(() => {
    const capabilities = selectedExecutor ? asRecord(selectedExecutor.capabilities) : null;
    const rawTools = capabilities?.tools;
    if (!Array.isArray(rawTools)) {
      return [];
    }
    return rawTools.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  }, [selectedExecutor]);
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
    agent_profile_id: "",
    channel_id: "",
    channel_label: "",
    target_transport_account_key: "",
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
  const [isDark, setIsDark] = useState<boolean>(() => getStoredTheme() === "dark");
  const sessionMessagesEndRef = useRef<HTMLDivElement | null>(null);
  const liveEventsEndRef = useRef<HTMLDivElement | null>(null);

  const activeLabel = views[active];
  const apiReady = adminApiKey.trim().length > 0;
  const maskedAdminApiKey = apiReady ? `••••${adminApiKey.slice(-4)}` : "Not configured";
  const liveEventKinds = useMemo(
    () => Array.from(new Set(liveEvents.map((event) => event.kind))).sort(),
    [liveEvents]
  );
  const filteredLiveEvents = useMemo(() => {
    const query = liveEventSearch.trim().toLowerCase();
    return liveEvents.filter((event) => {
      if (liveEventLevelFilter !== "all" && event.level !== liveEventLevelFilter) {
        return false;
      }
      if (liveEventKindFilter !== "all" && event.kind !== liveEventKindFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = [
        event.kind,
        event.title,
        event.message,
        event.session_id,
        event.job_id,
        event.run_id,
        event.tool_run_id,
        event.executor_id,
        event.user_id,
        event.transport,
        JSON.stringify(event.data ?? {}),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [liveEvents, liveEventKindFilter, liveEventLevelFilter, liveEventSearch]);

  useEffect(() => {
    applyTheme(isDark);
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

  useEffect(() => {
    if (!apiReady || active !== "live") {
      return;
    }
    let isMounted = true;
    const abortController = new AbortController();
    setLiveEventsLoading(true);
    setLiveEventsError(null);

    const mergeEvent = (nextEvent: AdminLiveEvent) => {
      if (!isMounted) {
        return;
      }
      setLiveEvents((current) => {
        if (current.some((item) => item.id === nextEvent.id)) {
          return current;
        }
        const merged = [...current, nextEvent].sort(
          (left, right) => Date.parse(left.created_at) - Date.parse(right.created_at)
        );
        return merged.slice(-1000);
      });
    };

    const run = async () => {
      try {
        const items = await api.getAdminEvents(200);
        if (!isMounted) {
          return;
        }
        setLiveEvents(items);
        setLiveEventsLoading(false);

        while (isMounted && !abortController.signal.aborted) {
          try {
            setLiveEventsError(null);
            await streamAdminEvents(
              (event) => {
                if (!liveEventsPaused) {
                  mergeEvent(event);
                }
              },
              { signal: abortController.signal }
            );
          } catch (error) {
            const streamError = error as Error;
            if (!isMounted || streamError.name === "AbortError") {
              return;
            }
            setLiveEventsError(streamError.message || "Live event stream disconnected.");
          }
          if (!isMounted || abortController.signal.aborted) {
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1500));
        }
      } catch (error) {
        const loadError = error as Error;
        if (!isMounted || loadError.name === "AbortError") {
          return;
        }
        setLiveEventsError(loadError.message || "Unable to load live events.");
        setLiveEventsLoading(false);
      }
    };

    void run();

    return () => {
      isMounted = false;
      abortController.abort();
    };
  }, [active, apiReady, liveEventsPaused]);

  useEffect(() => {
    if (active !== "live" || !liveEventsAutoScroll) {
      return;
    }
    liveEventsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active, liveEvents, liveEventsAutoScroll]);

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
    () => {
      if (modelsData.length) {
        return modelsData.map((model) => model.name);
      }
      return configModels
        .filter((model) => model.provider?.trim() && model.name?.trim())
        .map((model) => `${model.provider.trim()}/${model.name.trim()}`);
    },
    [configModels, modelsData],
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
      const categories = filteredConfigCategories.filter((category) => {
        if (meta.categories.includes(category.id)) {
          return true;
        }
        return tabId === "advanced" && !ASSIGNED_SETTINGS_CATEGORIES.has(category.id);
      });
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

  const openRunDetail = (runId: string) => {
    setSelectedRunId(runId);
  };

  const openAgentJobDetail = (jobId: string) => {
    setSelectedAgentJobId(jobId);
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
      setMemoryProfileId("");
      return;
    }
    if (userId !== memoryUserId) {
      setMemoryUserId(userId);
      setMemoryProfileId("");
      setSelectedMemory(null);
      return;
    }
    const loadedProfiles = profilesByUserId[userId];
    if (!loadedProfiles) {
      if (profilesLoadingByUserId[userId]) {
        return;
      }
      const profileError = profilesErrorByUserId[userId];
      if (profileError) {
        setMemoryData([]);
        setMemoryLoading(false);
        setMemoryError(profileError);
        return;
      }
      void refreshProfilesForUser(userId);
      return;
    }
    const availableProfiles = loadedProfiles.filter((profile) => profile.status !== "archived");
    if (!availableProfiles.length) {
      setMemoryData([]);
      setMemoryLoading(false);
      setMemoryError("No active profiles found for this user.");
      setMemoryProfileId("");
      return;
    }
    const nextProfileId = availableProfiles.some((profile) => profile.id === memoryProfileId)
      ? memoryProfileId
      : preferredProfileIdForUser(userId, availableProfiles);
    if (nextProfileId !== memoryProfileId) {
      setMemoryProfileId(nextProfileId);
      return;
    }
    refreshMemory(userId, nextProfileId);
  }, [
    active,
    apiReady,
    memoryProfileId,
    memoryUserId,
    profilesByUserId,
    profilesErrorByUserId,
    profilesLoadingByUserId,
    usersData,
  ]);

  useEffect(() => {
    if (!apiReady || active !== "secrets") {
      return;
    }
    const userId =
      secretUserId && usersData.some((user) => user.id === secretUserId)
        ? secretUserId
        : usersData[0]?.id;
    if (!userId) {
      setSecretsData([]);
      setSecretsError("No users found yet.");
      setSecretsLoading(false);
      setSecretProfileId("");
      return;
    }
    if (userId !== secretUserId) {
      setSecretUserId(userId);
      setSecretUserLabel(userLabelFor(userId));
      setSecretProfileId("");
      return;
    }
    const loadedProfiles = profilesByUserId[userId];
    if (!loadedProfiles) {
      if (profilesLoadingByUserId[userId]) {
        return;
      }
      const profileError = profilesErrorByUserId[userId];
      if (profileError) {
        setSecretsData([]);
        setSecretsLoading(false);
        setSecretsError(profileError);
        return;
      }
      void refreshProfilesForUser(userId);
      return;
    }
    const availableProfiles = loadedProfiles.filter((profile) => profile.status !== "archived");
    const validProfileIds = new Set(availableProfiles.map((profile) => profile.id));
    const fallbackScopeId = preferredProfileIdForUser(userId, availableProfiles) || SECRET_SCOPE_SHARED;
    const nextProfileId =
      !secretProfileId
        ? fallbackScopeId
        : secretProfileId === SECRET_SCOPE_SHARED || validProfileIds.has(secretProfileId)
          ? secretProfileId
          : fallbackScopeId;
    if (nextProfileId !== secretProfileId) {
      setSecretProfileId(nextProfileId);
      return;
    }
    refreshSecrets(userId);
  }, [
    active,
    apiReady,
    profilesByUserId,
    profilesErrorByUserId,
    profilesLoadingByUserId,
    secretProfileId,
    secretUserId,
    usersData,
  ]);

  useEffect(() => {
    if (!apiReady || !selectedMemory?.source || !memoryProfileId) {
      setMemoryDetailContent("");
      return;
    }
    setMemoryDetailLoading(true);
    api
      .getMemoryFile(selectedMemory.source, memoryUserId, memoryProfileId)
      .then((data) => {
        setMemoryDetailContent(data.content);
      })
      .catch((error: Error) => {
        setMemoryError(error.message);
      })
      .finally(() => {
        setMemoryDetailLoading(false);
      });
  }, [selectedMemory, memoryProfileId, memoryUserId, apiReady]);

  const handleMemoryReindex = async () => {
    if (!memoryUserId) {
      setMemoryError("No user selected for reindex.");
      return;
    }
    if (!memoryProfileId) {
      setMemoryError("No profile selected for reindex.");
      return;
    }
    setMemoryReindexing(true);
    try {
      const stats = await api.reindexMemory(memoryUserId, memoryProfileId);
      await api.getMemory(memoryUserId, memoryProfileId).then((data) => setMemoryData(data));
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
        agent_profile_id: secretProfileId && secretProfileId !== SECRET_SCOPE_SHARED ? secretProfileId : undefined,
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

  const handleSecretDelete = async (name: string, agentProfileId?: string | null) => {
    if (!secretUserId) {
      setSecretsError("No user selected for secrets.");
      return;
    }
    try {
      await api.deleteSecret(secretUserId, name, agentProfileId ?? undefined);
      refreshSecrets(secretUserId);
    } catch (error) {
      setSecretsError((error as Error).message);
    }
  };

  const updateConfigValue = (key: string, value: unknown) => {
    setConfigDraft((prev) => ({ ...prev, [key]: value }));
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

  const refreshModels = async (force = false): Promise<ModelItem[]> => {
    if (!force && (modelsLoading || modelsData.length)) {
      return modelsData;
    }
    setModelsLoading(true);
    try {
      const models = await api.getModels();
      setModelsData(models);
      return models;
    } catch {
      return [];
    } finally {
      setModelsLoading(false);
    }
  };

  const refreshProfilesForUser = async (userId: string, force = false): Promise<AgentProfile[]> => {
    const cleanedUserId = userId.trim();
    if (!cleanedUserId) {
      return [];
    }
    if (!force && (profilesByUserId[cleanedUserId] || profilesLoadingByUserId[cleanedUserId])) {
      return profilesByUserId[cleanedUserId] ?? [];
    }
    setProfilesLoadingByUserId((current) => ({ ...current, [cleanedUserId]: true }));
    setProfilesErrorByUserId((current) => ({ ...current, [cleanedUserId]: null }));
    try {
      const profiles = await api.getProfiles(cleanedUserId, true);
      setProfilesByUserId((current) => ({ ...current, [cleanedUserId]: profiles }));
      setProfileRenameDrafts((current) => {
        const next = { ...current };
        for (const profile of profiles) {
          next[profile.id] = profile.name;
        }
        return next;
      });
      setProfileModelDrafts((current) => {
        const next = { ...current };
        for (const profile of profiles) {
          next[profile.id] = profile.default_model ?? "__default__";
        }
        return next;
      });
      return profiles;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [cleanedUserId]: message }));
      return [];
    } finally {
      setProfilesLoadingByUserId((current) => ({ ...current, [cleanedUserId]: false }));
    }
  };

  const refreshTransportAccountsForUser = async (
    userId: string,
    force = false
  ): Promise<TransportAccountItem[]> => {
    const cleanedUserId = userId.trim();
    if (!cleanedUserId) {
      return [];
    }
    if (
      !force &&
      (transportAccountsByUserId[cleanedUserId] || transportAccountsLoadingByUserId[cleanedUserId])
    ) {
      return transportAccountsByUserId[cleanedUserId] ?? [];
    }
    setTransportAccountsLoadingByUserId((current) => ({ ...current, [cleanedUserId]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [cleanedUserId]: null }));
    try {
      const accounts = await api.getTransportAccounts(cleanedUserId);
      setTransportAccountsByUserId((current) => ({ ...current, [cleanedUserId]: accounts }));
      setTransportDisplayNameDrafts((current) => {
        const next = { ...current };
        for (const account of accounts) {
          next[account.account_key] = account.display_name;
        }
        return next;
      });
      await Promise.all(
        accounts
          .filter((account) => account.transport === "discord")
          .map((account) => refreshBindingsForAccount(account.account_key, true))
      );
      return accounts;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [cleanedUserId]: message }));
      return [];
    } finally {
      setTransportAccountsLoadingByUserId((current) => ({ ...current, [cleanedUserId]: false }));
    }
  };

  const refreshBindingsForAccount = async (accountKey: string, force = false): Promise<TransportBindingItem[]> => {
    const cleanedAccountKey = accountKey.trim();
    if (!cleanedAccountKey) {
      return [];
    }
    if (!force && (bindingsByAccountKey[cleanedAccountKey] || bindingsLoadingByAccountKey[cleanedAccountKey])) {
      return bindingsByAccountKey[cleanedAccountKey] ?? [];
    }
    setBindingsLoadingByAccountKey((current) => ({ ...current, [cleanedAccountKey]: true }));
    try {
      const bindings = await api.getTransportBindings(cleanedAccountKey);
      setBindingsByAccountKey((current) => ({ ...current, [cleanedAccountKey]: bindings }));
      return bindings;
    } catch {
      return [];
    } finally {
      setBindingsLoadingByAccountKey((current) => ({ ...current, [cleanedAccountKey]: false }));
    }
  };

  const resetProfileCreateState = () => {
    setProfileCreateName("");
    setProfileCreateSourceSlug("blank");
    setProfileCreateMode("blank");
    setProfileCreateMakeDefault(false);
    setProfileComposerOpen(false);
  };

  const openProfileManager = (userId: string) => {
    setActive("profiles");
    setProfileManagerUserId(userId);
    resetProfileCreateState();
    setProfileListTab("active");
    setExpandedProfileSections({});
    setSharedDefaultBindingsExpanded(false);
    void refreshProfilesForUser(userId, true);
    void refreshTransportAccountsForUser(userId, true);
  };

  const handleProfileCreate = async () => {
    const userId = profileManagerUserId?.trim() ?? "";
    if (!userId) {
      return;
    }
    const name = profileCreateName.trim();
    if (!name) {
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: "Profile name is required." }));
      return;
    }
    setProfileSaving(true);
    setProfilesErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      const sourceSlug = profileCreateSourceSlug !== "blank" ? profileCreateSourceSlug : undefined;
      await api.createProfile({
        user_id: userId,
        name,
        source_profile_slug: sourceSlug,
        mode: sourceSlug ? profileCreateMode : "blank",
        make_default: profileCreateMakeDefault,
      });
      setProfileCreateName("");
      setProfileCreateSourceSlug("blank");
      setProfileCreateMode("blank");
      setProfileCreateMakeDefault(false);
      setProfileComposerOpen(false);
      await refreshProfilesForUser(userId, true);
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setProfileSaving(false);
    }
  };

  const handleTransportAccountSave = async (userId: string, profile: AgentProfile) => {
    const existing = (transportAccountsByUserId[userId] ?? []).find(
      (account) => !account.is_shared_default && account.agent_profile_id === profile.id && account.transport === "discord"
    );
    const draftName = (transportDisplayNameDrafts[existing?.account_key ?? profile.id] ?? "").trim();
    const draftToken = (transportTokenDrafts[profile.id] ?? "").trim();
    if (!existing && !draftToken) {
      setTransportAccountsErrorByUserId((current) => ({
        ...current,
        [userId]: "A bot token is required to create a dedicated Discord bot.",
      }));
      return;
    }
    const loadingKey = existing?.account_key ?? profile.id;
    setTransportActionLoading((current) => ({ ...current, [loadingKey]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      if (existing) {
        await api.updateTransportAccount(existing.account_key, {
          display_name: draftName || existing.display_name,
          credential_value: draftToken || undefined,
        });
      } else {
        await api.createTransportAccount({
          user_id: userId,
          agent_profile_id: profile.id,
          transport: "discord",
          display_name: draftName || `${profile.name} Discord`,
          credential_value: draftToken,
          enabled: true,
        });
      }
      setTransportTokenDrafts((current) => ({ ...current, [profile.id]: "" }));
      await refreshTransportAccountsForUser(userId, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [loadingKey]: false }));
    }
  };

  const handleTransportAccountEnabled = async (
    userId: string,
    account: TransportAccountItem,
    enabled: boolean
  ) => {
    setTransportActionLoading((current) => ({ ...current, [account.account_key]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.updateTransportAccount(account.account_key, { enabled });
      await refreshTransportAccountsForUser(userId, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [account.account_key]: false }));
    }
  };

  const handleTransportAccountDelete = async (userId: string, account: TransportAccountItem) => {
    const confirmed = window.confirm(
      `Delete the dedicated Discord bot "${account.display_name}"?\nThis disables its bindings and removes the override token.`
    );
    if (!confirmed) {
      return;
    }
    setTransportActionLoading((current) => ({ ...current, [account.account_key]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.deleteTransportAccount(account.account_key);
      await refreshTransportAccountsForUser(userId, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [account.account_key]: false }));
    }
  };

  const handleBindingCreate = async (
    userId: string,
    account: TransportAccountItem,
    fallbackProfileId?: string
  ) => {
    const draft = bindingDrafts[account.account_key] ?? {
      guild_id: "",
      surface_id: "",
      mode: "mention_only",
      agent_profile_id: fallbackProfileId ?? "",
    };
    if (!draft.surface_id) {
      setTransportAccountsErrorByUserId((current) => ({
        ...current,
        [userId]: "Choose a Discord channel before creating a binding.",
      }));
      return;
    }
    setTransportActionLoading((current) => ({ ...current, [account.account_key]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.createTransportBinding({
        transport_account_key: account.account_key,
        user_id: userId,
        agent_profile_id: account.is_shared_default ? draft.agent_profile_id : fallbackProfileId,
        origin: "discord",
        surface_kind: "discord_channel",
        surface_id: draft.surface_id,
        mode: draft.mode,
        enabled: true,
      });
      setBindingDrafts((current) => ({
        ...current,
        [account.account_key]: {
          guild_id: draft.guild_id,
          surface_id: "",
          mode: "mention_only",
          agent_profile_id: fallbackProfileId ?? draft.agent_profile_id,
        },
      }));
      await refreshBindingsForAccount(account.account_key, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [account.account_key]: false }));
    }
  };

  const handleBindingUpdate = async (
    userId: string,
    binding: TransportBindingItem,
    payload: Partial<{ mode: string; enabled: boolean; agent_profile_id: string }>
  ) => {
    setTransportActionLoading((current) => ({ ...current, [binding.id]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.updateTransportBinding(binding.id, payload);
      await refreshBindingsForAccount(binding.transport_account_key, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [binding.id]: false }));
    }
  };

  const handleBindingDelete = async (userId: string, binding: TransportBindingItem) => {
    setTransportActionLoading((current) => ({ ...current, [binding.id]: true }));
    setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.deleteTransportBinding(binding.id);
      await refreshBindingsForAccount(binding.transport_account_key, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTransportAccountsErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setTransportActionLoading((current) => ({ ...current, [binding.id]: false }));
    }
  };

  const handleProfileSettingsSave = async (userId: string, profile: AgentProfile) => {
    const nextName = (profileRenameDrafts[profile.id] ?? profile.name).trim();
    const nextDefaultModelDraft = profileModelDrafts[profile.id] ?? (profile.default_model ?? "__default__");
    const nextDefaultModel = nextDefaultModelDraft === "__default__" ? null : nextDefaultModelDraft;
    if (!nextName) {
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: "Profile name is required." }));
      return;
    }
    const currentDefaultModel = profile.default_model ?? null;
    if (nextName === profile.name && nextDefaultModel === currentDefaultModel) {
      return;
    }
    setProfileActionLoading((current) => ({ ...current, [profile.id]: true }));
    setProfilesErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.updateProfile(profile.id, {
        user_id: userId,
        name: nextName,
        default_model: nextDefaultModel,
      });
      await refreshProfilesForUser(userId, true);
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setProfileActionLoading((current) => ({ ...current, [profile.id]: false }));
    }
  };

  const handleProfileSetDefault = async (userId: string, profile: AgentProfile) => {
    setProfileActionLoading((current) => ({ ...current, [profile.id]: true }));
    setProfilesErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.updateProfile(profile.id, { user_id: userId, make_default: true });
      await refreshProfilesForUser(userId, true);
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setProfileActionLoading((current) => ({ ...current, [profile.id]: false }));
    }
  };

  const handleProfileArchiveToggle = async (userId: string, profile: AgentProfile, archived: boolean) => {
    setProfileActionLoading((current) => ({ ...current, [profile.id]: true }));
    setProfilesErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.updateProfile(profile.id, { user_id: userId, archived });
      await refreshProfilesForUser(userId, true);
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setProfileActionLoading((current) => ({ ...current, [profile.id]: false }));
    }
  };

  const handleProfileDelete = async (userId: string, profile: AgentProfile) => {
    const confirmed = window.confirm(
      `Delete archived profile "${profile.name}" permanently?\nThis removes its sessions, memory, secrets, jobs, and workspace files.`
    );
    if (!confirmed) {
      return;
    }
    setProfileActionLoading((current) => ({ ...current, [profile.id]: true }));
    setProfilesErrorByUserId((current) => ({ ...current, [userId]: null }));
    try {
      await api.deleteProfile(profile.id);
      setProfileRenameDrafts((current) => {
        const next = { ...current };
        delete next[profile.id];
        return next;
      });
      await refreshProfilesForUser(userId, true);
      refreshUsers();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProfilesErrorByUserId((current) => ({ ...current, [userId]: message }));
    } finally {
      setProfileActionLoading((current) => ({ ...current, [profile.id]: false }));
    }
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
        `    - browser_action\n` +
        `  notify: true\n` +
        `  screenshot: false\n` +
        `  mouse: false\n` +
        `  keyboard: false\n`;

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

  const refreshMemory = (targetUserId?: string, targetProfileId?: string) => {
    const resolvedUserId = targetUserId || memoryUserId;
    const resolvedProfileId = targetProfileId || memoryProfileId;
    if (!resolvedUserId) {
      setMemoryError("No user selected for memory.");
      return;
    }
    if (!resolvedProfileId) {
      setMemoryError("No profile selected for memory.");
      return;
    }
    setMemoryLoading(true);
    setMemoryError(null);
    api
      .getMemory(resolvedUserId, resolvedProfileId)
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

  const refreshLiveEvents = () => {
    setLiveEventsLoading(true);
    setLiveEventsError(null);
    api
      .getAdminEvents(200)
      .then((data) => {
        setLiveEvents(data);
      })
      .catch((error: Error) => {
        setLiveEventsError(error.message);
      })
      .finally(() => {
        setLiveEventsLoading(false);
      });
  };

  const handleRefreshActive = () => {
    switch (active) {
      case "overview":
        refreshOverview();
        break;
      case "live":
        refreshLiveEvents();
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
      case "profiles":
        refreshUsers();
        if (profileManagerUserId) {
          void refreshProfilesForUser(profileManagerUserId, true);
          void refreshTransportAccountsForUser(profileManagerUserId, true);
        }
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
    if (!apiReady || active !== "profiles") {
      return;
    }
    refreshUsers();
    void refreshModels();
  }, [active, apiReady]);

  useEffect(() => {
    if (active !== "profiles" || profileManagerUserId || !usersData.length) {
      return;
    }
    openProfileManager(usersData[0].id);
  }, [active, profileManagerUserId, usersData]);

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

  const profilesForUser = (userId: string | null | undefined, includeArchived = true) => {
    if (!userId) {
      return [] as AgentProfile[];
    }
    const rows = profilesByUserId[userId] ?? [];
    return includeArchived ? rows : rows.filter((profile) => profile.status !== "archived");
  };

  const activeProfilesForUser = (userId: string | null | undefined) => profilesForUser(userId, false);

  const transportAccountsForUser = (userId: string | null | undefined) => {
    if (!userId) {
      return [] as TransportAccountItem[];
    }
    return transportAccountsByUserId[userId] ?? [];
  };

  const explicitDiscordAccountForProfile = (
    userId: string | null | undefined,
    profileId: string | null | undefined
  ) =>
    transportAccountsForUser(userId).find(
      (account) =>
        !account.is_shared_default &&
        account.transport === "discord" &&
        account.agent_profile_id === profileId
    );

  const sharedDefaultDiscordAccount = (userId: string | null | undefined) =>
    transportAccountsForUser(userId).find(
      (account) => account.is_shared_default && account.transport === "discord"
    );

  const channelOptionsForAccount = (accountKey?: string | null, guildId?: string | null) =>
    channelsData.filter((channel) => {
      const guildMatches =
        guildId === undefined || guildId === null
          ? true
          : guildId === ""
            ? false
            : channel.guild_id === guildId;
      return channel.transport_account_key === accountKey && guildMatches && channel.kind !== "dm";
    });

  const guildOptionsForAccount = (accountKey?: string | null) => {
    const seen = new Set<string>();
    return channelsData
      .filter(
        (channel) =>
          channel.transport_account_key === accountKey &&
          channel.kind !== "dm" &&
          !!channel.guild_id
      )
      .map((channel) => ({
        guild_id: channel.guild_id ?? "",
        guild_name: channel.guild_name?.trim() || channel.guild_id || "Unknown server",
      }))
      .filter((guild) => {
        if (!guild.guild_id || seen.has(guild.guild_id)) {
          return false;
        }
        seen.add(guild.guild_id);
        return true;
      })
      .sort((left, right) => left.guild_name.localeCompare(right.guild_name));
  };

  const preferredProfileIdForUser = (
    userId: string,
    candidateProfiles: AgentProfile[] = activeProfilesForUser(userId),
  ) => {
    const user = usersData.find((item) => item.id === userId);
    return (
      user?.default_profile_id ??
      candidateProfiles.find((profile) => profile.is_default)?.id ??
      candidateProfiles[0]?.id ??
      ""
    );
  };

  const profileLabelFor = (
    userId: string | null | undefined,
    profileId?: string | null,
    fallbackSlug?: string | null,
  ) => {
    if (profileId && userId) {
      const match = profilesForUser(userId).find((profile) => profile.id === profileId);
      if (match) {
        return match.slug;
      }
    }
    if (fallbackSlug) {
      return fallbackSlug;
    }
    if (userId) {
      const user = usersData.find(
        (item) => item.id === userId || item.transport_user_id === userId
      );
      if (user?.default_profile_slug) {
        return user.default_profile_slug;
      }
    }
    return "default";
  };

  const secretScopeLabel = (userId: string, profileId?: string | null) => {
    if (!profileId) {
      return "Shared";
    }
    return profileLabelFor(userId, profileId);
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

  const channelLabelFor = (channelId: string, accountKey?: string | null) => {
    const channel = channelsData.find(
      (item) => item.id === channelId && (!accountKey || item.transport_account_key === accountKey)
    );
    return channel?.label ?? channelId;
  };

  const resolveChannelId = (value: string, fallback: string, accountKey?: string | null) => {
    if (!value) {
      return fallback;
    }
    const match = channelsData.find(
      (channel) =>
        (!accountKey || channel.transport_account_key === accountKey) &&
        (channel.label === value || channel.id === value)
    );
    return match?.id ?? value;
  };

  const memoryProfiles = activeProfilesForUser(memoryUserId);
  const secretProfiles = activeProfilesForUser(secretUserId);
  const profileManagerUserIdValue = profileManagerUserId ?? "";
  const profileManagerProfiles = profilesForUser(profileManagerUserId);
  const profileManagerActiveProfiles = profileManagerProfiles.filter((profile) => profile.status !== "archived");
  const profileManagerArchivedProfiles = profileManagerProfiles.filter((profile) => profile.status === "archived");
  const profileManagerSharedDefaultDiscord = sharedDefaultDiscordAccount(profileManagerUserId);
  const profileManagerDedicatedDiscordAccounts = transportAccountsForUser(profileManagerUserId).filter(
    (account) => !account.is_shared_default && account.transport === "discord"
  );
  const profileManagerSharedBindings = profileManagerSharedDefaultDiscord
    ? bindingsByAccountKey[profileManagerSharedDefaultDiscord.account_key] ?? []
    : [];
  const profileManagerTotalBindings =
    profileManagerSharedBindings.length +
    profileManagerDedicatedDiscordAccounts.reduce(
      (count, account) => count + (bindingsByAccountKey[account.account_key] ?? []).length,
      0
    );
  const profileManagerSharedDefaultEligibleProfiles = profileManagerActiveProfiles.filter(
    (profile) => !explicitDiscordAccountForProfile(profileManagerUserIdValue, profile.id)
  );
  const profileManagerVisibleProfiles =
    profileListTab === "archived" ? profileManagerArchivedProfiles : profileManagerActiveProfiles;
  const profileManagerUserLabel = profileManagerUserId ? userLabelFor(profileManagerUserId) : "";
  const bindingModeLabel = (mode?: string | null) =>
    mode === "all_messages" ? "All messages" : "Mentions only";
  const bindingDraftFor = (accountKey: string, fallbackProfileId = "") =>
    bindingDrafts[accountKey] ?? {
      guild_id: "",
      surface_id: "",
      mode: "mention_only",
      agent_profile_id: fallbackProfileId,
    };
  const setBindingDraftFor = (
    accountKey: string,
    updates: Partial<{ guild_id: string; surface_id: string; mode: string; agent_profile_id: string }>,
    fallbackProfileId = ""
  ) => {
    setBindingDrafts((current) => ({
      ...current,
      [accountKey]: {
        ...(current[accountKey] ?? {
          guild_id: "",
          surface_id: "",
          mode: "mention_only",
          agent_profile_id: fallbackProfileId,
        }),
        ...updates,
      },
    }));
  };
  const isProfileSectionExpanded = (profile: AgentProfile) => expandedProfileSections[profile.id] ?? false;
  const toggleProfileSection = (profile: AgentProfile) => {
    setExpandedProfileSections((current) => ({
      ...current,
      [profile.id]: !(current[profile.id] ?? false),
    }));
  };
  const visibleSecrets = useMemo(() => {
    const filtered = secretsData.filter((secret) => {
      if (!secretProfileId) {
        return false;
      }
      if (secretProfileId === SECRET_SCOPE_SHARED) {
        return !secret.agent_profile_id;
      }
      return !secret.agent_profile_id || secret.agent_profile_id === secretProfileId;
    });
    return [...filtered].sort((a, b) => {
      if (a.name === b.name) {
        return secretScopeLabel(secretUserId, a.agent_profile_id).localeCompare(
          secretScopeLabel(secretUserId, b.agent_profile_id)
        );
      }
      return a.name.localeCompare(b.name);
    });
  }, [secretProfileId, secretUserId, secretsData]);

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
    if (jobForm.user_id) {
      void refreshProfilesForUser(jobForm.user_id);
      void refreshTransportAccountsForUser(jobForm.user_id);
    }
    setJobForm((prev) => {
      const nextUserLabel = prev.user_label || userLabelFor(prev.user_id);
      const nextChannelLabel =
        prev.channel_label || channelLabelFor(prev.channel_id, prev.target_transport_account_key);
      if (nextUserLabel === prev.user_label && nextChannelLabel === prev.channel_label) {
        return prev;
      }
      return {
        ...prev,
        user_label: nextUserLabel,
        channel_label: nextChannelLabel,
      };
    });
  }, [usersData, channelsData, jobDialogOpen, jobForm.user_id]);

  useEffect(() => {
    if (!jobDialogOpen || !jobForm.user_id) {
      return;
    }
    const profiles = activeProfilesForUser(jobForm.user_id);
    if (!profiles.length) {
      return;
    }
    const fallbackProfileId =
      profiles.find((profile) => profile.id === jobForm.agent_profile_id)?.id ??
      preferredProfileIdForUser(jobForm.user_id, profiles);
    const dedicated = explicitDiscordAccountForProfile(jobForm.user_id, fallbackProfileId);
    const shared = sharedDefaultDiscordAccount(jobForm.user_id);
    const nextAccountKey = dedicated?.account_key ?? shared?.account_key ?? "";
    if (
      fallbackProfileId === jobForm.agent_profile_id &&
      nextAccountKey === jobForm.target_transport_account_key
    ) {
      return;
    }
    setJobForm((prev) => ({
      ...prev,
      agent_profile_id: fallbackProfileId,
      target_transport_account_key: nextAccountKey,
    }));
  }, [
    jobDialogOpen,
    jobForm.user_id,
    jobForm.agent_profile_id,
    jobForm.target_transport_account_key,
    profilesByUserId,
    transportAccountsByUserId,
  ]);

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
      agent_profile_id: "",
      channel_id: "",
      channel_label: "",
      target_transport_account_key: "",
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
      agent_profile_id: job.agent_profile_id ?? preferredProfileIdForUser(job.user_id),
      channel_id: job.channel_id,
      channel_label: channelLabelFor(job.channel_id, job.target_transport_account_key),
      target_transport_account_key: job.target_transport_account_key ?? "",
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
      const resolvedChannelId = resolveChannelId(
        jobForm.channel_label,
        jobForm.channel_id,
        jobForm.target_transport_account_key
      );
      if (!resolvedUserId || !jobForm.agent_profile_id || !jobForm.target_transport_account_key || !resolvedChannelId) {
        throw new Error("User, profile, Discord bot, and destination channel are all required.");
      }
      if (editingJob) {
        await api.updateSchedule(editingJob.id, {
          agent_profile_id: jobForm.agent_profile_id,
          name: jobForm.name,
          prompt: jobForm.prompt,
          model: jobForm.model,
          target_origin: "discord",
          target_destination_id: resolvedChannelId,
          target_transport_account_key: jobForm.target_transport_account_key,
          schedule_type: jobForm.schedule_type,
          schedule_expr: scheduleExpr,
          enabled: jobForm.enabled,
          channel_id: resolvedChannelId,
        });
      } else {
        await api.createSchedule({
          user_id: resolvedUserId,
          agent_profile_id: jobForm.agent_profile_id,
          channel_id: resolvedChannelId,
          target_origin: "discord",
          target_destination_id: resolvedChannelId,
          target_transport_account_key: jobForm.target_transport_account_key,
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

  const renderConfigCategoryCard = (category: ConfigResponse["categories"][number]) => (
    <ConfigCategoryCard
      category={category}
      configDraft={configDraft}
      availableModelSelectors={availableModelSelectors}
      draggingModelChain={draggingModelChain}
      setDraggingModelChain={setDraggingModelChain}
      updateConfigValue={updateConfigValue}
    />
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

  const renderProvidersEditor = () => (
    <ProvidersEditor
      configProviders={configProviders}
      openProviderItems={openProviderItems}
      setOpenProviderItems={setOpenProviderItems}
      updateProviderItem={updateProviderItem}
      addProviderItem={addProviderItem}
      removeProviderItem={removeProviderItem}
    />
  );

  const renderModelsEditor = () => (
    <ModelsEditor
      configModels={configModels}
      configProviders={configProviders}
      openModelItems={openModelItems}
      setOpenModelItems={setOpenModelItems}
      updateModelItem={updateModelItem}
      addModelItem={addModelItem}
      removeModelItem={removeModelItem}
      setConfigError={setConfigError}
    />
  );

  const renderMcpServersEditor = () => (
    <McpServersEditor
      configMcpServers={configMcpServers}
      openMcpItems={openMcpItems}
      setOpenMcpItems={setOpenMcpItems}
      updateMcpServerItem={updateMcpServerItem}
      addMcpServerItem={addMcpServerItem}
      removeMcpServerItem={removeMcpServerItem}
      setConfigError={setConfigError}
    />
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
          <OverviewView
            overviewRange={overviewRange}
            onOverviewRangeChange={setOverviewRange}
            overviewLoading={overviewLoading}
            overviewError={overviewError}
            overviewCost={overviewCost}
            overviewHealth={overviewHealth}
            overviewSessions={overviewSessions}
            overviewToolRuns={overviewToolRuns}
            openSessionDetail={openSessionDetail}
            renderUser={renderUser}
          />
        )}

        {active === "live" && (
          <LiveEventsView
            liveEvents={liveEvents}
            filteredLiveEvents={filteredLiveEvents}
            liveEventKinds={liveEventKinds}
            liveEventsLoading={liveEventsLoading}
            liveEventsError={liveEventsError}
            liveEventsPaused={liveEventsPaused}
            onLiveEventsPausedChange={setLiveEventsPaused}
            liveEventsAutoScroll={liveEventsAutoScroll}
            onLiveEventsAutoScrollChange={setLiveEventsAutoScroll}
            liveEventSearch={liveEventSearch}
            onLiveEventSearchChange={setLiveEventSearch}
            liveEventLevelFilter={liveEventLevelFilter}
            onLiveEventLevelFilterChange={setLiveEventLevelFilter}
            liveEventKindFilter={liveEventKindFilter}
            onLiveEventKindFilterChange={setLiveEventKindFilter}
            clearLiveEvents={() => setLiveEvents([])}
            openSessionDetail={openSessionDetail}
            openRunDetail={openRunDetail}
            openAgentJobDetail={openAgentJobDetail}
            openExecutorDetail={openExecutorDetail}
            executorsData={executorsData}
            liveEventsEndRef={liveEventsEndRef}
          />
        )}

        {active === "sessions" && (
          <SessionsView
            filter={filter}
            onFilterChange={setFilter}
            sessionsRange={sessionsRange}
            onSessionsRangeChange={setSessionsRange}
            sessionsLoading={sessionsLoading}
            sessionsError={sessionsError}
            sessionsData={sessionsData}
            visibleSessions={visibleSessions}
            pagedSessions={pagedSessions}
            sessionsPage={sessionsPage}
            sessionsPageCount={sessionsPageCount}
            onPreviousPage={() => setSessionsPage((page) => Math.max(1, page - 1))}
            onNextPage={() => setSessionsPage((page) => Math.min(sessionsPageCount, page + 1))}
            openSessionDetail={openSessionDetail}
            renderUser={renderUser}
            profileLabelFor={profileLabelFor}
          />
        )}

        {active === "tools" && (
          <ToolRunsView
            toolRunToolFilter={toolRunToolFilter}
            onToolRunToolFilterChange={setToolRunToolFilter}
            toolRunUserFilter={toolRunUserFilter}
            onToolRunUserFilterChange={setToolRunUserFilter}
            toolRunExecutorFilter={toolRunExecutorFilter}
            onToolRunExecutorFilterChange={setToolRunExecutorFilter}
            toolRunsRange={toolRunsRange}
            onToolRunsRangeChange={setToolRunsRange}
            clearFilters={() => {
              setToolRunToolFilter("all");
              setToolRunUserFilter("all");
              setToolRunExecutorFilter("all");
              setToolRunsRange("today");
            }}
            showToolRunReasoning={showToolRunReasoning}
            onShowToolRunReasoningChange={setShowToolRunReasoning}
            toolRunsLoading={toolRunsLoading}
            toolRunsError={toolRunsError}
            toolRunsData={toolRunsData}
            visibleToolRuns={visibleToolRuns}
            pagedToolRuns={pagedToolRuns}
            toolRunsPage={toolRunsPage}
            toolRunsPageCount={toolRunsPageCount}
            onPreviousPage={() => setToolRunsPage((page) => Math.max(1, page - 1))}
            onNextPage={() => setToolRunsPage((page) => Math.min(toolRunsPageCount, page + 1))}
            toolRunTools={toolRunTools}
            toolRunUsers={toolRunUsers}
            toolRunExecutors={toolRunExecutors}
            renderUser={renderUser}
            userLabelFor={userLabelFor}
            openSessionDetail={openSessionDetail}
            setSelectedToolRun={setSelectedToolRun}
            setSelectedRunId={setSelectedRunId}
            toolRunReasoning={toolRunReasoning}
          />
        )}

        {active === "agent-jobs" && (
          <AgentJobsView
            agentJobsData={agentJobsData}
            agentJobsLoading={agentJobsLoading}
            agentJobsError={agentJobsError}
            filteredAgentJobs={filteredAgentJobs}
            agentJobStatuses={agentJobStatuses}
            agentJobUsers={agentJobUsers}
            agentJobStatusFilter={agentJobStatusFilter}
            onAgentJobStatusFilterChange={setAgentJobStatusFilter}
            agentJobUserFilter={agentJobUserFilter}
            onAgentJobUserFilterChange={setAgentJobUserFilter}
            agentJobStatusCounts={agentJobStatusCounts}
            renderUser={renderUser}
            userLabelFor={userLabelFor}
            setSelectedAgentJobId={setSelectedAgentJobId}
            refreshAgentJobs={refreshAgentJobs}
            formatDuration={formatDuration}
            computeAgentJobDurationMs={computeAgentJobDurationMs}
          />
        )}

        {active === "jobs" && (
          <div className="grid gap-6">
            <ScheduledJobsView
              jobsLoading={jobsLoading}
              jobsError={jobsError}
              jobsData={jobsData}
              openNewJob={openNewJob}
              openEditJob={openEditJob}
              deleteJob={async (job) => {
                if (!confirm(`Delete job "${job.name}"?`)) {
                  return;
                }
                try {
                  await api.deleteSchedule(job.id);
                  refreshJobs();
                } catch (error) {
                  setJobsError((error as Error).message);
                }
              }}
              renderUser={renderUser}
              channelLabelFor={channelLabelFor}
              mainModelLabelValue={SCHEDULED_JOB_MODEL_MAIN}
            />
            <ScheduledJobDialog
              open={jobDialogOpen}
              setOpen={setJobDialogOpen}
              editingJob={editingJob}
              directoryError={directoryError}
              jobForm={jobForm}
              setJobForm={setJobForm}
              availableModelSelectors={availableModelSelectors}
              mainModelLabelValue={SCHEDULED_JOB_MODEL_MAIN}
              buildDateSchedule={buildDateSchedule}
              usersData={usersData}
              resolveUserId={resolveUserId}
              userLabelFor={userLabelFor}
              activeProfilesForUser={activeProfilesForUser}
              explicitDiscordAccountForProfile={explicitDiscordAccountForProfile}
              sharedDefaultDiscordAccount={sharedDefaultDiscordAccount}
              channelOptionsForAccount={channelOptionsForAccount}
              resolveChannelId={resolveChannelId}
              channelLabelFor={channelLabelFor}
              saveJob={saveJob}
              jobSaving={jobSaving}
            />
          </div>
        )}

        {active === "memory" && (
          <MemoryView
            memoryReindexing={memoryReindexing}
            handleMemoryReindex={handleMemoryReindex}
            usersData={usersData}
            memoryUserId={memoryUserId}
            setMemoryUserId={setMemoryUserId}
            memoryProfileId={memoryProfileId}
            setMemoryProfileId={setMemoryProfileId}
            memoryProfiles={memoryProfiles}
            profilesLoadingByUserId={profilesLoadingByUserId}
            setMemoryData={setMemoryData}
            setMemoryError={setMemoryError}
            setSelectedMemory={setSelectedMemory}
            setMemoryDetailContent={setMemoryDetailContent}
            memoryLoading={memoryLoading}
            memoryError={memoryError}
            memoryData={memoryData}
            selectedMemory={selectedMemory}
            memoryDetailLoading={memoryDetailLoading}
            memoryDetailContent={memoryDetailContent}
            userLabelFor={userLabelFor}
          />
        )}

        {active === "secrets" && (
          <SecretsView
            secretsLoading={secretsLoading}
            refreshSecrets={() => refreshSecrets()}
            secretUserLabel={secretUserLabel}
            setSecretUserLabel={setSecretUserLabel}
            secretUserId={secretUserId}
            setSecretUserId={setSecretUserId}
            secretProfileId={secretProfileId}
            setSecretProfileId={setSecretProfileId}
            secretProfiles={secretProfiles}
            profilesLoadingByUserId={profilesLoadingByUserId}
            secretName={secretName}
            setSecretName={setSecretName}
            secretValue={secretValue}
            setSecretValue={setSecretValue}
            secretSaving={secretSaving}
            handleSecretSave={handleSecretSave}
            secretsError={secretsError}
            visibleSecrets={visibleSecrets}
            handleSecretDelete={handleSecretDelete}
            usersData={usersData}
            userLabelFor={userLabelFor}
            resolveUserId={resolveUserId}
            secretScopeLabel={secretScopeLabel}
            secretScopeSharedValue={SECRET_SCOPE_SHARED}
          />
        )}

        {active === "users" && (
          <UsersView
            usersLoading={usersLoading}
            usersError={usersError}
            usersData={usersData}
            userUpdating={userUpdating}
            refreshUsers={refreshUsers}
            renderUser={renderUser}
            openProfileManager={openProfileManager}
            handleUserApproval={handleUserApproval}
            handleUserDeny={handleUserDeny}
          />
        )}

        {active === "sandbox" && (
          <SandboxView
            sandboxLoading={sandboxLoading}
            sandboxError={sandboxError}
            sandboxStatus={sandboxStatus}
            sandboxContainers={sandboxContainers}
            sandboxWorkspaces={sandboxWorkspaces}
            visibleExecutors={visibleExecutors}
            onlineExecutors={onlineExecutors}
            refreshSandbox={refreshSandbox}
            openExecutorOnboarding={() => {
              setExecutorOnboardingError(null);
              setExecutorOnboardingResult(null);
              setExecutorOnboardingOpen(true);
            }}
            openExecutorDetail={openExecutorDetail}
            renderUser={renderUser}
          />
        )}

        {active === "settings" && (
          <SettingsView
            apiReady={apiReady}
            maskedAdminApiKey={maskedAdminApiKey}
            openApiKeyDialog={openApiKeyDialog}
            clearAdminApiKey={clearAdminApiKey}
            configSaving={configSaving}
            saveConfig={saveConfig}
            configLoading={configLoading}
            configError={configError}
            configData={configData}
            settingsModelCount={settingsModelCount}
            settingsProviderCount={settingsProviderCount}
            settingsMcpCount={settingsMcpCount}
            settingsQuery={settingsQuery}
            setSettingsQuery={setSettingsQuery}
            settingsTab={settingsTab}
            setSettingsTab={setSettingsTab}
            settingsTabMeta={SETTINGS_TAB_META}
            settingsCategoriesByTab={settingsCategoriesByTab}
            settingsQueryNormalized={settingsQueryNormalized}
            renderProvidersEditor={renderProvidersEditor}
            renderModelsEditor={renderModelsEditor}
            renderMcpServersEditor={renderMcpServersEditor}
            renderConfigCategoryCard={renderConfigCategoryCard}
            apiBase={API_BASE}
          />
        )}

        {active !== "overview" && active !== "live" && active !== "sessions" && active !== "tools" && active !== "agent-jobs" && active !== "jobs" && active !== "memory" && active !== "secrets" && active !== "users" && active !== "sandbox" && active !== "settings" && (
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

        <ApiKeyDialog
          open={apiKeyDialogOpen}
          apiReady={apiReady}
          apiBase={API_BASE}
          apiKeyDraft={apiKeyDraft}
          setApiKeyDraft={setApiKeyDraft}
          apiKeyDialogError={apiKeyDialogError}
          apiKeySaving={apiKeySaving}
          openApiKeyDialog={openApiKeyDialog}
          closeApiKeyDialog={closeApiKeyDialog}
          saveAdminApiKey={saveAdminApiKey}
        />

        <ExecutorOnboardingDialog
          open={executorOnboardingOpen}
          setOpen={setExecutorOnboardingOpen}
          executorForm={executorForm}
          setExecutorForm={setExecutorForm}
          approvedUsers={approvedUsers}
          userLabelFor={userLabelFor}
          executorOnboardingLoading={executorOnboardingLoading}
          executorOnboardingError={executorOnboardingError}
          executorOnboardingResult={executorOnboardingResult}
          setExecutorOnboardingError={setExecutorOnboardingError}
          setExecutorOnboardingResult={setExecutorOnboardingResult}
          runExecutorOnboarding={runExecutorOnboarding}
        />

        <ExecutorDetailDialog
          open={executorDetailOpen}
          setOpen={setExecutorDetailOpen}
          selectedExecutor={selectedExecutor}
          setSelectedExecutor={setSelectedExecutor}
          executorDetailForm={executorDetailForm}
          setExecutorDetailForm={setExecutorDetailForm}
          selectedExecutorDeviceFeatures={selectedExecutorDeviceFeatures}
          selectedExecutorPermissions={selectedExecutorPermissions}
          selectedExecutorTools={selectedExecutorTools}
          executorDetailSaving={executorDetailSaving}
          executorDetailDeleting={executorDetailDeleting}
          executorDetailError={executorDetailError}
          setExecutorDetailError={setExecutorDetailError}
          userLabelFor={userLabelFor}
          saveExecutorDetail={saveExecutorDetail}
          disableExecutor={disableExecutor}
          enableExecutor={enableExecutor}
          deleteExecutor={deleteExecutor}
        />

        <AgentJobDetailDialog
          selectedAgentJobId={selectedAgentJobId}
          setSelectedAgentJobId={setSelectedAgentJobId}
          selectedAgentJobLoading={selectedAgentJobLoading}
          selectedAgentJobError={selectedAgentJobError}
          selectedAgentJob={selectedAgentJob}
          formatDuration={formatDuration}
          computeAgentJobDurationMs={computeAgentJobDurationMs}
          formatFullJson={formatFullJson}
          extractAgentJobTranscript={extractAgentJobTranscript}
        />

        <ToolRunDetailDialog
          selectedToolRun={selectedToolRun}
          setSelectedToolRun={setSelectedToolRun}
          showToolRunReasoning={showToolRunReasoning}
          toolRunReasoning={toolRunReasoning}
          formatFullJson={formatFullJson}
          renderUser={renderUser}
          setSelectedRunId={setSelectedRunId}
        />

        <RunDetailDialog
          selectedRunId={selectedRunId}
          setSelectedRunId={setSelectedRunId}
          runDetailLoading={runDetailLoading}
          runDetailError={runDetailError}
          runDetail={runDetail}
          formatDuration={formatDuration}
          formatFullJson={formatFullJson}
          userLabelFor={userLabelFor}
          showRunReasoning={showRunReasoning}
          setShowRunReasoning={setShowRunReasoning}
          runDetailReasoning={runDetailReasoning}
        />

        <SessionDetailDialog
          selectedSessionId={selectedSessionId}
          closeSessionDetail={closeSessionDetail}
          sessionDetailLoading={sessionDetailLoading}
          sessionDetailError={sessionDetailError}
          sessionDetail={sessionDetail}
          profileLabelFor={profileLabelFor}
          renderUser={renderUser}
          showSessionReasoning={showSessionReasoning}
          setShowSessionReasoning={setShowSessionReasoning}
          sessionTimeline={sessionTimeline}
          messageReasoning={messageReasoning}
          userLabelFor={userLabelFor}
          sessionMessagesEndRef={sessionMessagesEndRef}
          summaryStatusVariant={summaryStatusVariant}
          summaryStatusLabel={summaryStatusLabel}
          summaryStatusHint={summaryStatusHint}
        />

        {active === "profiles" && (
          <ProfilesView
            usersData={usersData}
            usersLoading={usersLoading}
            refreshUsers={refreshUsers}
            goToUsers={() => setActive("users")}
            profileManagerUserIdValue={profileManagerUserIdValue}
            profileManagerUserLabel={profileManagerUserLabel}
            openProfileManager={openProfileManager}
            userLabelFor={userLabelFor}
            profileManagerActiveProfiles={profileManagerActiveProfiles}
            profileManagerDedicatedDiscordAccounts={profileManagerDedicatedDiscordAccounts}
            profileManagerTotalBindings={profileManagerTotalBindings}
            profileManagerArchivedProfiles={profileManagerArchivedProfiles}
            profileManagerSharedDefaultDiscord={profileManagerSharedDefaultDiscord ?? null}
            profileManagerSharedDefaultEligibleProfiles={profileManagerSharedDefaultEligibleProfiles}
            profileManagerSharedBindings={profileManagerSharedBindings}
            sharedDefaultBindingsExpanded={sharedDefaultBindingsExpanded}
            setSharedDefaultBindingsExpanded={setSharedDefaultBindingsExpanded}
            profileComposerOpen={profileComposerOpen}
            setProfileComposerOpen={(open) => setProfileComposerOpen(open)}
            resetProfileCreateState={resetProfileCreateState}
            refreshProfileWorkspace={() => {
              void refreshProfilesForUser(profileManagerUserIdValue, true);
              void refreshTransportAccountsForUser(profileManagerUserIdValue, true);
            }}
            profileListTab={profileListTab}
            setProfileListTab={(value) => setProfileListTab(value)}
            profileCreateName={profileCreateName}
            setProfileCreateName={(value) => setProfileCreateName(value)}
            profileCreateSourceSlug={profileCreateSourceSlug}
            setProfileCreateSourceSlug={(value) => setProfileCreateSourceSlug(value)}
            profileCreateMode={profileCreateMode}
            setProfileCreateMode={(value) => setProfileCreateMode(value)}
            profileCreateMakeDefault={profileCreateMakeDefault}
            setProfileCreateMakeDefault={(value) => setProfileCreateMakeDefault(value)}
            handleProfileCreate={handleProfileCreate}
            profileSaving={profileSaving}
            profileManagerProfiles={profileManagerProfiles}
            profilesError={profilesErrorByUserId[profileManagerUserIdValue] ?? null}
            transportAccountsError={transportAccountsErrorByUserId[profileManagerUserIdValue] ?? null}
            profilesLoading={profilesLoadingByUserId[profileManagerUserIdValue] ?? false}
            profileManagerVisibleProfiles={profileManagerVisibleProfiles}
            profileActionLoading={profileActionLoading}
            explicitDiscordAccountForProfile={(userId, profileId) =>
              explicitDiscordAccountForProfile(userId, profileId) ?? null
            }
            bindingsByAccountKey={bindingsByAccountKey}
            bindingDraftFor={bindingDraftFor}
            setBindingDraftFor={setBindingDraftFor}
            guildOptionsForAccount={guildOptionsForAccount}
            channelOptionsForAccount={channelOptionsForAccount}
            bindingsLoadingByAccountKey={bindingsLoadingByAccountKey}
            bindingModeLabel={bindingModeLabel}
            channelLabelFor={channelLabelFor}
            profileLabelFor={profileLabelFor}
            isProfileSectionExpanded={isProfileSectionExpanded}
            toggleProfileSection={toggleProfileSection}
            handleBindingCreate={handleBindingCreate}
            handleBindingUpdate={handleBindingUpdate}
            handleBindingDelete={handleBindingDelete}
            handleProfileArchiveToggle={handleProfileArchiveToggle}
            handleProfileDelete={handleProfileDelete}
            handleProfileSetDefault={handleProfileSetDefault}
            profileRenameDrafts={profileRenameDrafts}
            setProfileRenameDrafts={setProfileRenameDrafts}
            profileModelDrafts={profileModelDrafts}
            setProfileModelDrafts={setProfileModelDrafts}
            modelsLoading={modelsLoading}
            availableModelSelectors={availableModelSelectors}
            handleProfileSettingsSave={handleProfileSettingsSave}
            transportDisplayNameDrafts={transportDisplayNameDrafts}
            setTransportDisplayNameDrafts={setTransportDisplayNameDrafts}
            transportTokenDrafts={transportTokenDrafts}
            setTransportTokenDrafts={setTransportTokenDrafts}
            handleTransportAccountEnabled={handleTransportAccountEnabled}
            transportActionLoading={transportActionLoading}
            handleTransportAccountSave={handleTransportAccountSave}
            handleTransportAccountDelete={handleTransportAccountDelete}
          />
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
