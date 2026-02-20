import type {
  AgentJobDetail,
  AgentJobListItem,
  ChannelListItem,
  ConfigResponse,
  ExecutorItem,
  ExecutorTokenCreateOut,
  MemoryEntry,
  OverviewResponse,
  RunTraceDetail,
  RunTraceListItem,
  SandboxStatus,
  ScheduledJobItem,
  SecretItem,
  SessionDetail,
  SessionListItem,
  ToolRunListItem,
  UserListItem,
} from "@/lib/types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const API_KEY = import.meta.env.VITE_API_KEY ?? "";

type ApiResponse<T> = T;

async function request<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["X-API-Key"] = API_KEY;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getOverview: (range?: "today" | "24h" | "week" | "month" | "year"): Promise<OverviewResponse> => {
    const params = new URLSearchParams();
    if (range) {
      params.set("range", range);
    }
    const query = params.toString();
    return request(`/v1/overview${query ? `?${query}` : ""}`);
  },
  getSessions: (status?: string): Promise<SessionListItem[]> => {
    const params = new URLSearchParams();
    if (status && status !== "all") {
      params.set("status", status);
    }
    const query = params.toString();
    return request(`/v1/sessions${query ? `?${query}` : ""}`);
  },
  getSessionDetail: (id: string): Promise<SessionDetail> => request(`/v1/sessions/${id}/detail`),
  getToolRuns: (status?: string): Promise<ToolRunListItem[]> => {
    const params = new URLSearchParams();
    if (status) {
      params.set("status", status);
    }
    const query = params.toString();
    return request(`/v1/tools${query ? `?${query}` : ""}`);
  },
  getRuns: (filters?: {
    status?: string;
    user_id?: string;
    session_id?: string;
    limit?: number;
  }): Promise<RunTraceListItem[]> => {
    const params = new URLSearchParams();
    if (filters?.status) params.set("status", filters.status);
    if (filters?.user_id) params.set("user_id", filters.user_id);
    if (filters?.session_id) params.set("session_id", filters.session_id);
    if (filters?.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    return request(`/v1/runs${query ? `?${query}` : ""}`);
  },
  getRunDetail: (id: string): Promise<RunTraceDetail> => request(`/v1/runs/${id}`),
  getSchedules: (): Promise<ScheduledJobItem[]> => request("/v1/schedules"),
  getAgentJobs: (filters?: {
    status?: string;
    user_id?: string;
    limit?: number;
  }): Promise<AgentJobListItem[]> => {
    const params = new URLSearchParams();
    if (filters?.status) params.set("status", filters.status);
    if (filters?.user_id) params.set("user_id", filters.user_id);
    if (filters?.limit) params.set("limit", String(filters.limit));
    const query = params.toString();
    return request(`/v1/agent-jobs${query ? `?${query}` : ""}`);
  },
  getAgentJob: (id: string): Promise<AgentJobDetail> => request(`/v1/agent-jobs/${id}`),
  createSchedule: (payload: {
    user_id: string;
    channel_id: string;
    name: string;
    prompt: string;
    schedule_type: string;
    schedule_expr: string;
    enabled: boolean;
  }): Promise<ScheduledJobItem> =>
    request("/v1/schedules", { method: "POST", body: JSON.stringify(payload) }),
  updateSchedule: (
    id: string,
    payload: Partial<{
      name: string;
      prompt: string;
      schedule_type: string;
      schedule_expr: string;
      enabled: boolean;
      channel_id: string;
    }>
  ): Promise<ScheduledJobItem> =>
    request(`/v1/schedules/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteSchedule: (id: string): Promise<{ deleted: boolean }> =>
    request(`/v1/schedules/${id}`, { method: "DELETE" }),
  getUsers: (): Promise<UserListItem[]> => request("/v1/users"),
  updateUser: (id: string, payload: { approved: boolean }): Promise<{ id: string; approved: boolean }> =>
    request(`/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (id: string): Promise<{ id: string; deleted: boolean }> =>
    request(`/v1/users/${id}`, { method: "DELETE" }),
  getChannels: (): Promise<ChannelListItem[]> => request("/v1/channels"),
  getMemory: (userId: string): Promise<MemoryEntry[]> => request(`/v1/memory?user_id=${userId}`),
  reindexMemory: (userId: string): Promise<{ indexed: number; skipped: number; removed: number }> =>
    request(`/v1/memory/reindex?user_id=${userId}`, { method: "POST" }),
  getMemoryFile: (source: string, userId: string): Promise<{ source: string; content: string }> =>
    request(`/v1/memory/file?source=${encodeURIComponent(source)}&user_id=${encodeURIComponent(userId)}`),
  getSandboxStatus: (): Promise<SandboxStatus> => request("/v1/sandbox"),
  getExecutors: (userId?: string): Promise<ExecutorItem[]> => {
    const params = new URLSearchParams();
    if (userId) {
      params.set("user_id", userId);
    }
    const query = params.toString();
    return request(`/v1/executors${query ? `?${query}` : ""}`);
  },
  createExecutor: (payload: {
    user_id: string;
    name: string;
    kind?: string;
    platform?: string;
    hostname?: string;
    capabilities?: Record<string, unknown>;
  }): Promise<ExecutorItem> =>
    request("/v1/executors", { method: "POST", body: JSON.stringify(payload) }),
  createExecutorToken: (payload: {
    user_id: string;
    executor_id?: string;
    executor_name?: string;
  }): Promise<ExecutorTokenCreateOut> =>
    request("/v1/executors/tokens", { method: "POST", body: JSON.stringify(payload) }),
  updateExecutor: (
    id: string,
    payload: Partial<{
      name: string;
      platform: string;
      hostname: string;
    }>
  ): Promise<ExecutorItem> =>
    request(`/v1/executors/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  disableExecutor: (id: string): Promise<ExecutorItem> =>
    request(`/v1/executors/${id}/disable`, { method: "POST" }),
  enableExecutor: (id: string): Promise<ExecutorItem> =>
    request(`/v1/executors/${id}/enable`, { method: "POST" }),
  deleteExecutor: (id: string): Promise<{ id: string; deleted: boolean }> =>
    request(`/v1/executors/${id}`, { method: "DELETE" }),
  getConfig: (): Promise<ConfigResponse> => request("/v1/config"),
  updateConfig: (values: Record<string, unknown>): Promise<ConfigResponse> =>
    request("/v1/config", { method: "PUT", body: JSON.stringify({ values }) }),
  getSecrets: (userId: string): Promise<SecretItem[]> =>
    request(`/v1/secrets?user_id=${encodeURIComponent(userId)}`),
  upsertSecret: (payload: { user_id: string; name: string; value: string }): Promise<SecretItem> =>
    request("/v1/secrets", { method: "POST", body: JSON.stringify(payload) }),
  deleteSecret: (userId: string, name: string): Promise<{ deleted: boolean }> =>
    request(`/v1/secrets/${encodeURIComponent(name)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    }),
};
