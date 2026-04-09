import type { ExecutorItem } from "@/lib/types";
import type { ExecutorDeviceFeatureInfo, ExecutorPermissionInfo } from "@/features/admin/types";

export const EXECUTOR_DEVICE_FEATURE_ORDER = ["notify", "screenshot", "mouse", "keyboard"] as const;

export const EXECUTOR_DEVICE_FEATURE_LABELS: Record<(typeof EXECUTOR_DEVICE_FEATURE_ORDER)[number], string> = {
  notify: "Notify",
  screenshot: "Screenshot",
  mouse: "Mouse",
  keyboard: "Keyboard",
};

const EXECUTOR_PERMISSION_LABELS: Record<string, string> = {
  accessibility: "Accessibility",
  screen_recording: "Screen Recording",
};

export const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

export const getExecutorPermissions = (executor: ExecutorItem): Record<string, ExecutorPermissionInfo> => {
  const capabilities = asRecord(executor.capabilities) ?? {};
  const raw = asRecord(capabilities.permissions);
  if (!raw) {
    return {};
  }
  const permissions: Record<string, ExecutorPermissionInfo> = {};
  for (const [key, value] of Object.entries(raw)) {
    const record = asRecord(value);
    if (!record) {
      continue;
    }
    permissions[key] = {
      label: typeof record.label === "string" && record.label.trim() ? record.label : EXECUTOR_PERMISSION_LABELS[key] ?? key,
      status: typeof record.status === "string" && record.status.trim() ? record.status : "unknown",
      detail: typeof record.detail === "string" && record.detail.trim() ? record.detail : undefined,
    };
  }
  return permissions;
};

export const getExecutorDeviceFeatures = (executor: ExecutorItem): Record<string, ExecutorDeviceFeatureInfo> => {
  const capabilities = asRecord(executor.capabilities) ?? {};
  const raw = asRecord(capabilities.device_features);
  const features: Record<string, ExecutorDeviceFeatureInfo> = {};
  for (const key of EXECUTOR_DEVICE_FEATURE_ORDER) {
    const record = raw ? asRecord(raw[key]) : null;
    if (record) {
      features[key] = {
        enabled: Boolean(record.enabled),
        supported: record.supported === undefined ? Boolean(record.enabled) : Boolean(record.supported),
        ready: Boolean(record.ready),
        state: typeof record.state === "string" && record.state.trim() ? record.state : Boolean(record.ready) ? "ready" : "unknown",
        permission: typeof record.permission === "string" ? record.permission : undefined,
        permission_status: typeof record.permission_status === "string" ? record.permission_status : undefined,
        detail: typeof record.detail === "string" && record.detail.trim() ? record.detail : undefined,
      };
      continue;
    }
    const enabled = Boolean(capabilities[key]);
    features[key] = {
      enabled,
      supported: enabled,
      ready: enabled,
      state: enabled ? "ready" : "disabled",
    };
  }
  return features;
};

export const executorFeatureBadgeVariant = (feature: ExecutorDeviceFeatureInfo): "secondary" | "success" | "warning" | "danger" => {
  if (feature.state === "ready") {
    return "success";
  }
  if (feature.state === "disabled") {
    return "secondary";
  }
  if (feature.state === "unsupported") {
    return "danger";
  }
  return "warning";
};

export const executorFeatureBadgeLabel = (
  key: keyof typeof EXECUTOR_DEVICE_FEATURE_LABELS,
  feature: ExecutorDeviceFeatureInfo
): string => {
  const label = EXECUTOR_DEVICE_FEATURE_LABELS[key];
  if (feature.state === "ready") {
    return label;
  }
  if (feature.state === "disabled") {
    return `${label} off`;
  }
  if (feature.state === "unsupported") {
    return `${label} unavailable`;
  }
  if (feature.state === "needs_permission") {
    return `${label} permission`;
  }
  return `${label} check`;
};

export const executorPermissionBadgeVariant = (status: string): "secondary" | "success" | "warning" | "danger" => {
  if (status === "granted") {
    return "success";
  }
  if (status === "missing" || status === "unknown") {
    return "warning";
  }
  if (status === "unsupported") {
    return "danger";
  }
  return "secondary";
};

export const executorPermissionStatusLabel = (status: string): string => {
  if (status === "granted") {
    return "Granted";
  }
  if (status === "missing") {
    return "Missing";
  }
  if (status === "not_required") {
    return "Not required";
  }
  if (status === "unsupported") {
    return "Unavailable";
  }
  return "Unknown";
};
