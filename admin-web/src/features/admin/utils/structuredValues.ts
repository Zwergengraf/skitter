import type { ConfigResponse } from "@/lib/types";
import type { StructuredValueRow, StructuredValueType } from "@/features/admin/types";

export const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

export const inferStructuredValueType = (value: unknown): StructuredValueType => {
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

export const stringifyStructuredValue = (value: unknown, valueType: StructuredValueType): string => {
  if (valueType === "json") {
    return JSON.stringify(value ?? {}, null, 2);
  }
  return String(value ?? "");
};

export const flattenStructuredObject = (value: unknown, prefix = ""): StructuredValueRow[] => {
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

export const parseStructuredValue = (row: StructuredValueRow): unknown => {
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

export const expandStructuredRows = (rows: StructuredValueRow[]): Record<string, unknown> => {
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

export const uniqueStructuredKey = (existing: string[], base: string): string => {
  if (!existing.includes(base)) {
    return base;
  }
  let index = 2;
  while (existing.includes(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
};

export const buildConfigDraft = (data: ConfigResponse): Record<string, unknown> => {
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
