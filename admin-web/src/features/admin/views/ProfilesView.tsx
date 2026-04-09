import type { Dispatch, SetStateAction } from "react";

import {
  Bot,
  Cable,
  ChevronDown,
  ChevronRight,
  Clock3,
  Globe,
  Plus,
  RefreshCcw,
} from "lucide-react";

import { SectionHeader } from "@/components/SectionHeader";
import { BindingManager } from "@/features/admin/components/BindingManager";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { BindingDraft, GuildOption } from "@/features/admin/types";
import { ProfileMetricCard } from "@/features/admin/components/ProfileMetricCard";
import type {
  AgentProfile,
  ChannelListItem,
  TransportAccountItem,
  TransportBindingItem,
  UserListItem,
} from "@/lib/types";
import { formatRelativeTime } from "@/lib/utils";

type ProfileListTab = "active" | "archived";
type ProfileCreateMode = "blank" | "settings" | "all";

type ProfilesViewProps = {
  usersData: UserListItem[];
  usersLoading: boolean;
  refreshUsers: () => void;
  goToUsers: () => void;
  profileManagerUserIdValue: string;
  profileManagerUserLabel: string;
  openProfileManager: (userId: string) => void;
  userLabelFor: (userId: string) => string;
  profileManagerActiveProfiles: AgentProfile[];
  profileManagerDedicatedDiscordAccounts: TransportAccountItem[];
  profileManagerTotalBindings: number;
  profileManagerArchivedProfiles: AgentProfile[];
  profileManagerSharedDefaultDiscord: TransportAccountItem | null;
  profileManagerSharedDefaultEligibleProfiles: AgentProfile[];
  profileManagerSharedBindings: TransportBindingItem[];
  sharedDefaultBindingsExpanded: boolean;
  setSharedDefaultBindingsExpanded: Dispatch<SetStateAction<boolean>>;
  profileComposerOpen: boolean;
  setProfileComposerOpen: (open: boolean) => void;
  resetProfileCreateState: () => void;
  refreshProfileWorkspace: () => void;
  profileListTab: ProfileListTab;
  setProfileListTab: (value: ProfileListTab) => void;
  profileCreateName: string;
  setProfileCreateName: (value: string) => void;
  profileCreateSourceSlug: string;
  setProfileCreateSourceSlug: (value: string) => void;
  profileCreateMode: ProfileCreateMode;
  setProfileCreateMode: (value: ProfileCreateMode) => void;
  profileCreateMakeDefault: boolean;
  setProfileCreateMakeDefault: (value: boolean) => void;
  handleProfileCreate: () => void;
  profileSaving: boolean;
  profileManagerProfiles: AgentProfile[];
  profilesError: string | null;
  transportAccountsError: string | null;
  profilesLoading: boolean;
  profileManagerVisibleProfiles: AgentProfile[];
  profileActionLoading: Record<string, boolean>;
  explicitDiscordAccountForProfile: (userId: string, profileId: string) => TransportAccountItem | null;
  bindingsByAccountKey: Record<string, TransportBindingItem[]>;
  bindingDraftFor: (accountKey: string, fallbackProfileId?: string) => BindingDraft;
  setBindingDraftFor: (
    accountKey: string,
    updates: Partial<BindingDraft>,
    fallbackProfileId?: string
  ) => void;
  guildOptionsForAccount: (accountKey?: string | null) => GuildOption[];
  channelOptionsForAccount: (accountKey?: string | null, guildId?: string | null) => ChannelListItem[];
  bindingsLoadingByAccountKey: Record<string, boolean>;
  bindingModeLabel: (mode?: string | null) => string;
  channelLabelFor: (channelId: string, accountKey?: string | null) => string;
  profileLabelFor: (
    userId: string | null | undefined,
    profileId?: string | null,
    fallbackSlug?: string | null
  ) => string;
  isProfileSectionExpanded: (profile: AgentProfile) => boolean;
  toggleProfileSection: (profile: AgentProfile) => void;
  handleBindingCreate: (userId: string, account: TransportAccountItem, fallbackProfileId?: string) => Promise<void>;
  handleBindingUpdate: (
    userId: string,
    binding: TransportBindingItem,
    payload: Partial<{ mode: string; enabled: boolean; agent_profile_id: string }>
  ) => Promise<void>;
  handleBindingDelete: (userId: string, binding: TransportBindingItem) => Promise<void>;
  handleProfileArchiveToggle: (userId: string, profile: AgentProfile, archived: boolean) => Promise<void>;
  handleProfileDelete: (userId: string, profile: AgentProfile) => Promise<void>;
  handleProfileSetDefault: (userId: string, profile: AgentProfile) => Promise<void>;
  profileRenameDrafts: Record<string, string>;
  setProfileRenameDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  profileModelDrafts: Record<string, string>;
  setProfileModelDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  modelsLoading: boolean;
  availableModelSelectors: string[];
  handleProfileSettingsSave: (userId: string, profile: AgentProfile) => Promise<void>;
  transportDisplayNameDrafts: Record<string, string>;
  setTransportDisplayNameDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  transportTokenDrafts: Record<string, string>;
  setTransportTokenDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  handleTransportAccountEnabled: (userId: string, account: TransportAccountItem, enabled: boolean) => Promise<void>;
  transportActionLoading: Record<string, boolean>;
  handleTransportAccountSave: (userId: string, profile: AgentProfile) => Promise<void>;
  handleTransportAccountDelete: (userId: string, account: TransportAccountItem) => Promise<void>;
};

export function ProfilesView({
  usersData,
  usersLoading,
  refreshUsers,
  goToUsers,
  profileManagerUserIdValue,
  profileManagerUserLabel,
  openProfileManager,
  userLabelFor,
  profileManagerActiveProfiles,
  profileManagerDedicatedDiscordAccounts,
  profileManagerTotalBindings,
  profileManagerArchivedProfiles,
  profileManagerSharedDefaultDiscord,
  profileManagerSharedDefaultEligibleProfiles,
  profileManagerSharedBindings,
  sharedDefaultBindingsExpanded,
  setSharedDefaultBindingsExpanded,
  profileComposerOpen,
  setProfileComposerOpen,
  resetProfileCreateState,
  refreshProfileWorkspace,
  profileListTab,
  setProfileListTab,
  profileCreateName,
  setProfileCreateName,
  profileCreateSourceSlug,
  setProfileCreateSourceSlug,
  profileCreateMode,
  setProfileCreateMode,
  profileCreateMakeDefault,
  setProfileCreateMakeDefault,
  handleProfileCreate,
  profileSaving,
  profileManagerProfiles,
  profilesError,
  transportAccountsError,
  profilesLoading,
  profileManagerVisibleProfiles,
  profileActionLoading,
  explicitDiscordAccountForProfile,
  bindingsByAccountKey,
  bindingDraftFor,
  setBindingDraftFor,
  guildOptionsForAccount,
  channelOptionsForAccount,
  bindingsLoadingByAccountKey,
  bindingModeLabel,
  channelLabelFor,
  profileLabelFor,
  isProfileSectionExpanded,
  toggleProfileSection,
  handleBindingCreate,
  handleBindingUpdate,
  handleBindingDelete,
  handleProfileArchiveToggle,
  handleProfileDelete,
  handleProfileSetDefault,
  profileRenameDrafts,
  setProfileRenameDrafts,
  profileModelDrafts,
  setProfileModelDrafts,
  modelsLoading,
  availableModelSelectors,
  handleProfileSettingsSave,
  transportDisplayNameDrafts,
  setTransportDisplayNameDrafts,
  transportTokenDrafts,
  setTransportTokenDrafts,
  handleTransportAccountEnabled,
  transportActionLoading,
  handleTransportAccountSave,
  handleTransportAccountDelete,
}: ProfilesViewProps) {
  const renderBindingManager = ({
    userId,
    account,
    bindings,
    helperText,
    emptyText,
    selectableProfiles,
    fallbackProfileId,
    expanded = true,
    onToggleExpanded,
  }: {
    userId: string;
    account: TransportAccountItem;
    bindings: TransportBindingItem[];
    helperText: string;
    emptyText: string;
    selectableProfiles?: AgentProfile[];
    fallbackProfileId?: string;
    expanded?: boolean;
    onToggleExpanded?: () => void;
  }) => {
    const draft = bindingDraftFor(account.account_key, fallbackProfileId ?? "");
    const guildOptions = guildOptionsForAccount(account.account_key);
    const channelOptions = channelOptionsForAccount(account.account_key, draft.guild_id);
    const showProfileSelect = selectableProfiles !== undefined;
    const busy = Boolean(transportActionLoading[account.account_key]);
    const canCreateBinding = Boolean(draft.surface_id) && (!showProfileSelect || Boolean(draft.agent_profile_id));

    return (
      <BindingManager
        account={account}
        bindings={bindings}
        helperText={helperText}
        emptyText={emptyText}
        draft={draft}
        guildOptions={guildOptions}
        channelOptions={channelOptions}
        selectableProfiles={selectableProfiles}
        expanded={expanded}
        onToggleExpanded={onToggleExpanded}
        canCreateBinding={canCreateBinding}
        busy={busy}
        loading={Boolean(bindingsLoadingByAccountKey[account.account_key])}
        actionLoadingById={transportActionLoading}
        setDraft={(updates) => setBindingDraftFor(account.account_key, updates, fallbackProfileId ?? "")}
        onCreateBinding={() => {
          void handleBindingCreate(userId, account, fallbackProfileId);
        }}
        onUpdateBinding={(binding, payload) => {
          void handleBindingUpdate(userId, binding, payload);
        }}
        onDeleteBinding={(binding) => {
          void handleBindingDelete(userId, binding);
        }}
        channelLabelFor={channelLabelFor}
        bindingModeLabel={bindingModeLabel}
        profileLabelFor={profileLabelFor}
      />
    );
  };

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader className="gap-5">
          <SectionHeader
            title="Profiles"
            subtitle="Manage each user's agent profiles, dedicated Discord bots, and channel bindings without getting lost in the details."
          />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,360px)_1fr] xl:items-end">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">User</label>
              <Select
                value={profileManagerUserIdValue || usersData[0]?.id || "none"}
                onValueChange={(value) => {
                  if (value === "none") {
                    return;
                  }
                  openProfileManager(value);
                }}
                disabled={usersLoading && !usersData.length}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select user" />
                </SelectTrigger>
                <SelectContent>
                  {usersData.length ? (
                    usersData.map((user) => (
                      <SelectItem key={user.id} value={user.id}>
                        {userLabelFor(user.id)}
                      </SelectItem>
                    ))
                  ) : (
                    <SelectItem value="none">{usersLoading ? "Loading users..." : "No users available"}</SelectItem>
                  )}
                </SelectContent>
              </Select>
              <p className="text-xs text-mutedForeground">
                {profileManagerUserIdValue
                  ? `Currently managing ${profileManagerUserLabel} (${profileManagerUserIdValue}).`
                  : "Choose a user to start managing their profiles and Discord routing."}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <ProfileMetricCard
                icon={<Bot className="h-4 w-4" />}
                label="Active Profiles"
                value={profileManagerUserIdValue ? profileManagerActiveProfiles.length : "—"}
                hint="Profiles available for new sessions and client switching."
              />
              <ProfileMetricCard
                icon={<Cable className="h-4 w-4" />}
                label="Dedicated Bots"
                value={profileManagerUserIdValue ? profileManagerDedicatedDiscordAccounts.length : "—"}
                hint="Profiles with their own Discord token instead of the shared default bot."
              />
              <ProfileMetricCard
                icon={<Globe className="h-4 w-4" />}
                label="Bound Channels"
                value={profileManagerUserIdValue ? profileManagerTotalBindings : "—"}
                hint="Server channels currently routed to this user's bots."
              />
              <ProfileMetricCard
                icon={<Clock3 className="h-4 w-4" />}
                label="Archived"
                value={profileManagerUserIdValue ? profileManagerArchivedProfiles.length : "—"}
                hint="Profiles that are hidden from normal use but can still be restored."
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" onClick={refreshUsers} disabled={usersLoading}>
              {usersLoading ? "Refreshing users..." : "Refresh users"}
            </Button>
            <Button variant="outline" onClick={goToUsers}>
              View users
            </Button>
          </div>

          {!usersData.length ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
              {usersLoading ? "Loading users..." : "No users yet."}
            </div>
          ) : !profileManagerUserIdValue ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
              Select a user to open their profile workspace.
            </div>
          ) : (
            <div className="space-y-6">
              <Card>
                <CardHeader className="gap-4">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="max-w-3xl">
                      <CardTitle>Shared Default Discord Bot</CardTitle>
                      <CardDescription>
                        Profiles without a dedicated override use the shared bot from <code>config.yaml</code> for DMs and
                        any server channels you bind here.
                      </CardDescription>
                    </div>
                    {profileManagerSharedDefaultDiscord ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{profileManagerSharedDefaultDiscord.status}</Badge>
                        {profileManagerSharedDefaultDiscord.external_label ? (
                          <Badge variant="outline">{profileManagerSharedDefaultDiscord.external_label}</Badge>
                        ) : null}
                      </div>
                    ) : (
                      <Badge variant="outline">Disabled</Badge>
                    )}
                  </div>
                  {profileManagerSharedDefaultDiscord ? (
                    <div className="grid gap-3 lg:grid-cols-3">
                      <div className="rounded-2xl border border-border bg-muted/20 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                          Eligible profiles
                        </p>
                        <p className="mt-3 text-2xl font-semibold text-foreground">
                          {profileManagerSharedDefaultEligibleProfiles.length}
                        </p>
                        <p className="mt-2 text-xs text-mutedForeground">
                          Profiles that can still use the shared bot because they do not have a dedicated override.
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border bg-muted/20 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                          Bound channels
                        </p>
                        <p className="mt-3 text-2xl font-semibold text-foreground">{profileManagerSharedBindings.length}</p>
                        <p className="mt-2 text-xs text-mutedForeground">
                          Shared-bot server channels with explicit profile routing.
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border bg-muted/20 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                          Bot identity
                        </p>
                        <p className="mt-3 text-base font-semibold text-foreground">
                          {profileManagerSharedDefaultDiscord.external_label || "Connected bot"}
                        </p>
                        <p className="mt-2 text-xs text-mutedForeground">
                          This bot is shared across profiles that do not bring their own Discord token.
                        </p>
                      </div>
                    </div>
                  ) : null}
                </CardHeader>
                <CardContent className="space-y-4">
                  {profileManagerSharedDefaultDiscord ? (
                    <>
                      {!profileManagerSharedDefaultEligibleProfiles.length ? (
                        <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
                          Every active profile for this user already has its own dedicated Discord bot, so the shared
                          bot cannot be bound to additional channels for them.
                        </div>
                      ) : null}
                      {profileManagerSharedDefaultDiscord.last_error ? (
                        <div className="rounded-2xl border border-rose-200/70 bg-rose-500/5 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/50 dark:text-rose-300">
                          {profileManagerSharedDefaultDiscord.last_error}
                        </div>
                      ) : null}
                      {renderBindingManager({
                        userId: profileManagerUserIdValue,
                        account: profileManagerSharedDefaultDiscord,
                        bindings: profileManagerSharedBindings,
                        helperText:
                          "Use the shared bot for server channels when a profile does not need its own dedicated bot token.",
                        emptyText: "No server channels are bound to the shared default bot yet.",
                        selectableProfiles: profileManagerSharedDefaultEligibleProfiles,
                        expanded: sharedDefaultBindingsExpanded,
                        onToggleExpanded: () => setSharedDefaultBindingsExpanded((current) => !current),
                      })}
                    </>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
                      The shared default Discord bot is disabled or has no token configured in <code>config.yaml</code>.
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="gap-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <CardTitle>Profile Workspace</CardTitle>
                      <CardDescription>
                        Keep the working area focused on the profiles you are editing, and open the create flow only
                        when you need it.
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        variant={profileComposerOpen ? "secondary" : "default"}
                        onClick={() => {
                          if (profileComposerOpen) {
                            resetProfileCreateState();
                            return;
                          }
                          setProfileComposerOpen(true);
                        }}
                      >
                        <Plus className="mr-2 h-4 w-4" />
                        {profileComposerOpen ? "Hide add profile" : "Add profile"}
                      </Button>
                      <Button size="sm" variant="outline" onClick={refreshProfileWorkspace}>
                        <RefreshCcw className="mr-2 h-4 w-4" />
                        Refresh everything
                      </Button>
                    </div>
                  </div>
                  <Tabs value={profileListTab} onValueChange={(value) => setProfileListTab(value as ProfileListTab)}>
                    <TabsList>
                      <TabsTrigger value="active">Active</TabsTrigger>
                      <TabsTrigger value="archived">Archived</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </CardHeader>
                <CardContent className="space-y-4">
                  {profileComposerOpen ? (
                    <div className="rounded-3xl border border-border bg-muted/15 p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-base font-semibold text-foreground">Create or clone profile</p>
                          <p className="mt-1 text-sm text-mutedForeground">
                            Start from a clean workspace skeleton or copy another profile's setup without leaving this
                            page.
                          </p>
                        </div>
                        <Button size="sm" variant="ghost" onClick={resetProfileCreateState}>
                          Hide
                        </Button>
                      </div>
                      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(220px,0.8fr)_minmax(220px,0.8fr)]">
                        <div className="grid gap-2">
                          <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Profile name
                          </label>
                          <Input
                            value={profileCreateName}
                            onChange={(event) => setProfileCreateName(event.target.value)}
                            placeholder="Research Assistant"
                          />
                        </div>
                        <div className="grid gap-2">
                          <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Starting point
                          </label>
                          <Select
                            value={profileCreateSourceSlug}
                            onValueChange={(value) => {
                              setProfileCreateSourceSlug(value);
                              setProfileCreateMode(
                                value === "blank"
                                  ? "blank"
                                  : profileCreateMode === "blank"
                                    ? "settings"
                                    : profileCreateMode
                              );
                            }}
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Blank profile" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="blank">Blank profile</SelectItem>
                              {profileManagerProfiles.map((profile) => (
                                <SelectItem key={profile.id} value={profile.slug}>
                                  {profile.name} · {profile.slug}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="grid gap-2">
                          <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                            Clone mode
                          </label>
                          <Select
                            value={profileCreateMode}
                            onValueChange={(value) => setProfileCreateMode(value as ProfileCreateMode)}
                            disabled={profileCreateSourceSlug === "blank"}
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Blank" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="blank">Blank</SelectItem>
                              <SelectItem value="settings">Settings only</SelectItem>
                              <SelectItem value="all">Everything</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-background/70 px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Switch checked={profileCreateMakeDefault} onCheckedChange={setProfileCreateMakeDefault} />
                          <div>
                            <p className="text-sm font-semibold text-foreground">Make this the default profile</p>
                            <p className="text-xs text-mutedForeground">
                              New sessions and clients will fall back to it automatically.
                            </p>
                          </div>
                        </div>
                        <Button onClick={handleProfileCreate} disabled={profileSaving}>
                          {profileSaving
                            ? "Saving..."
                            : profileCreateSourceSlug === "blank"
                              ? "Create profile"
                              : "Clone profile"}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-border bg-muted/20 px-4 py-4">
                      <div>
                        <p className="text-sm font-semibold text-foreground">Create a new agent profile when you need one</p>
                        <p className="mt-1 text-sm text-mutedForeground">
                          Keep this page focused on active profiles, and open the add flow only when you are ready to
                          create or clone one.
                        </p>
                      </div>
                      <Button size="sm" onClick={() => setProfileComposerOpen(true)}>
                        <Plus className="mr-2 h-4 w-4" />
                        Add profile
                      </Button>
                    </div>
                  )}
                  {profilesError ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-4 text-sm text-mutedForeground">
                      {profilesError}
                    </div>
                  ) : null}
                  {transportAccountsError ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-4 text-sm text-mutedForeground">
                      {transportAccountsError}
                    </div>
                  ) : null}

                  {profilesLoading && !profileManagerProfiles.length ? (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      Loading profiles...
                    </div>
                  ) : profileManagerVisibleProfiles.length ? (
                    <div className="space-y-4">
                      {profileManagerVisibleProfiles.map((profile) => {
                        const loading = profileActionLoading[profile.id];
                        const dedicatedDiscord = explicitDiscordAccountForProfile(profileManagerUserIdValue, profile.id);
                        const dedicatedBindings = dedicatedDiscord ? bindingsByAccountKey[dedicatedDiscord.account_key] ?? [] : [];
                        const transportDraftKey = dedicatedDiscord?.account_key ?? profile.id;
                        const detailsExpanded = isProfileSectionExpanded(profile);

                        return (
                          <div key={profile.id} className="overflow-hidden rounded-2xl border border-border bg-muted/20">
                            <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-5">
                              <div className="space-y-3">
                                <div className="flex flex-wrap items-center gap-3">
                                  <span
                                    className={`h-2.5 w-2.5 rounded-full ${
                                      profile.status === "archived" ? "bg-amber-500" : "bg-emerald-500"
                                    }`}
                                  />
                                  <p className="text-base font-semibold text-foreground">{profile.name}</p>
                                  <Badge variant="outline">{profile.slug}</Badge>
                                  {profile.is_default ? <Badge variant="success">Default</Badge> : null}
                                  <Badge variant={profile.status === "archived" ? "warning" : "secondary"}>
                                    {profile.status}
                                  </Badge>
                                </div>
                                <div className="flex flex-wrap items-center gap-2 text-xs text-mutedForeground">
                                  <span>Created {formatRelativeTime(profile.created_at)}</span>
                                  <span>·</span>
                                  <span>Updated {formatRelativeTime(profile.updated_at)}</span>
                                  <span>·</span>
                                  <span>{dedicatedDiscord ? "Dedicated Discord bot" : "Shared Discord bot"}</span>
                                  <span>·</span>
                                  <span>
                                    {dedicatedDiscord ? dedicatedBindings.length : 0} dedicated channel
                                    {dedicatedDiscord && dedicatedBindings.length === 1 ? "" : "s"}
                                  </span>
                                </div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => toggleProfileSection(profile)}
                                  className="gap-2"
                                >
                                  {detailsExpanded ? (
                                    <ChevronDown className="h-4 w-4" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" />
                                  )}
                                  {detailsExpanded ? "Hide details" : "Show details"}
                                </Button>
                                {profile.status === "archived" ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => void handleProfileArchiveToggle(profileManagerUserIdValue, profile, false)}
                                      disabled={loading}
                                    >
                                      Restore
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="danger"
                                      onClick={() => void handleProfileDelete(profileManagerUserIdValue, profile)}
                                      disabled={loading}
                                    >
                                      Delete permanently
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    {!profile.is_default ? (
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void handleProfileSetDefault(profileManagerUserIdValue, profile)}
                                        disabled={loading}
                                      >
                                        Set default
                                      </Button>
                                    ) : null}
                                    <Button
                                      size="sm"
                                      variant="danger"
                                      onClick={() => void handleProfileArchiveToggle(profileManagerUserIdValue, profile, true)}
                                      disabled={loading || profile.is_default}
                                    >
                                      Archive
                                    </Button>
                                  </>
                                )}
                              </div>
                            </div>

                            {detailsExpanded ? (
                              <div className="border-t border-border/70 bg-background/60 px-5 py-5">
                                {profile.status === "archived" ? (
                                  <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
                                    Archived profiles are hidden from normal client use. Restore the profile to edit it
                                    again, or delete it permanently if it was only for testing.
                                  </div>
                                ) : (
                                  <div className="grid gap-4 2xl:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
                                    <div className="rounded-2xl border border-border bg-card p-4">
                                      <div className="space-y-4">
                                        <div>
                                          <p className="text-sm font-semibold text-foreground">Profile settings</p>
                                          <p className="mt-1 text-xs text-mutedForeground">
                                            Keep the profile name human-friendly. The slug stays stable for routing and
                                            workspace lookup.
                                          </p>
                                        </div>
                                        <div className="grid gap-2">
                                          <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                            Display name
                                          </label>
                                          <Input
                                            value={profileRenameDrafts[profile.id] ?? profile.name}
                                            onChange={(event) =>
                                              setProfileRenameDrafts((current) => ({
                                                ...current,
                                                [profile.id]: event.target.value,
                                              }))
                                            }
                                            disabled={loading}
                                          />
                                        </div>
                                        <div className="grid gap-2">
                                          <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                            Default model
                                          </label>
                                          <Select
                                            value={profileModelDrafts[profile.id] ?? (profile.default_model ?? "__default__")}
                                            onValueChange={(value) =>
                                              setProfileModelDrafts((current) => ({
                                                ...current,
                                                [profile.id]: value,
                                              }))
                                            }
                                            disabled={loading || modelsLoading}
                                          >
                                            <SelectTrigger>
                                              <SelectValue placeholder="Default (global)" />
                                            </SelectTrigger>
                                            <SelectContent>
                                              <SelectItem value="__default__">Default (global)</SelectItem>
                                              {availableModelSelectors.map((modelName) => (
                                                <SelectItem key={modelName} value={modelName}>
                                                  {modelName}
                                                </SelectItem>
                                              ))}
                                            </SelectContent>
                                          </Select>
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2">
                                          <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => void handleProfileSettingsSave(profileManagerUserIdValue, profile)}
                                            disabled={loading}
                                          >
                                            {loading ? "Saving..." : "Save settings"}
                                          </Button>
                                        </div>
                                        <div className="rounded-2xl border border-border bg-muted/20 px-4 py-3 text-xs text-mutedForeground">
                                          Workspace path and identity files stay with the profile slug. Changing the
                                          profile default model affects new sessions and profile-owned runs; existing
                                          sessions keep their current model.
                                        </div>
                                      </div>
                                    </div>

                                    <div className="space-y-4">
                                      <div className="rounded-2xl border border-border bg-card p-4">
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                          <div>
                                            <div className="flex flex-wrap items-center gap-2">
                                              <p className="text-sm font-semibold text-foreground">Dedicated Discord bot</p>
                                              {dedicatedDiscord ? (
                                                <>
                                                  <Badge variant={dedicatedDiscord.enabled ? "success" : "secondary"}>
                                                    {dedicatedDiscord.enabled ? "Enabled" : "Disabled"}
                                                  </Badge>
                                                  <Badge variant="secondary">{dedicatedDiscord.status}</Badge>
                                                </>
                                              ) : (
                                                <Badge variant="outline">Using shared default</Badge>
                                              )}
                                            </div>
                                            <p className="mt-2 text-xs text-mutedForeground">
                                              Give this profile its own token only when it needs to be exclusive on
                                              Discord or run in its own bound channels.
                                            </p>
                                            {dedicatedDiscord?.last_error ? (
                                              <p className="mt-2 text-xs text-danger">{dedicatedDiscord.last_error}</p>
                                            ) : null}
                                          </div>
                                        </div>
                                        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                                          <div className="grid gap-2">
                                            <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                              Bot label
                                            </label>
                                            <Input
                                              value={
                                                transportDisplayNameDrafts[transportDraftKey] ??
                                                dedicatedDiscord?.display_name ??
                                                `${profile.name} Discord`
                                              }
                                              onChange={(event) =>
                                                setTransportDisplayNameDrafts((current) => ({
                                                  ...current,
                                                  [transportDraftKey]: event.target.value,
                                                }))
                                              }
                                              placeholder={`${profile.name} Discord`}
                                            />
                                          </div>
                                          <div className="grid gap-2">
                                            <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                                              Bot token
                                            </label>
                                            <Input
                                              type="password"
                                              value={transportTokenDrafts[profile.id] ?? ""}
                                              onChange={(event) =>
                                                setTransportTokenDrafts((current) => ({
                                                  ...current,
                                                  [profile.id]: event.target.value,
                                                }))
                                              }
                                              placeholder={
                                                dedicatedDiscord
                                                  ? "Paste a new token to rotate it"
                                                  : "Discord bot token"
                                              }
                                            />
                                          </div>
                                        </div>
                                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                                          <p className="text-xs text-mutedForeground">
                                            {dedicatedDiscord
                                              ? "Rotate the token or disable the bot without losing the profile."
                                              : "Without a dedicated bot, this profile continues to use the shared default bot in DMs."}
                                          </p>
                                          <div className="flex flex-wrap items-center gap-2">
                                            {dedicatedDiscord ? (
                                              <>
                                                <div className="flex items-center gap-2 rounded-full border border-border bg-muted/20 px-3 py-1.5">
                                                  <span className="text-xs text-mutedForeground">Enabled</span>
                                                  <Switch
                                                    checked={dedicatedDiscord.enabled}
                                                    onCheckedChange={(value) =>
                                                      void handleTransportAccountEnabled(
                                                        profileManagerUserIdValue,
                                                        dedicatedDiscord,
                                                        value
                                                      )
                                                    }
                                                    disabled={transportActionLoading[dedicatedDiscord.account_key]}
                                                  />
                                                </div>
                                                <Button
                                                  size="sm"
                                                  variant="outline"
                                                  onClick={() => void handleTransportAccountSave(profileManagerUserIdValue, profile)}
                                                  disabled={transportActionLoading[dedicatedDiscord.account_key]}
                                                >
                                                  Save bot
                                                </Button>
                                                <Button
                                                  size="sm"
                                                  variant="danger"
                                                  onClick={() =>
                                                    void handleTransportAccountDelete(profileManagerUserIdValue, dedicatedDiscord)
                                                  }
                                                  disabled={transportActionLoading[dedicatedDiscord.account_key]}
                                                >
                                                  Remove bot
                                                </Button>
                                              </>
                                            ) : (
                                              <Button
                                                size="sm"
                                                onClick={() => void handleTransportAccountSave(profileManagerUserIdValue, profile)}
                                                disabled={transportActionLoading[transportDraftKey]}
                                              >
                                                Create dedicated bot
                                              </Button>
                                            )}
                                          </div>
                                        </div>
                                      </div>

                                      {dedicatedDiscord ? (
                                        renderBindingManager({
                                          userId: profileManagerUserIdValue,
                                          account: dedicatedDiscord,
                                          bindings: dedicatedBindings,
                                          helperText: "Only this profile will answer in the dedicated bot's bound channels.",
                                          emptyText: "No server channels are bound to this dedicated bot yet.",
                                          fallbackProfileId: profile.id,
                                        })
                                      ) : (
                                        <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
                                          This profile currently uses the shared default Discord bot. Bind public channels
                                          from the shared bot card, or create a dedicated bot if this profile needs its
                                          own Discord identity.
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                )}
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-6 text-sm text-mutedForeground">
                      {profileListTab === "archived" ? "No archived profiles for this user." : "No active profiles found for this user."}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
