export type HealthStatus = "healthy" | "warning" | "degraded";

export interface Metric {
  label: string;
  value: number | string;
  delta: string;
  trend: "up" | "down" | "flat";
}

export interface OverviewCostPoint {
  label: string;
  cost: number;
}

export interface OverviewSession {
  id: string;
  user: string;
  transport: string;
  status: string;
  last_active_at: string | null;
  total_tokens: number;
}

export interface OverviewToolApproval {
  id: string;
  tool: string;
  status: string;
  requested_by: string;
  created_at: string;
}

export interface OverviewResponse {
  cost_trajectory: OverviewCostPoint[];
  system_health: ServiceStatus[];
  live_sessions: OverviewSession[];
  tool_approvals: OverviewToolApproval[];
}

export interface SessionListItem {
  id: string;
  user: string;
  transport: string;
  status: string;
  last_active_at: string | null;
  total_tokens: number;
  total_cost: number;
  last_input_tokens: number;
}

export interface SessionMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  meta: Record<string, unknown>;
}

export interface SessionToolRun {
  id: string;
  tool: string;
  status: string;
  executor_id?: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  approved_by?: string | null;
  created_at: string;
}

export interface SessionDetail {
  id: string;
  user_id: string;
  user: string;
  status: string;
  created_at: string;
  last_active_at?: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  last_input_tokens: number;
  last_output_tokens: number;
  last_total_tokens: number;
  last_cost: number;
  last_model?: string | null;
  last_usage_at?: string | null;
  messages: SessionMessage[];
  tool_runs: SessionToolRun[];
}

export interface MemoryEntry {
  id: string;
  summary: string;
  tags: string[];
  created_at: string;
  source?: string | null;
  session_ids: string[];
}

export interface ToolRunListItem {
  id: string;
  run_id?: string | null;
  tool: string;
  status: string;
  executor_id?: string | null;
  requested_by: string;
  created_at: string;
  session_id: string;
  approved_by?: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  reasoning: string[];
}

export interface RunTraceListItem {
  id: string;
  session_id: string;
  user_id: string;
  message_id: string;
  origin: string;
  status: string;
  model?: string | null;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  error?: string | null;
  limit_reason?: string | null;
}

export interface RunTraceEventItem {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunTraceDetail {
  run: RunTraceListItem;
  input_text: string;
  output_text: string;
  limit_detail?: string | null;
  tool_runs: SessionToolRun[];
  events: RunTraceEventItem[];
}

export interface ScheduledJobItem {
  id: string;
  user_id: string;
  channel_id: string;
  model: string;
  name: string;
  prompt: string;
  schedule_type: string;
  schedule_expr: string;
  timezone: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  last_delivery_error?: string | null;
  consecutive_failures?: number;
  last_attempts?: number;
  last_run_id?: string | null;
}

export interface AgentJobListItem {
  id: string;
  user_id: string;
  session_id?: string | null;
  kind: string;
  name: string;
  status: string;
  model?: string | null;
  target_scope_type: string;
  target_scope_id: string;
  target_origin?: string | null;
  target_destination_id?: string | null;
  cancel_requested: boolean;
  tool_calls_used: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  delivered_at?: string | null;
  delivery_error?: string | null;
}

export interface AgentJobDetail extends AgentJobListItem {
  run_id: string;
  payload: Record<string, unknown>;
  limits: Record<string, unknown>;
  result: Record<string, unknown>;
  tool_runs: SessionToolRun[];
}

export interface UserListItem {
  id: string;
  transport_user_id: string;
  display_name?: string | null;
  username?: string | null;
  avatar_url?: string | null;
  approved: boolean;
}

export interface ChannelListItem {
  id: string;
  name: string;
  kind: string;
  label: string;
  guild_name?: string | null;
}

export interface SandboxWorkspace {
  user_id: string;
  path: string;
  size_bytes: number;
  size_human: string;
  updated_at: string;
}

export interface SandboxContainer {
  id: string;
  name: string;
  status: string;
  user_id?: string | null;
  created_at?: string | null;
  base_url?: string | null;
  ports: string[];
  last_activity_at?: string | null;
}

export interface SandboxStatus {
  workspaces: SandboxWorkspace[];
  containers: SandboxContainer[];
  total_workspace_bytes: number;
  total_workspace_human: string;
}

export interface ExecutorItem {
  id: string;
  owner_user_id: string;
  name: string;
  kind: string;
  platform?: string | null;
  hostname?: string | null;
  status: string;
  capabilities: Record<string, unknown>;
  last_seen_at?: string | null;
  created_at: string;
  disabled: boolean;
  online: boolean;
}

export interface ExecutorTokenCreateOut {
  executor_id: string;
  executor_name: string;
  token: string;
  token_prefix: string;
}

export interface ConfigField {
  key: string;
  label: string;
  type: "string" | "number" | "boolean" | "list";
  value: unknown;
  description?: string | null;
  secret?: boolean;
  minimum?: number | null;
  maximum?: number | null;
  step?: number | null;
}

export interface ConfigCategory {
  id: string;
  label: string;
  fields: ConfigField[];
}

export interface ConfigProviderItem {
  name: string;
  api_type?: string;
  api_base?: string;
  api_key?: string;
}

export interface ConfigModelItem {
  name: string;
  provider: string;
  model_id?: string;
  input_cost_per_1m?: number;
  output_cost_per_1m?: number;
  reasoning?: Record<string, unknown>;
}

export interface ConfigMcpServerItem {
  name: string;
  description?: string;
  transport?: string;
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
  cwd?: string;
  enabled?: boolean;
  startup_timeout_seconds?: number;
  request_timeout_seconds?: number;
}

export interface ConfigResponse {
  categories: ConfigCategory[];
  providers: ConfigProviderItem[];
  models: ConfigModelItem[];
  mcp_servers: ConfigMcpServerItem[];
}

export interface SecretItem {
  name: string;
  created_at: string;
  updated_at: string;
  last_used_at?: string | null;
}

export interface SessionRow {
  id: string;
  user: string;
  transport: "discord" | "web" | "cli";
  lastActive: string;
  state: "active" | "idle" | "paused";
  tokens: number;
}

export interface ToolRunRow {
  id: string;
  tool: string;
  status: "pending" | "approved" | "running" | "completed" | "failed";
  requestedBy: string;
  createdAt: string;
}

export interface ScheduledJobRow {
  id: string;
  name: string;
  schedule: string;
  channel: string;
  nextRun: string;
  status: "active" | "paused";
}

export interface MemoryRow {
  id: string;
  summary: string;
  updatedAt: string;
  embeddings: number;
}

export interface ServiceStatus {
  name: string;
  status: HealthStatus;
  detail: string;
}

export interface IncidentRow {
  id: string;
  title: string;
  severity: "low" | "medium" | "high";
  timestamp: string;
}
