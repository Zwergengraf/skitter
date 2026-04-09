import { ChevronDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { BindingDraft, GuildOption } from "@/features/admin/types";
import type { AgentProfile, ChannelListItem, TransportAccountItem, TransportBindingItem } from "@/lib/types";

type BindingManagerProps = {
  account: TransportAccountItem;
  bindings: TransportBindingItem[];
  helperText: string;
  emptyText: string;
  draft: BindingDraft;
  guildOptions: GuildOption[];
  channelOptions: ChannelListItem[];
  selectableProfiles?: AgentProfile[];
  expanded?: boolean;
  onToggleExpanded?: () => void;
  canCreateBinding: boolean;
  busy: boolean;
  loading: boolean;
  actionLoadingById: Record<string, boolean>;
  setDraft: (updates: Partial<BindingDraft>) => void;
  onCreateBinding: () => void;
  onUpdateBinding: (
    binding: TransportBindingItem,
    payload: Partial<{ mode: string; enabled: boolean; agent_profile_id: string }>
  ) => void;
  onDeleteBinding: (binding: TransportBindingItem) => void;
  channelLabelFor: (channelId: string, accountKey?: string | null) => string;
  bindingModeLabel: (mode?: string | null) => string;
  profileLabelFor: (
    userId: string | null | undefined,
    profileId?: string | null,
    fallbackSlug?: string | null
  ) => string;
};

export function BindingManager({
  account,
  bindings,
  helperText,
  emptyText,
  draft,
  guildOptions,
  channelOptions,
  selectableProfiles,
  expanded = true,
  onToggleExpanded,
  canCreateBinding,
  busy,
  loading,
  actionLoadingById,
  setDraft,
  onCreateBinding,
  onUpdateBinding,
  onDeleteBinding,
  channelLabelFor,
  bindingModeLabel,
  profileLabelFor,
}: BindingManagerProps) {
  const showProfileSelect = selectableProfiles !== undefined;
  const bindingCount = bindings.length;

  return (
    <div className="rounded-2xl border border-border bg-muted/20">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 px-4 py-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-foreground">Server channel bindings</p>
            <Badge variant="outline">{bindingCount} active</Badge>
          </div>
          <p className="text-xs leading-relaxed text-mutedForeground">{helperText}</p>
        </div>
        {onToggleExpanded ? (
          <Button size="sm" variant="ghost" onClick={onToggleExpanded} className="gap-2">
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            {expanded ? "Hide channels" : "Show channels"}
          </Button>
        ) : null}
      </div>
      {expanded ? (
        <div className="space-y-4 p-4">
          <div className="rounded-2xl border border-border bg-card p-4">
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  Server
                </label>
                <Select
                  value={draft.guild_id}
                  onValueChange={(value) =>
                    setDraft({
                      guild_id: value,
                      surface_id: "",
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a Discord server" />
                  </SelectTrigger>
                  <SelectContent>
                    {guildOptions.length ? (
                      guildOptions.map((guild) => (
                        <SelectItem key={guild.guild_id} value={guild.guild_id}>
                          {guild.guild_name}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__none__" disabled>
                        No servers discovered yet
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  Channel
                </label>
                <Select
                  value={draft.surface_id}
                  onValueChange={(value) =>
                    setDraft({
                      surface_id: value,
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={draft.guild_id ? "Choose a channel" : "Select a server first"} />
                  </SelectTrigger>
                  <SelectContent>
                    {channelOptions.length ? (
                      channelOptions.map((channel) => (
                        <SelectItem key={channel.id} value={channel.id}>
                          {channel.label}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__none__" disabled>
                        {draft.guild_id ? "No channels found for this server" : "Select a server first"}
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              {showProfileSelect ? (
                <div className="grid gap-2">
                  <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Profile
                  </label>
                  <Select
                    value={draft.agent_profile_id}
                    onValueChange={(value) =>
                      setDraft({
                        agent_profile_id: value,
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a profile" />
                    </SelectTrigger>
                    <SelectContent>
                      {(selectableProfiles ?? []).length ? (
                        (selectableProfiles ?? []).map((profile) => (
                          <SelectItem key={profile.id} value={profile.id}>
                            {profile.name} · {profile.slug}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="__none__" disabled>
                          No eligible profiles available
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
              <div className="grid gap-2">
                <label className="text-[11px] font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                  Trigger mode
                </label>
                <Select
                  value={draft.mode}
                  onValueChange={(value) =>
                    setDraft({
                      mode: value,
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a trigger mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mention_only">Mentions only</SelectItem>
                    <SelectItem value="all_messages">All messages</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-mutedForeground">
                {showProfileSelect
                  ? "Use the shared bot for profiles that do not have their own dedicated Discord override."
                  : "This dedicated bot only handles the channels bound here."}
              </p>
              <Button size="sm" onClick={onCreateBinding} disabled={busy || !canCreateBinding}>
                Bind channel
              </Button>
            </div>
          </div>

          {loading ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
              Loading channel bindings...
            </div>
          ) : bindingCount ? (
            <div className="space-y-3">
              {bindings.map((binding) => (
                <div
                  key={binding.id}
                  className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-border bg-card px-4 py-4"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-foreground">
                      {channelLabelFor(binding.surface_id, binding.transport_account_key)}
                    </p>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-mutedForeground">
                      <span>{bindingModeLabel(binding.mode)}</span>
                      {showProfileSelect ? (
                        <>
                          <span>·</span>
                          <span>
                            Profile {profileLabelFor(binding.user_id, binding.agent_profile_id, binding.agent_profile_slug)}
                          </span>
                        </>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={binding.mode === "all_messages" ? "warning" : "secondary"}>
                      {bindingModeLabel(binding.mode)}
                    </Badge>
                    <div className="flex items-center gap-2 rounded-full border border-border bg-muted/30 px-3 py-1.5">
                      <span className="text-xs text-mutedForeground">Enabled</span>
                      <Switch
                        checked={binding.enabled}
                        onCheckedChange={(value) =>
                          onUpdateBinding(binding, {
                            enabled: value,
                          })
                        }
                        disabled={Boolean(actionLoadingById[binding.id])}
                      />
                    </div>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => onDeleteBinding(binding)}
                      disabled={Boolean(actionLoadingById[binding.id])}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-border bg-muted/30 px-4 py-4 text-sm text-mutedForeground">
              {emptyText}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
