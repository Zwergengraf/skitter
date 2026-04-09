export type OverviewRange = "today" | "24h" | "week" | "month" | "year";
export type TableRange = "all" | "today" | "week" | "month";
export type SettingsTabId = "core" | "models" | "automation" | "execution" | "integrations" | "advanced";
export type StructuredValueType = "string" | "number" | "boolean" | "json";

export type StructuredValueRow = {
  keyPath: string;
  valueType: StructuredValueType;
  value: string;
};

export type ExecutorPermissionInfo = {
  label: string;
  status: string;
  detail?: string;
};

export type ExecutorDeviceFeatureInfo = {
  enabled: boolean;
  supported: boolean;
  ready: boolean;
  state: string;
  permission?: string;
  permission_status?: string;
  detail?: string;
};

export type BindingDraft = {
  guild_id: string;
  surface_id: string;
  mode: string;
  agent_profile_id: string;
};

export type GuildOption = {
  guild_id: string;
  guild_name: string;
};
