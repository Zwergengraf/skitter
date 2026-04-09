import { SectionHeader } from "@/components/SectionHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StateMessage } from "@/features/admin/components/StateMessage";
import type { AgentProfile, SecretItem, UserListItem } from "@/lib/types";
import { formatRelativeTime } from "@/lib/utils";

type SecretsViewProps = {
  secretsLoading: boolean;
  refreshSecrets: () => void;
  secretUserLabel: string;
  setSecretUserLabel: (value: string) => void;
  secretUserId: string;
  setSecretUserId: (value: string) => void;
  secretProfileId: string;
  setSecretProfileId: (value: string) => void;
  secretProfiles: AgentProfile[];
  profilesLoadingByUserId: Record<string, boolean>;
  secretName: string;
  setSecretName: (value: string) => void;
  secretValue: string;
  setSecretValue: (value: string) => void;
  secretSaving: boolean;
  handleSecretSave: () => void;
  secretsError: string | null;
  visibleSecrets: SecretItem[];
  handleSecretDelete: (name: string, agentProfileId?: string | null) => void;
  usersData: UserListItem[];
  userLabelFor: (userId: string) => string;
  resolveUserId: (value: string, fallback: string) => string;
  secretScopeLabel: (userId: string, profileId?: string | null) => string;
  secretScopeSharedValue: string;
};

export function SecretsView({
  secretsLoading,
  refreshSecrets,
  secretUserLabel,
  setSecretUserLabel,
  secretUserId,
  setSecretUserId,
  secretProfileId,
  setSecretProfileId,
  secretProfiles,
  profilesLoadingByUserId,
  secretName,
  setSecretName,
  secretValue,
  setSecretValue,
  secretSaving,
  handleSecretSave,
  secretsError,
  visibleSecrets,
  handleSecretDelete,
  usersData,
  userLabelFor,
  resolveUserId,
  secretScopeLabel,
  secretScopeSharedValue,
}: SecretsViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader
            title="Secrets"
            subtitle="Per-user keys and tokens for skills. Values are write-only."
            actionLabel={secretsLoading ? "Refreshing..." : "Refresh"}
            onAction={secretsLoading ? undefined : refreshSecrets}
          />
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">User</label>
              <Input
                list="skitter-secret-users"
                value={secretUserLabel}
                onChange={(event) => {
                  const value = event.target.value;
                  setSecretUserLabel(value);
                  setSecretUserId(value ? resolveUserId(value, secretUserId) : "");
                  setSecretProfileId("");
                }}
                placeholder="Select a user"
              />
              <datalist id="skitter-secret-users">
                {usersData.map((user) => (
                  <option
                    key={user.id}
                    value={`@${user.display_name ?? user.username ?? user.transport_user_id}`}
                    label={user.transport_user_id}
                  />
                ))}
              </datalist>
              <p className="text-xs text-mutedForeground">
                {secretUserId
                  ? `Selected: ${userLabelFor(secretUserId)} (${secretUserId})`
                  : "Type to search by name or paste a user id."}
              </p>
            </div>
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Scope</label>
              <Select
                value={secretProfileId || "loading"}
                onValueChange={(value) => {
                  if (value === "loading") {
                    return;
                  }
                  setSecretProfileId(value);
                }}
                disabled={!secretUserId || profilesLoadingByUserId[secretUserId]}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select scope" />
                </SelectTrigger>
                <SelectContent>
                  {secretProfiles.length || secretProfileId === secretScopeSharedValue ? (
                    <>
                      <SelectItem value={secretScopeSharedValue}>Shared across all profiles</SelectItem>
                      {secretProfiles.map((profile) => (
                        <SelectItem key={profile.id} value={profile.id}>
                          {profile.name} · {profile.slug}
                        </SelectItem>
                      ))}
                    </>
                  ) : (
                    <SelectItem value="loading">
                      {profilesLoadingByUserId[secretUserId] ? "Loading profiles..." : "No profiles available"}
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
              <p className="text-xs text-mutedForeground">
                {secretProfileId === secretScopeSharedValue
                  ? "Shared secrets are visible to every profile for this user."
                  : secretProfileId
                    ? "Profile secrets override shared values with the same name."
                    : "Pick a profile or use shared scope."}
              </p>
            </div>
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Secret name</label>
              <Input value={secretName} onChange={(event) => setSecretName(event.target.value)} placeholder="EXAMPLE_API_KEY" />
              <p className="text-xs text-mutedForeground">Use this name inside skills.</p>
            </div>
          </div>
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Secret value</label>
            <Input
              type="password"
              value={secretValue}
              onChange={(event) => setSecretValue(event.target.value)}
              placeholder="••••••••"
            />
            <div className="flex items-center justify-between">
              <p className="text-xs text-mutedForeground">Values are stored encrypted and never shown again.</p>
              <Button onClick={handleSecretSave} disabled={secretSaving}>
                {secretSaving ? "Saving..." : "Save secret"}
              </Button>
            </div>
          </div>
          {secretsError ? <StateMessage>{secretsError}</StateMessage> : null}
          {secretsLoading ? (
            <StateMessage>Loading secrets...</StateMessage>
          ) : visibleSecrets.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Last used</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleSecrets.map((secret) => (
                  <TableRow key={`${secret.name}:${secret.agent_profile_id ?? "shared"}`}>
                    <TableCell className="font-semibold">{secret.name}</TableCell>
                    <TableCell className="text-mutedForeground">{secretScopeLabel(secretUserId, secret.agent_profile_id)}</TableCell>
                    <TableCell className="text-mutedForeground">{formatRelativeTime(secret.updated_at)}</TableCell>
                    <TableCell className="text-mutedForeground">
                      {secret.last_used_at ? formatRelativeTime(secret.last_used_at) : "—"}
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="danger" onClick={() => handleSecretDelete(secret.name, secret.agent_profile_id)}>
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <StateMessage>
              {secretProfileId === secretScopeSharedValue
                ? "No shared secrets yet."
                : secretProfileId
                  ? "No secrets are available for this profile yet."
                  : "No secrets yet."}
            </StateMessage>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
