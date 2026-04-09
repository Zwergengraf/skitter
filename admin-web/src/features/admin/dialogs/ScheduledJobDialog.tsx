import type { Dispatch, SetStateAction } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  AgentProfile,
  ChannelListItem,
  ScheduledJobItem,
  TransportAccountItem,
  UserListItem,
} from "@/lib/types";

type JobFormState = {
  user_id: string;
  user_label: string;
  agent_profile_id: string;
  channel_id: string;
  channel_label: string;
  target_transport_account_key: string;
  name: string;
  prompt: string;
  model: string;
  schedule_type: string;
  schedule_expr: string;
  schedule_date: string;
  schedule_time: string;
  enabled: boolean;
};

type ScheduledJobDialogProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  editingJob: ScheduledJobItem | null;
  directoryError: string | null;
  jobForm: JobFormState;
  setJobForm: Dispatch<SetStateAction<JobFormState>>;
  availableModelSelectors: string[];
  mainModelLabelValue: string;
  buildDateSchedule: (date: string, time: string) => string;
  usersData: UserListItem[];
  resolveUserId: (value: string, fallback: string) => string;
  userLabelFor: (userId: string) => string;
  activeProfilesForUser: (userId: string) => AgentProfile[];
  explicitDiscordAccountForProfile: (
    userId: string | null | undefined,
    profileId: string | null | undefined
  ) => TransportAccountItem | undefined;
  sharedDefaultDiscordAccount: (userId: string | null | undefined) => TransportAccountItem | undefined;
  channelOptionsForAccount: (accountKey?: string | null, guildId?: string | null) => ChannelListItem[];
  resolveChannelId: (value: string, fallback: string, accountKey?: string | null) => string;
  channelLabelFor: (channelId: string, accountKey?: string | null) => string;
  saveJob: () => void;
  jobSaving: boolean;
};

export function ScheduledJobDialog({
  open,
  setOpen,
  editingJob,
  directoryError,
  jobForm,
  setJobForm,
  availableModelSelectors,
  mainModelLabelValue,
  buildDateSchedule,
  usersData,
  resolveUserId,
  userLabelFor,
  activeProfilesForUser,
  explicitDiscordAccountForProfile,
  sharedDefaultDiscordAccount,
  channelOptionsForAccount,
  resolveChannelId,
  channelLabelFor,
  saveJob,
  jobSaving,
}: ScheduledJobDialogProps) {
  const availableTransportAccounts = (() => {
    const dedicated = explicitDiscordAccountForProfile(jobForm.user_id, jobForm.agent_profile_id);
    const shared = sharedDefaultDiscordAccount(jobForm.user_id);
    return dedicated ? [dedicated] : shared ? [shared] : [];
  })();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editingJob ? "Edit job" : "New scheduled job"}</DialogTitle>
          <DialogDescription>Use cron format for recurring runs, or choose one-shot date.</DialogDescription>
        </DialogHeader>
        {directoryError ? (
          <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-3 text-sm text-mutedForeground">
            {directoryError}
          </div>
        ) : null}
        <div className="grid gap-4">
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Name</label>
            <Input
              value={jobForm.name}
              onChange={(event) => setJobForm((prev) => ({ ...prev, name: event.target.value }))}
              placeholder="Morning news brief"
            />
          </div>
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Prompt</label>
            <Textarea
              value={jobForm.prompt}
              onChange={(event) => setJobForm((prev) => ({ ...prev, prompt: event.target.value }))}
              placeholder="Summarize the latest AI news and send it to me."
            />
          </div>
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Model</label>
            <Select value={jobForm.model} onValueChange={(value) => setJobForm((prev) => ({ ...prev, model: value }))}>
              <SelectTrigger>
                <SelectValue placeholder="Select model" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={mainModelLabelValue}>Main model chain (dynamic)</SelectItem>
                {availableModelSelectors.map((selector) => (
                  <SelectItem key={`scheduled-job-model-${selector}`} value={selector}>
                    {selector}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-mutedForeground">
              Main model chain is resolved when the job runs, so future config changes apply automatically.
            </p>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                Schedule type
              </label>
              <Select
                value={jobForm.schedule_type}
                onValueChange={(value) => setJobForm((prev) => ({ ...prev, schedule_type: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="cron" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="cron">Cron</SelectItem>
                  <SelectItem value="date">One-shot date</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              {jobForm.schedule_type === "date" ? (
                <>
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Run at
                  </label>
                  <div className="grid gap-2 md:grid-cols-2">
                    <Input
                      type="date"
                      value={jobForm.schedule_date}
                      onChange={(event) =>
                        setJobForm((prev) => {
                          const date = event.target.value;
                          return {
                            ...prev,
                            schedule_date: date,
                            schedule_expr: buildDateSchedule(date, prev.schedule_time),
                          };
                        })
                      }
                    />
                    <Input
                      type="time"
                      value={jobForm.schedule_time}
                      onChange={(event) =>
                        setJobForm((prev) => {
                          const time = event.target.value;
                          return {
                            ...prev,
                            schedule_time: time,
                            schedule_expr: buildDateSchedule(prev.schedule_date, time),
                          };
                        })
                      }
                    />
                  </div>
                </>
              ) : (
                <>
                  <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                    Cron expression
                  </label>
                  <Input
                    value={jobForm.schedule_expr}
                    onChange={(event) => setJobForm((prev) => ({ ...prev, schedule_expr: event.target.value }))}
                    placeholder="0 9 * * *"
                  />
                </>
              )}
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">User</label>
              <Input
                list="skitter-users"
                value={jobForm.user_label}
                onChange={(event) =>
                  setJobForm((prev) => {
                    const value = event.target.value;
                    return {
                      ...prev,
                      user_label: value,
                      user_id: value ? resolveUserId(value, prev.user_id) : "",
                    };
                  })
                }
                placeholder="Select a user"
              />
              <datalist id="skitter-users">
                {usersData.map((user) => (
                  <option
                    key={user.id}
                    value={`@${user.display_name ?? user.username ?? user.transport_user_id}`}
                    label={user.transport_user_id}
                  />
                ))}
              </datalist>
              <p className="text-xs text-mutedForeground">
                {jobForm.user_id
                  ? `Selected: ${userLabelFor(jobForm.user_id)} (${jobForm.user_id})`
                  : "Type to search by name or paste a user id."}
              </p>
            </div>
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Profile</label>
              <Select
                value={jobForm.agent_profile_id}
                onValueChange={(value) =>
                  setJobForm((prev) => ({
                    ...prev,
                    agent_profile_id: value,
                    channel_id: "",
                    channel_label: "",
                  }))
                }
                disabled={!jobForm.user_id}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select profile" />
                </SelectTrigger>
                <SelectContent>
                  {activeProfilesForUser(jobForm.user_id).map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name} · {profile.slug}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">
                Discord bot
              </label>
              <Select
                value={jobForm.target_transport_account_key}
                onValueChange={(value) =>
                  setJobForm((prev) => ({
                    ...prev,
                    target_transport_account_key: value,
                    channel_id: "",
                    channel_label: "",
                  }))
                }
                disabled={!jobForm.user_id}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select Discord bot" />
                </SelectTrigger>
                <SelectContent>
                  {availableTransportAccounts.map((account) => (
                    <SelectItem key={account.account_key} value={account.account_key}>
                      {account.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-mutedForeground">
                Profiles with dedicated Discord bots must use that bot for scheduled delivery.
              </p>
            </div>
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Channel</label>
              <Input
                list="skitter-channels"
                value={jobForm.channel_label}
                onChange={(event) =>
                  setJobForm((prev) => {
                    const value = event.target.value;
                    return {
                      ...prev,
                      channel_label: value,
                      channel_id: value
                        ? resolveChannelId(value, prev.channel_id, prev.target_transport_account_key)
                        : "",
                    };
                  })
                }
                placeholder="Select a channel"
              />
              <datalist id="skitter-channels">
                {channelOptionsForAccount(jobForm.target_transport_account_key).map((channel) => (
                  <option key={channel.id} value={channel.label} label={channel.id} />
                ))}
              </datalist>
              <p className="text-xs text-mutedForeground">
                {jobForm.channel_id
                  ? `Selected: ${channelLabelFor(jobForm.channel_id, jobForm.target_transport_account_key)} (${jobForm.channel_id})`
                  : "Type to search by label or paste a channel id."}
              </p>
            </div>
          </div>
          <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3">
            <div>
              <p className="text-sm font-semibold">Job enabled</p>
              <p className="text-xs text-mutedForeground">Pause without deleting.</p>
            </div>
            <Switch
              checked={jobForm.enabled}
              onCheckedChange={(value) => setJobForm((prev) => ({ ...prev, enabled: value }))}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={saveJob} disabled={jobSaving}>
            {jobSaving ? "Saving..." : editingJob ? "Save changes" : "Create job"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
