import type { Dispatch, ReactNode, SetStateAction } from "react";

import {
  Bot,
  Cable,
  ChevronDown,
  ChevronRight,
  Globe,
  GripVertical,
  Plus,
  Trash2,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { StructuredValueRow, StructuredValueType } from "@/features/admin/types";
import {
  expandStructuredRows,
  flattenStructuredObject,
  uniqueStructuredKey,
} from "@/features/admin/utils/structuredValues";
import type {
  ConfigMcpServerItem,
  ConfigModelItem,
  ConfigProviderItem,
  ConfigResponse,
} from "@/lib/types";

const SETTINGS_TEXTAREA_FIELDS = new Set([
  "archive_path",
  "memory_file",
  "oauth_callback_url",
  "bot_status_text",
  "whitelist_users",
  "slack_allowed_team_ids",
  "telegram_allowed_chat_ids",
  "main_model",
  "heartbeat_model",
]);

type DraggingModelChain = { fieldKey: string; index: number } | null;

function reorderListValues(values: string[], fromIndex: number, toIndex: number): string[] {
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
}

function updateStructuredRow(
  rows: StructuredValueRow[],
  index: number,
  patch: Partial<StructuredValueRow>
): StructuredValueRow[] {
  return rows.map((row, currentIndex) => (currentIndex === index ? { ...row, ...patch } : row));
}

function applyStructuredRows(
  currentValue: Record<string, unknown> | undefined,
  nextRows: StructuredValueRow[],
  onValid: (value: Record<string, unknown>) => void,
  setConfigError: (value: string | null) => void,
  errorMessage: string
) {
  try {
    const nextValue = expandStructuredRows(nextRows);
    onValid(nextValue);
    setConfigError(null);
  } catch {
    onValid(currentValue ?? {});
    setConfigError(errorMessage);
  }
}

function StructuredEditorShell({
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
  icon: LucideIcon;
  onAdd: () => void;
  addLabel: string;
  children: ReactNode;
}) {
  return (
    <Card className="border-border/80 bg-card shadow-sm">
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
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

type ConfigCategoryCardProps = {
  category: ConfigResponse["categories"][number];
  configDraft: Record<string, unknown>;
  availableModelSelectors: string[];
  draggingModelChain: DraggingModelChain;
  setDraggingModelChain: Dispatch<SetStateAction<DraggingModelChain>>;
  updateConfigValue: (key: string, value: unknown) => void;
};

export function ConfigCategoryCard({
  category,
  configDraft,
  availableModelSelectors,
  draggingModelChain,
  setDraggingModelChain,
  updateConfigValue,
}: ConfigCategoryCardProps) {
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
          <div className="space-y-2 rounded-2xl border border-border/70 bg-background p-3">
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
                  className="flex items-center gap-3 rounded-xl border border-border/60 bg-card px-3 py-2"
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
                    onClick={() =>
                      updateConfigValue(field.key, chain.filter((_, currentIndex) => currentIndex !== index))
                    }
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
                <SelectValue
                  placeholder={remainingOptions.length ? "Add model to chain" : "No unused models available"}
                />
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
        <Switch checked={Boolean(configDraft[field.key])} onCheckedChange={(value) => updateConfigValue(field.key, value)} />
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
          value={
            Array.isArray(configDraft[field.key])
              ? (configDraft[field.key] as string[]).join(", ")
              : String(configDraft[field.key] ?? "")
          }
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

  return (
    <Card key={category.id} className="border-border/80 bg-card shadow-sm">
      <CardHeader className="space-y-1">
        <CardTitle className="text-base">{category.label}</CardTitle>
        <CardDescription>
          {category.fields.length} option{category.fields.length === 1 ? "" : "s"}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        {category.fields.map((field) => (
          <div key={field.key} className="rounded-2xl border border-border/70 bg-muted/20 p-4">
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
}

type ProvidersEditorProps = {
  configProviders: ConfigProviderItem[];
  openProviderItems: Record<number, boolean>;
  setOpenProviderItems: Dispatch<SetStateAction<Record<number, boolean>>>;
  updateProviderItem: (index: number, key: keyof ConfigProviderItem, value: string) => void;
  addProviderItem: () => void;
  removeProviderItem: (index: number) => void;
};

export function ProvidersEditor({
  configProviders,
  openProviderItems,
  setOpenProviderItems,
  updateProviderItem,
  addProviderItem,
  removeProviderItem,
}: ProvidersEditorProps) {
  return StructuredEditorShell({
    title: "Providers",
    description: "Provider endpoints, API types, and credentials.",
    count: configProviders.length,
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
                {isOpen ? (
                  <ChevronDown className="h-4 w-4 text-mutedForeground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-mutedForeground" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{provider.name || `Provider ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">
                    {provider.api_base || "API endpoint and authentication"}
                  </p>
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
                  <Input value={provider.name ?? ""} onChange={(event) => updateProviderItem(index, "name", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    API Type
                  </label>
                  <Select value={provider.api_type || "openai"} onValueChange={(value) => updateProviderItem(index, "api_type", value)}>
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
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    API Base
                  </label>
                  <Input
                    value={provider.api_base ?? ""}
                    onChange={(event) => updateProviderItem(index, "api_base", event.target.value)}
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    API Key
                  </label>
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
        );
      })
    ) : (
      <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
        No providers configured.
      </div>
    ),
  });
}

type ModelsEditorProps = {
  configModels: ConfigModelItem[];
  configProviders: ConfigProviderItem[];
  openModelItems: Record<number, boolean>;
  setOpenModelItems: Dispatch<SetStateAction<Record<number, boolean>>>;
  updateModelItem: (
    index: number,
    key: keyof ConfigModelItem,
    value: string | number | Record<string, unknown>
  ) => void;
  addModelItem: () => void;
  removeModelItem: (index: number) => void;
  setConfigError: (value: string | null) => void;
};

export function ModelsEditor({
  configModels,
  configProviders,
  openModelItems,
  setOpenModelItems,
  updateModelItem,
  addModelItem,
  removeModelItem,
  setConfigError,
}: ModelsEditorProps) {
  return StructuredEditorShell({
    title: "Models",
    description: "Model registry, costs, and per-model reasoning overrides.",
    count: configModels.length,
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
                {isOpen ? (
                  <ChevronDown className="h-4 w-4 text-mutedForeground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-mutedForeground" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{model.name || `Model ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">
                    {model.provider
                      ? `${model.provider}/${model.name || `model-${index + 1}`}`
                      : "Model selector, provider, pricing"}
                  </p>
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
                  <Input value={model.name ?? ""} onChange={(event) => updateModelItem(index, "name", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Provider
                  </label>
                  <Select value={model.provider ?? ""} onValueChange={(value) => updateModelItem(index, "provider", value)}>
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
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Model ID
                  </label>
                  <Input
                    value={model.model_id ?? ""}
                    onChange={(event) => updateModelItem(index, "model_id", event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Input cost / 1M
                  </label>
                  <Input
                    type="number"
                    step="0.0001"
                    value={String(model.input_cost_per_1m ?? 0)}
                    onChange={(event) => updateModelItem(index, "input_cost_per_1m", Number(event.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Output cost / 1M
                  </label>
                  <Input
                    type="number"
                    step="0.0001"
                    value={String(model.output_cost_per_1m ?? 0)}
                    onChange={(event) => updateModelItem(index, "output_cost_per_1m", Number(event.target.value))}
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Reasoning Overrides
                    </label>
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
                        applyStructuredRows(
                          model.reasoning,
                          nextRows,
                          (value) => updateModelItem(index, "reasoning", value),
                          setConfigError,
                          "Model reasoning overrides contain invalid values."
                        );
                      }}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Add override
                    </Button>
                  </div>
                  <div className="space-y-3 rounded-2xl border border-border/70 bg-background p-3">
                    {reasoningRows.length ? (
                      reasoningRows.map((row, rowIndex) => (
                        <div
                          key={`model-reasoning-${index}-${rowIndex}`}
                          className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_160px_minmax(0,1fr)_auto] md:items-start"
                        >
                          <Input
                            value={row.keyPath}
                            placeholder="anthropic.budget_tokens"
                            onChange={(event) =>
                              applyStructuredRows(
                                model.reasoning,
                                updateStructuredRow(reasoningRows, rowIndex, { keyPath: event.target.value }),
                                (value) => updateModelItem(index, "reasoning", value),
                                setConfigError,
                                "Model reasoning overrides contain invalid values."
                              )
                            }
                          />
                          <Select
                            value={row.valueType}
                            onValueChange={(value) =>
                              applyStructuredRows(
                                model.reasoning,
                                updateStructuredRow(reasoningRows, rowIndex, {
                                  valueType: value as StructuredValueType,
                                }),
                                (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                setConfigError,
                                "Model reasoning overrides contain invalid values."
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
                                applyStructuredRows(
                                  model.reasoning,
                                  updateStructuredRow(reasoningRows, rowIndex, { value }),
                                  (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                  setConfigError,
                                  "Model reasoning overrides contain invalid values."
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
                                applyStructuredRows(
                                  model.reasoning,
                                  updateStructuredRow(reasoningRows, rowIndex, { value: event.target.value }),
                                  (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                  setConfigError,
                                  "Model reasoning overrides contain invalid JSON."
                                )
                              }
                            />
                          ) : (
                            <Input
                              type={row.valueType === "number" ? "number" : "text"}
                              value={row.value}
                              onChange={(event) =>
                                applyStructuredRows(
                                  model.reasoning,
                                  updateStructuredRow(reasoningRows, rowIndex, { value: event.target.value }),
                                  (nextValue) => updateModelItem(index, "reasoning", nextValue),
                                  setConfigError,
                                  "Model reasoning overrides contain invalid values."
                                )
                              }
                            />
                          )}
                          <Button
                            size="icon"
                            variant="outline"
                            onClick={() =>
                              applyStructuredRows(
                                model.reasoning,
                                reasoningRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                                (value) => updateModelItem(index, "reasoning", value),
                                setConfigError,
                                "Model reasoning overrides contain invalid values."
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
        );
      })
    ) : (
      <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
        No models configured.
      </div>
    ),
  });
}

type McpServersEditorProps = {
  configMcpServers: ConfigMcpServerItem[];
  openMcpItems: Record<number, boolean>;
  setOpenMcpItems: Dispatch<SetStateAction<Record<number, boolean>>>;
  updateMcpServerItem: (index: number, key: keyof ConfigMcpServerItem, value: unknown) => void;
  addMcpServerItem: () => void;
  removeMcpServerItem: (index: number) => void;
  setConfigError: (value: string | null) => void;
};

export function McpServersEditor({
  configMcpServers,
  openMcpItems,
  setOpenMcpItems,
  updateMcpServerItem,
  addMcpServerItem,
  removeMcpServerItem,
  setConfigError,
}: McpServersEditorProps) {
  return StructuredEditorShell({
    title: "MCP Servers",
    description: "Configured MCP servers with transport, discovery text, and runtime settings.",
    count: configMcpServers.length,
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
                {isOpen ? (
                  <ChevronDown className="h-4 w-4 text-mutedForeground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-mutedForeground" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{server.name || `MCP Server ${index + 1}`}</p>
                  <p className="truncate text-xs text-mutedForeground">
                    {server.transport === "http" ? server.url || "HTTP transport" : server.command || "stdio transport"}
                  </p>
                </div>
              </button>
              <div className="flex items-center gap-3">
                <Switch checked={Boolean(server.enabled)} onCheckedChange={(value) => updateMcpServerItem(index, "enabled", value)} />
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
                  <Input value={server.name ?? ""} onChange={(event) => updateMcpServerItem(index, "name", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Transport
                  </label>
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
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Description
                  </label>
                  <Textarea rows={3} value={server.description ?? ""} onChange={(event) => updateMcpServerItem(index, "description", event.target.value)} />
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
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Working Directory
                  </label>
                  <Input value={server.cwd ?? ""} onChange={(event) => updateMcpServerItem(index, "cwd", event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Startup Timeout
                  </label>
                  <Input
                    type="number"
                    step="1"
                    value={String(server.startup_timeout_seconds ?? 15)}
                    onChange={(event) => updateMcpServerItem(index, "startup_timeout_seconds", Number(event.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Request Timeout
                  </label>
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
                  <div className="space-y-3 rounded-2xl border border-border/70 bg-background p-3">
                    {headerRows.length ? (
                      headerRows.map((row, rowIndex) => (
                        <div
                          key={`mcp-header-${index}-${rowIndex}`}
                          className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center"
                        >
                          <Input
                            value={row.keyPath}
                            placeholder="Authorization"
                            onChange={(event) => {
                              const nextRows = headerRows.map((entry, currentIndex) =>
                                currentIndex === rowIndex ? { ...entry, keyPath: event.target.value } : entry
                              );
                              applyStructuredRows(
                                server.headers,
                                nextRows,
                                (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                                setConfigError,
                                "MCP headers contain invalid values."
                              );
                            }}
                          />
                          <Input
                            value={row.value}
                            placeholder="Bearer ..."
                            onChange={(event) => {
                              const nextRows = headerRows.map((entry, currentIndex) =>
                                currentIndex === rowIndex ? { ...entry, value: event.target.value } : entry
                              );
                              applyStructuredRows(
                                server.headers,
                                nextRows,
                                (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                                setConfigError,
                                "MCP headers contain invalid values."
                              );
                            }}
                          />
                          <Button
                            size="icon"
                            variant="outline"
                            onClick={() =>
                              applyStructuredRows(
                                server.headers,
                                headerRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                                (value) => updateMcpServerItem(index, "headers", value as Record<string, string>),
                                setConfigError,
                                "MCP headers contain invalid values."
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
                    <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                      Environment
                    </label>
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
                  <div className="space-y-3 rounded-2xl border border-border/70 bg-background p-3">
                    {envRows.length ? (
                      envRows.map((row, rowIndex) => (
                        <div
                          key={`mcp-env-${index}-${rowIndex}`}
                          className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center"
                        >
                          <Input
                            value={row.keyPath}
                            placeholder="API_TOKEN"
                            onChange={(event) => {
                              const nextRows = envRows.map((entry, currentIndex) =>
                                currentIndex === rowIndex ? { ...entry, keyPath: event.target.value } : entry
                              );
                              applyStructuredRows(
                                server.env,
                                nextRows,
                                (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                                setConfigError,
                                "MCP environment contains invalid values."
                              );
                            }}
                          />
                          <Input
                            value={row.value}
                            onChange={(event) => {
                              const nextRows = envRows.map((entry, currentIndex) =>
                                currentIndex === rowIndex ? { ...entry, value: event.target.value } : entry
                              );
                              applyStructuredRows(
                                server.env,
                                nextRows,
                                (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                                setConfigError,
                                "MCP environment contains invalid values."
                              );
                            }}
                          />
                          <Button
                            size="icon"
                            variant="outline"
                            onClick={() =>
                              applyStructuredRows(
                                server.env,
                                envRows.filter((_, currentIndex) => currentIndex !== rowIndex),
                                (value) => updateMcpServerItem(index, "env", value as Record<string, string>),
                                setConfigError,
                                "MCP environment contains invalid values."
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
        );
      })
    ) : (
      <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
        No MCP servers configured.
      </div>
    ),
  });
}
