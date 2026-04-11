import type { Dispatch, SetStateAction } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  EXECUTOR_DEVICE_FEATURE_LABELS,
  EXECUTOR_DEVICE_FEATURE_ORDER,
  executorFeatureBadgeLabel,
  executorFeatureBadgeVariant,
  executorPermissionBadgeVariant,
  executorPermissionStatusLabel,
} from "@/features/admin/utils/executors";
import type { ExecutorDeviceFeatureInfo, ExecutorPermissionInfo } from "@/features/admin/types";
import type { ExecutorItem, UserListItem } from "@/lib/types";

type ExecutorFormState = {
  user_id: string;
  name: string;
  api_url: string;
  workspace_root: string;
};

type ExecutorDetailFormState = {
  name: string;
};

type ExecutorOnboardingResult = {
  executorId: string;
  executorName: string;
  token: string;
  command: string;
  windowsCommand: string;
  configYaml: string;
} | null;

type ExecutorOnboardingDialogProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  executorForm: ExecutorFormState;
  setExecutorForm: Dispatch<SetStateAction<ExecutorFormState>>;
  approvedUsers: UserListItem[];
  userLabelFor: (userId: string) => string;
  executorOnboardingLoading: boolean;
  executorOnboardingError: string | null;
  executorOnboardingResult: ExecutorOnboardingResult;
  setExecutorOnboardingError: (value: string | null) => void;
  setExecutorOnboardingResult: (value: ExecutorOnboardingResult) => void;
  runExecutorOnboarding: () => void;
};

export function ExecutorOnboardingDialog({
  open,
  setOpen,
  executorForm,
  setExecutorForm,
  approvedUsers,
  userLabelFor,
  executorOnboardingLoading,
  executorOnboardingError,
  executorOnboardingResult,
  setExecutorOnboardingError,
  setExecutorOnboardingResult,
  runExecutorOnboarding,
}: ExecutorOnboardingDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) {
          setExecutorOnboardingError(null);
          setExecutorOnboardingResult(null);
        }
      }}
    >
      <DialogContent className="w-[94vw] max-w-4xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add Executor Node</DialogTitle>
          <DialogDescription>Create a node executor, mint a token, and generate launch commands for macOS, Linux, and Windows.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">User</p>
            <Select
              value={executorForm.user_id || "none"}
              onValueChange={(value) =>
                setExecutorForm((current) => ({
                  ...current,
                  user_id: value === "none" ? "" : value,
                }))
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select user" />
              </SelectTrigger>
              <SelectContent>
                {approvedUsers.length ? (
                  approvedUsers.map((user) => (
                    <SelectItem key={user.id} value={user.id}>
                      {userLabelFor(user.id)}
                    </SelectItem>
                  ))
                ) : (
                  <SelectItem value="none">No approved users</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Executor name</p>
            <Input
              value={executorForm.name}
              onChange={(event) => setExecutorForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="workstation-main"
            />
          </div>
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Workspace root</p>
            <Input
              value={executorForm.workspace_root}
              onChange={(event) =>
                setExecutorForm((current) => ({
                  ...current,
                  workspace_root: event.target.value,
                }))
              }
              placeholder={String.raw`workspace or C:\Users\you\SkitterNode\workspace`}
            />
          </div>
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">API URL</p>
            <Input
              value={executorForm.api_url}
              onChange={(event) => setExecutorForm((current) => ({ ...current, api_url: event.target.value }))}
              placeholder="http://localhost:8000"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={runExecutorOnboarding} disabled={executorOnboardingLoading}>
            {executorOnboardingLoading ? "Generating..." : "Create Token"}
          </Button>
          {executorOnboardingError ? <span className="text-sm text-danger">{executorOnboardingError}</span> : null}
        </div>

        {executorOnboardingResult ? (
          <div className="grid gap-3 lg:grid-cols-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">macOS / Linux</p>
              <Textarea className="mt-2 min-h-[120px] font-mono text-xs" readOnly value={executorOnboardingResult.command} />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(executorOnboardingResult.command).catch(() => undefined);
                  }}
                >
                  Copy command
                </Button>
                <span className="text-xs text-mutedForeground">
                  Executor `{executorOnboardingResult.executorName}` created.
                </span>
              </div>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Windows PowerShell</p>
              <Textarea className="mt-2 min-h-[120px] font-mono text-xs" readOnly value={executorOnboardingResult.windowsCommand} />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(executorOnboardingResult.windowsCommand).catch(() => undefined);
                  }}
                >
                  Copy command
                </Button>
                <span className="text-xs text-mutedForeground">Runs in PowerShell.</span>
              </div>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">Config YAML</p>
              <Textarea className="mt-2 min-h-[120px] font-mono text-xs" readOnly value={executorOnboardingResult.configYaml} />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(executorOnboardingResult.configYaml).catch(() => undefined);
                  }}
                >
                  Copy YAML
                </Button>
                <span className="text-xs text-mutedForeground">Token is shown once. Save it now.</span>
              </div>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

type ExecutorDetailDialogProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  selectedExecutor: ExecutorItem | null;
  setSelectedExecutor: (value: ExecutorItem | null) => void;
  executorDetailForm: ExecutorDetailFormState;
  setExecutorDetailForm: Dispatch<SetStateAction<ExecutorDetailFormState>>;
  selectedExecutorDeviceFeatures: Record<string, ExecutorDeviceFeatureInfo> | null;
  selectedExecutorPermissions: Record<string, ExecutorPermissionInfo> | null;
  selectedExecutorTools: string[];
  executorDetailSaving: boolean;
  executorDetailDeleting: boolean;
  executorDetailError: string | null;
  setExecutorDetailError: (value: string | null) => void;
  userLabelFor: (userId: string) => string;
  saveExecutorDetail: () => void;
  disableExecutor: () => void;
  enableExecutor: () => void;
  deleteExecutor: () => void;
};

export function ExecutorDetailDialog({
  open,
  setOpen,
  selectedExecutor,
  setSelectedExecutor,
  executorDetailForm,
  setExecutorDetailForm,
  selectedExecutorDeviceFeatures,
  selectedExecutorPermissions,
  selectedExecutorTools,
  executorDetailSaving,
  executorDetailDeleting,
  executorDetailError,
  setExecutorDetailError,
  userLabelFor,
  saveExecutorDetail,
  disableExecutor,
  enableExecutor,
  deleteExecutor,
}: ExecutorDetailDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) {
          setExecutorDetailError(null);
          setSelectedExecutor(null);
        }
      }}
    >
      <DialogContent className="w-[94vw] max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Executor details</DialogTitle>
          <DialogDescription>Edit executor metadata or disable this executor.</DialogDescription>
        </DialogHeader>
        {selectedExecutor ? (
          <div className="space-y-5">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Executor ID</p>
                <Input value={selectedExecutor.id} readOnly />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Owner</p>
                <Input value={userLabelFor(selectedExecutor.owner_user_id)} readOnly />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Name</p>
                <Input
                  value={executorDetailForm.name}
                  onChange={(event) => setExecutorDetailForm((current) => ({ ...current, name: event.target.value }))}
                />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Kind</p>
                <Input value={selectedExecutor.kind} readOnly />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Platform</p>
                <Input value={selectedExecutor.platform ?? "—"} readOnly />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-[0.2em] text-mutedForeground">Hostname</p>
                <Input value={selectedExecutor.hostname ?? "—"} readOnly />
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-border bg-muted/20 p-4">
                <p className="text-sm font-semibold">Host Features</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedExecutorDeviceFeatures ? (
                    EXECUTOR_DEVICE_FEATURE_ORDER.map((featureKey) => {
                      const feature = selectedExecutorDeviceFeatures[featureKey];
                      return (
                        <Badge key={featureKey} variant={executorFeatureBadgeVariant(feature)} className="text-[11px]">
                          {executorFeatureBadgeLabel(featureKey, feature)}
                        </Badge>
                      );
                    })
                  ) : (
                    <Badge variant="secondary">No host feature data</Badge>
                  )}
                </div>
                {selectedExecutorDeviceFeatures ? (
                  <div className="mt-4 space-y-3">
                    {EXECUTOR_DEVICE_FEATURE_ORDER.map((featureKey) => {
                      const feature = selectedExecutorDeviceFeatures[featureKey];
                      return (
                        <div key={featureKey} className="rounded-2xl border border-border/70 bg-card px-3 py-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-medium">{EXECUTOR_DEVICE_FEATURE_LABELS[featureKey]}</p>
                            <Badge variant={executorFeatureBadgeVariant(feature)}>
                              {feature.state === "ready"
                                ? "Ready"
                                : feature.state === "disabled"
                                  ? "Disabled"
                                  : feature.state === "needs_permission"
                                    ? "Permission needed"
                                    : feature.state === "unsupported"
                                      ? "Unavailable"
                                      : "Check"}
                            </Badge>
                          </div>
                          {feature.detail ? <p className="mt-2 text-xs text-mutedForeground">{feature.detail}</p> : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>

              <div className="rounded-2xl border border-border bg-muted/20 p-4">
                <p className="text-sm font-semibold">Permissions</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedExecutorPermissions && Object.keys(selectedExecutorPermissions).length ? (
                    Object.entries(selectedExecutorPermissions).map(([key, permission]) => (
                      <Badge key={key} variant={executorPermissionBadgeVariant(permission.status)} className="text-[11px]">
                        {permission.label}: {executorPermissionStatusLabel(permission.status)}
                      </Badge>
                    ))
                  ) : (
                    <Badge variant="secondary">Not reported yet</Badge>
                  )}
                </div>
                {selectedExecutorPermissions && Object.keys(selectedExecutorPermissions).length ? (
                  <div className="mt-4 space-y-3">
                    {Object.entries(selectedExecutorPermissions).map(([key, permission]) => (
                      <div key={key} className="rounded-2xl border border-border/70 bg-card px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-medium">{permission.label}</p>
                          <Badge variant={executorPermissionBadgeVariant(permission.status)}>
                            {executorPermissionStatusLabel(permission.status)}
                          </Badge>
                        </div>
                        {permission.detail ? <p className="mt-2 text-xs text-mutedForeground">{permission.detail}</p> : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-xs text-mutedForeground">
                    Restart this executor node after upgrading if you want it to report host permission status.
                  </p>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-muted/20 p-4">
              <p className="text-sm font-semibold">Enabled Tools</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {selectedExecutorTools.length ? (
                  selectedExecutorTools.map((toolName) => (
                    <Badge key={toolName} variant="secondary">
                      {toolName}
                    </Badge>
                  ))
                ) : (
                  <Badge variant="secondary">No tool list reported</Badge>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button onClick={saveExecutorDetail} disabled={executorDetailSaving || executorDetailDeleting}>
                {executorDetailSaving ? "Saving..." : "Save changes"}
              </Button>
            </div>

            <div className="rounded-2xl border border-danger/40 bg-danger/5 p-4 space-y-3">
              <p className="text-sm font-semibold text-danger">Executor Controls</p>
              <p className="text-xs text-mutedForeground">
                Disable revokes executor tokens. Delete removes the executor permanently.
              </p>
              <div className="flex flex-wrap gap-2">
                {selectedExecutor.disabled ? (
                  <Button variant="outline" onClick={enableExecutor} disabled={executorDetailDeleting || executorDetailSaving}>
                    {executorDetailDeleting ? "Enabling..." : "Enable executor"}
                  </Button>
                ) : (
                  <Button variant="danger" onClick={disableExecutor} disabled={executorDetailDeleting || executorDetailSaving}>
                    {executorDetailDeleting ? "Disabling..." : "Disable executor"}
                  </Button>
                )}
                <Button variant="outline" onClick={deleteExecutor} disabled={executorDetailDeleting || executorDetailSaving}>
                  Delete executor
                </Button>
              </div>
            </div>

            {executorDetailError ? <div className="text-sm text-danger">{executorDetailError}</div> : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
