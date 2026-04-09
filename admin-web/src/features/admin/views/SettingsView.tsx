import type { ReactNode } from "react";
import { Bot, Cable, Database, Globe, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SectionHeader } from "@/components/SectionHeader";
import { StateMessage } from "@/features/admin/components/StateMessage";
import type { SettingsTabId } from "@/features/admin/types";
import type { ConfigResponse } from "@/lib/types";

type SettingsViewProps = {
  apiReady: boolean;
  maskedAdminApiKey: string;
  openApiKeyDialog: () => void;
  clearAdminApiKey: () => void;
  configSaving: boolean;
  saveConfig: () => void;
  configLoading: boolean;
  configError: string | null;
  configData: ConfigResponse | null;
  settingsModelCount: number;
  settingsProviderCount: number;
  settingsMcpCount: number;
  settingsQuery: string;
  setSettingsQuery: (value: string) => void;
  settingsTab: SettingsTabId;
  setSettingsTab: (value: SettingsTabId) => void;
  settingsTabMeta: Record<SettingsTabId, { label: string; icon: typeof Bot; categories: string[] }>;
  settingsCategoriesByTab: Record<SettingsTabId, ConfigResponse["categories"]>;
  settingsQueryNormalized: string;
  renderProvidersEditor: () => ReactNode;
  renderModelsEditor: () => ReactNode;
  renderMcpServersEditor: () => ReactNode;
  renderConfigCategoryCard: (category: ConfigResponse["categories"][number]) => ReactNode;
  apiBase: string;
};

export function SettingsView({
  apiReady,
  maskedAdminApiKey,
  openApiKeyDialog,
  clearAdminApiKey,
  configSaving,
  saveConfig,
  configLoading,
  configError,
  configData,
  settingsModelCount,
  settingsProviderCount,
  settingsMcpCount,
  settingsQuery,
  setSettingsQuery,
  settingsTab,
  setSettingsTab,
  settingsTabMeta,
  settingsCategoriesByTab,
  settingsQueryNormalized,
  renderProvidersEditor,
  renderModelsEditor,
  renderMcpServersEditor,
  renderConfigCategoryCard,
  apiBase,
}: SettingsViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader
            title="Admin API Access"
            subtitle="The admin API key is stored client-side in this browser and used for API requests."
          />
        </CardHeader>
        <CardContent className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={apiReady ? "success" : "warning"}>{apiReady ? "Configured" : "Required"}</Badge>
              <span className="font-mono text-sm">{maskedAdminApiKey}</span>
            </div>
            <p className="text-sm text-mutedForeground">API base: {apiBase}</p>
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
            <StateMessage>Loading configuration...</StateMessage>
          ) : configError ? (
            <StateMessage>{configError}</StateMessage>
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
                <p className="text-xs text-mutedForeground">Secret fields stay masked unless you enter a new value.</p>
              </div>

              <Tabs value={settingsTab} onValueChange={(value) => setSettingsTab(value as SettingsTabId)}>
                <TabsList className="grid h-auto w-full grid-cols-2 gap-2 rounded-3xl bg-muted/40 p-2 lg:grid-cols-6">
                  {Object.entries(settingsTabMeta).map(([tabId, meta]) => {
                    const Icon = meta.icon;
                    return (
                      <TabsTrigger key={tabId} value={tabId} className="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs">
                        <Icon className="h-4 w-4" />
                        {meta.label}
                      </TabsTrigger>
                    );
                  })}
                </TabsList>

                {(Object.keys(settingsTabMeta) as SettingsTabId[]).map((tabId) => (
                  <TabsContent key={tabId} value={tabId} className="mt-6 space-y-6">
                    {tabId === "models" ? (
                      <div className="grid gap-6 xl:grid-cols-2">
                        {renderProvidersEditor()}
                        {renderModelsEditor()}
                      </div>
                    ) : null}
                    {tabId === "integrations" ? <div className="grid gap-6">{renderMcpServersEditor()}</div> : null}
                    <div className="grid gap-6">
                      {settingsCategoriesByTab[tabId].length ? (
                        settingsCategoriesByTab[tabId].map((category) => renderConfigCategoryCard(category))
                      ) : (
                        <StateMessage>
                          No settings match this tab{settingsQueryNormalized ? " and the current filter" : ""}.
                        </StateMessage>
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
  );
}
