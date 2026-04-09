import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SectionHeader } from "@/components/SectionHeader";
import { StateMessage } from "@/features/admin/components/StateMessage";
import {
  EXECUTOR_DEVICE_FEATURE_ORDER,
  executorFeatureBadgeLabel,
  executorFeatureBadgeVariant,
  getExecutorDeviceFeatures,
} from "@/features/admin/utils/executors";
import type { ExecutorItem, SandboxContainer, SandboxStatus, SandboxWorkspace } from "@/lib/types";
import { formatBytes, formatRelativeTime } from "@/lib/utils";

type SandboxViewProps = {
  sandboxLoading: boolean;
  sandboxError: string | null;
  sandboxStatus: SandboxStatus | null;
  sandboxContainers: SandboxContainer[];
  sandboxWorkspaces: SandboxWorkspace[];
  visibleExecutors: ExecutorItem[];
  onlineExecutors: number;
  refreshSandbox: () => void;
  openExecutorOnboarding: () => void;
  openExecutorDetail: (executor: ExecutorItem) => void;
  renderUser: (userId: string) => React.ReactNode;
};

export function SandboxView({
  sandboxLoading,
  sandboxError,
  sandboxStatus,
  sandboxContainers,
  sandboxWorkspaces,
  visibleExecutors,
  onlineExecutors,
  refreshSandbox,
  openExecutorOnboarding,
  openExecutorDetail,
  renderUser,
}: SandboxViewProps) {
  return (
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
            <StateMessage>Loading sandbox status...</StateMessage>
          ) : sandboxError ? (
            <StateMessage>{sandboxError}</StateMessage>
          ) : (
            <>
              <div className="flex justify-end">
                <Button onClick={openExecutorOnboarding}>Add executor node</Button>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="rounded-2xl border border-border bg-card p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Total workspace</p>
                  <p className="mt-2 text-2xl font-semibold">{sandboxStatus?.total_workspace_human ?? "0 B"}</p>
                  <p className="text-xs text-mutedForeground">{sandboxWorkspaces.length} workspaces</p>
                </div>
                <div className="rounded-2xl border border-border bg-card p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Containers</p>
                  <p className="mt-2 text-2xl font-semibold">{sandboxContainers.length}</p>
                  <p className="text-xs text-mutedForeground">
                    {sandboxContainers.filter((c) => c.status === "running").length} running
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-card p-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Executors</p>
                  <p className="mt-2 text-2xl font-semibold">{visibleExecutors.length}</p>
                  <p className="text-xs text-mutedForeground">{onlineExecutors} online</p>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-border bg-card p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold">Workspaces</p>
                    <Badge variant="secondary">{formatBytes(sandboxStatus?.total_workspace_bytes ?? 0)}</Badge>
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
                              <TableCell className="font-semibold">{renderUser(workspace.user_id)}</TableCell>
                              <TableCell>{workspace.size_human}</TableCell>
                              <TableCell className="text-mutedForeground">{formatRelativeTime(workspace.updated_at)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <StateMessage compact>No workspaces found yet.</StateMessage>
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
                                <Badge variant={container.status === "running" ? "success" : "warning"}>
                                  {container.status}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-xs">{container.user_id ? renderUser(container.user_id) : "—"}</TableCell>
                              <TableCell className="text-xs text-mutedForeground">{formatRelativeTime(container.last_activity_at)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <StateMessage compact>No sandbox containers found.</StateMessage>
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
                        {visibleExecutors.map((executor) => {
                          const deviceFeatures = getExecutorDeviceFeatures(executor);
                          return (
                            <TableRow key={executor.id}>
                              <TableCell className="text-xs">
                                <div className="font-semibold">{executor.name}</div>
                                <div className="text-mutedForeground">{executor.id}</div>
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {EXECUTOR_DEVICE_FEATURE_ORDER.map((featureKey) => {
                                    const feature = deviceFeatures[featureKey];
                                    if (!feature.enabled && feature.state === "disabled") {
                                      return null;
                                    }
                                    return (
                                      <Badge key={featureKey} variant={executorFeatureBadgeVariant(feature)} className="text-[10px]">
                                        {executorFeatureBadgeLabel(featureKey, feature)}
                                      </Badge>
                                    );
                                  })}
                                </div>
                              </TableCell>
                              <TableCell className="text-xs">{executor.kind}</TableCell>
                              <TableCell className="text-xs">{renderUser(executor.owner_user_id)}</TableCell>
                              <TableCell>
                                <Badge
                                  variant={executor.disabled ? "warning" : executor.online ? "success" : "secondary"}
                                >
                                  {executor.disabled ? "disabled" : executor.online ? "online" : executor.status}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-xs text-mutedForeground">{executor.hostname || executor.platform || "—"}</TableCell>
                              <TableCell className="text-xs text-mutedForeground">{formatRelativeTime(executor.last_seen_at)}</TableCell>
                              <TableCell className="text-right">
                                <Button size="sm" variant="outline" onClick={() => openExecutorDetail(executor)}>
                                  Details
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  ) : (
                    <StateMessage compact>No non-docker executors found.</StateMessage>
                  )}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
