import type {
  AdminLiveEvent,
  AgentProfile,
  AgentJobDetail,
  AgentJobListItem,
  ChannelListItem,
  ConfigResponse,
  ExecutorItem,
  ExecutorTokenCreateOut,
  MemoryEntry,
  ModelItem,
  OverviewResponse,
  RunTraceDetail,
  RunTraceListItem,
  SandboxStatus,
  ScheduledJobItem,
  SecretItem,
  SessionDetail,
  SessionListItem,
  TransportAccountItem,
  TransportBindingItem,
  ToolRunListItem,
  UserListItem,
} from "@/lib/types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const ADMIN_API_KEY_STORAGE_KEY = "skitter.admin.apiKey";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let runtimeApiKey = "";
let authFailureHandler: ((error: ApiError) => void) | null = null;

export const getStoredApiKey = (): string => {
  if (runtimeApiKey) {
    return runtimeApiKey;
  }
  if (typeof window === "undefined") {
    return "";
  }
  try {
    return localStorage.getItem(ADMIN_API_KEY_STORAGE_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
};

export const setStoredApiKey = (value: string): void => {
  runtimeApiKey = value.trim();
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (runtimeApiKey) {
      localStorage.setItem(ADMIN_API_KEY_STORAGE_KEY, runtimeApiKey);
    } else {
      localStorage.removeItem(ADMIN_API_KEY_STORAGE_KEY);
    }
  } catch {
    // Ignore localStorage write failures and keep runtime-only state.
  }
};

export const clearStoredApiKey = (): void => {
  setStoredApiKey("");
};

export const setApiAuthFailureHandler = (
  handler: ((error: ApiError) => void) | null
): void => {
  authFailureHandler = handler;
};

type ApiResponse<T> = T;
type ApiRequestInit = RequestInit & {
  apiKeyOverride?: string;
  suppressAuthFailureHandler?: boolean;
};

async function request<T>(path: string, options?: ApiRequestInit): Promise<ApiResponse<T>> {
  const { apiKeyOverride, suppressAuthFailureHandler, ...requestOptions } = options ?? {};
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const apiKey = (apiKeyOverride ?? getStoredApiKey()).trim();
  if (!apiKey) {
    throw new ApiError(401, "Admin API key is required.");
  }
  headers["X-API-Key"] = apiKey;
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...requestOptions,
  });

  if (!response.ok) {
    const text = await response.text();
    const error = new ApiError(response.status, text || response.statusText);
    if (!suppressAuthFailureHandler && (response.status === 401 || response.status === 403)) {
      authFailureHandler?.(error);
    }
    throw error;
  }

  return response.json() as Promise<T>;
}

export const api = {
  validateAdminApiKey: (apiKey: string): Promise<OverviewResponse> =>
    request("/v1/overview?range=today", {
      apiKeyOverride: apiKey,
      suppressAuthFailureHandler: true,
    }),
  getOverview: (range?: "today" | "24h" | "week" | "month" | "year"): Promise<OverviewResponse> => {
    const params = new URLSearchParams();
    if (range) {
      params.set("range", range);
    }
    const query = params.toString();
    return request(`/v1/overview${query ? `?${query}` : ""}`);
  },
  getAdminEvents: (limit = 200): Promise<AdminLiveEvent[]> =>
    request(`/v1/admin/events/recent?limit=${limit}`),
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
    agent_profile_id?: string;
    channel_id: string;
    target_origin?: string;
    target_destination_id?: string;
    target_transport_account_key?: string;
    name: string;
    prompt: string;
    model: string;
    schedule_type: string;
    schedule_expr: string;
    enabled: boolean;
  }): Promise<ScheduledJobItem> =>
    request("/v1/schedules", { method: "POST", body: JSON.stringify(payload) }),
  updateSchedule: (
    id: string,
    payload: Partial<{
      agent_profile_id: string;
      name: string;
      prompt: string;
      model: string;
      target_origin: string;
      target_destination_id: string;
      target_transport_account_key: string;
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
  getProfiles: (userId: string, includeArchived = true): Promise<AgentProfile[]> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (includeArchived) {
      params.set("include_archived", "true");
    }
    return request(`/v1/profiles?${params.toString()}`);
  },
  createProfile: (payload: {
    user_id: string;
    name: string;
    source_profile_slug?: string;
    mode?: "blank" | "settings" | "all";
    make_default?: boolean;
  }): Promise<AgentProfile> =>
    request("/v1/profiles", { method: "POST", body: JSON.stringify(payload) }),
  updateProfile: (
    id: string,
    payload: Partial<{
      user_id: string;
      name: string;
      archived: boolean;
      make_default: boolean;
      default_model: string | null;
    }>
  ): Promise<AgentProfile> =>
    request(`/v1/profiles/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  getModels: (): Promise<ModelItem[]> => request("/v1/models"),
  deleteProfile: (id: string): Promise<{ id: string; deleted: boolean }> =>
    request(`/v1/profiles/${id}`, { method: "DELETE" }),
  updateUser: (id: string, payload: { approved: boolean }): Promise<{ id: string; approved: boolean }> =>
    request(`/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (id: string): Promise<{ id: string; deleted: boolean }> =>
    request(`/v1/users/${id}`, { method: "DELETE" }),
  getChannels: (filters?: {
    origin?: string;
    transport_account_key?: string;
  }): Promise<ChannelListItem[]> => {
    const params = new URLSearchParams();
    if (filters?.origin) {
      params.set("origin", filters.origin);
    }
    if (filters?.transport_account_key) {
      params.set("transport_account_key", filters.transport_account_key);
    }
    const query = params.toString();
    return request(`/v1/channels${query ? `?${query}` : ""}`);
  },
  getTransportAccounts: (userId: string, agentProfileId?: string): Promise<TransportAccountItem[]> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/transport-accounts?${params.toString()}`);
  },
  createTransportAccount: (payload: {
    user_id: string;
    agent_profile_id: string;
    transport?: string;
    display_name?: string;
    enabled?: boolean;
    credential_value: string;
  }): Promise<TransportAccountItem> =>
    request("/v1/transport-accounts", { method: "POST", body: JSON.stringify(payload) }),
  updateTransportAccount: (
    accountKey: string,
    payload: Partial<{
      display_name: string;
      enabled: boolean;
      credential_value: string;
    }>
  ): Promise<TransportAccountItem> =>
    request(`/v1/transport-accounts/${encodeURIComponent(accountKey)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteTransportAccount: (accountKey: string): Promise<{ account_key: string; deleted: boolean }> =>
    request(`/v1/transport-accounts/${encodeURIComponent(accountKey)}`, { method: "DELETE" }),
  getTransportSurfaces: (accountKey: string): Promise<ChannelListItem[]> =>
    request(`/v1/transport-accounts/${encodeURIComponent(accountKey)}/surfaces`),
  getTransportBindings: (accountKey: string): Promise<TransportBindingItem[]> =>
    request(`/v1/transport-accounts/${encodeURIComponent(accountKey)}/bindings`),
  createTransportBinding: (payload: {
    transport_account_key: string;
    user_id: string;
    agent_profile_id?: string;
    origin?: string;
    surface_kind: string;
    surface_id: string;
    mode?: string;
    enabled?: boolean;
  }): Promise<TransportBindingItem> =>
    request("/v1/transport-accounts/bindings", { method: "POST", body: JSON.stringify(payload) }),
  updateTransportBinding: (
    bindingId: string,
    payload: Partial<{
      agent_profile_id: string;
      mode: string;
      enabled: boolean;
    }>
  ): Promise<TransportBindingItem> =>
    request(`/v1/transport-accounts/bindings/${bindingId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteTransportBinding: (bindingId: string): Promise<{ id: string; deleted: boolean }> =>
    request(`/v1/transport-accounts/bindings/${bindingId}`, { method: "DELETE" }),
  getMemory: (userId: string, agentProfileId?: string): Promise<MemoryEntry[]> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/memory?${params.toString()}`);
  },
  reindexMemory: (
    userId: string,
    agentProfileId?: string
  ): Promise<{ indexed: number; skipped: number; removed: number }> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/memory/reindex?${params.toString()}`, { method: "POST" });
  },
  getMemoryFile: (
    source: string,
    userId: string,
    agentProfileId?: string
  ): Promise<{ source: string; content: string }> => {
    const params = new URLSearchParams();
    params.set("source", source);
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/memory/file?${params.toString()}`);
  },
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
  getSecrets: (userId: string, agentProfileId?: string): Promise<SecretItem[]> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/secrets?${params.toString()}`);
  },
  upsertSecret: (payload: { user_id: string; agent_profile_id?: string; name: string; value: string }): Promise<SecretItem> =>
    request("/v1/secrets", { method: "POST", body: JSON.stringify(payload) }),
  deleteSecret: (userId: string, name: string, agentProfileId?: string): Promise<{ deleted: boolean }> => {
    const params = new URLSearchParams();
    params.set("user_id", userId);
    if (agentProfileId) {
      params.set("agent_profile_id", agentProfileId);
    }
    return request(`/v1/secrets/${encodeURIComponent(name)}?${params.toString()}`, {
      method: "DELETE",
    });
  },
};

export const streamAdminEvents = async (
  onEvent: (event: AdminLiveEvent) => void,
  options?: { signal?: AbortSignal }
): Promise<void> => {
  const apiKey = getStoredApiKey().trim();
  if (!apiKey) {
    throw new ApiError(401, "Admin API key is required.");
  }
  const response = await fetch(`${API_BASE}/v1/admin/events/stream`, {
    headers: {
      "X-API-Key": apiKey,
      Accept: "text/event-stream",
    },
    signal: options?.signal,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text || response.statusText);
  }
  if (!response.body) {
    throw new Error("Live event stream is unavailable.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushChunk = (chunk: string) => {
    const lines = chunk.split("\n");
    const dataLines: string[] = [];
    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      if (!line || line.startsWith(":") || line.startsWith("event:")) {
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (!dataLines.length) {
      return;
    }
    onEvent(JSON.parse(dataLines.join("\n")) as AdminLiveEvent);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      flushChunk(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    flushChunk(buffer);
  }
};
