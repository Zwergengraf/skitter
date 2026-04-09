import { SectionHeader } from "@/components/SectionHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StateMessage } from "@/features/admin/components/StateMessage";
import type { AgentProfile, MemoryEntry, UserListItem } from "@/lib/types";
import { formatRelativeTime } from "@/lib/utils";

type MemoryViewProps = {
  memoryReindexing: boolean;
  handleMemoryReindex: () => void;
  usersData: UserListItem[];
  memoryUserId: string;
  setMemoryUserId: (value: string) => void;
  memoryProfileId: string;
  setMemoryProfileId: (value: string) => void;
  memoryProfiles: AgentProfile[];
  profilesLoadingByUserId: Record<string, boolean>;
  setMemoryData: (value: MemoryEntry[]) => void;
  setMemoryError: (value: string) => void;
  setSelectedMemory: (value: MemoryEntry | null) => void;
  setMemoryDetailContent: (value: string) => void;
  memoryLoading: boolean;
  memoryError: string | null;
  memoryData: MemoryEntry[];
  selectedMemory: MemoryEntry | null;
  memoryDetailLoading: boolean;
  memoryDetailContent: string;
  userLabelFor: (userId: string) => string;
};

export function MemoryView({
  memoryReindexing,
  handleMemoryReindex,
  usersData,
  memoryUserId,
  setMemoryUserId,
  memoryProfileId,
  setMemoryProfileId,
  memoryProfiles,
  profilesLoadingByUserId,
  setMemoryData,
  setMemoryError,
  setSelectedMemory,
  setMemoryDetailContent,
  memoryLoading,
  memoryError,
  memoryData,
  selectedMemory,
  memoryDetailLoading,
  memoryDetailContent,
  userLabelFor,
}: MemoryViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader
            title="Memory vault"
            subtitle="Summaries indexed from session handoffs."
            actionLabel={memoryReindexing ? "Reindexing..." : "Reindex"}
            onAction={memoryReindexing ? undefined : handleMemoryReindex}
          />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">User</label>
              <Select
                value={memoryUserId || usersData[0]?.id || "none"}
                onValueChange={(value) => {
                  if (value === "none") {
                    setMemoryUserId("");
                    setMemoryProfileId("");
                    setMemoryData([]);
                    setMemoryError("No user selected for memory.");
                    setSelectedMemory(null);
                    return;
                  }
                  setMemoryUserId(value);
                  setMemoryProfileId("");
                  setSelectedMemory(null);
                  setMemoryDetailContent("");
                }}
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
                    <SelectItem value="none">No users available</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Profile</label>
              <Select
                value={memoryProfileId || "loading"}
                onValueChange={(value) => {
                  if (value === "loading") {
                    return;
                  }
                  setMemoryProfileId(value);
                  setSelectedMemory(null);
                  setMemoryDetailContent("");
                }}
                disabled={!memoryUserId || profilesLoadingByUserId[memoryUserId] || !memoryProfiles.length}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select profile" />
                </SelectTrigger>
                <SelectContent>
                  {memoryProfiles.length ? (
                    memoryProfiles.map((profile) => (
                      <SelectItem key={profile.id} value={profile.id}>
                        {profile.name} · {profile.slug}
                      </SelectItem>
                    ))
                  ) : (
                    <SelectItem value="loading">
                      {profilesLoadingByUserId[memoryUserId] ? "Loading profiles..." : "No active profiles"}
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
              <p className="text-xs text-mutedForeground">Memory files are isolated per profile workspace.</p>
            </div>
          </div>

          {memoryLoading ? (
            <StateMessage>Loading memory...</StateMessage>
          ) : memoryError ? (
            <StateMessage>{memoryError}</StateMessage>
          ) : memoryData.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Sessions</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {memoryData.map((row) => (
                  <TableRow key={row.id} className="cursor-pointer" onClick={() => setSelectedMemory(row)}>
                    <TableCell className="font-semibold">
                      <div className="min-w-[200px] whitespace-nowrap">{row.source ?? "unknown"}</div>
                    </TableCell>
                    <TableCell className="text-xs text-mutedForeground">
                      {row.session_ids?.length ? row.session_ids.join(", ") : "—"}
                    </TableCell>
                    <TableCell className="text-mutedForeground">
                      <div className="whitespace-nowrap">{formatRelativeTime(row.created_at)}</div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <StateMessage>No memory entries yet.</StateMessage>
          )}
        </CardContent>
      </Card>
      <Dialog open={!!selectedMemory} onOpenChange={(open) => !open && setSelectedMemory(null)}>
        <DialogContent className="max-w-4xl w-[90vw]">
          <DialogHeader>
            <DialogTitle>Memory detail</DialogTitle>
            <DialogDescription>
              Source: {selectedMemory?.source ?? "unknown"} · Sessions:{" "}
              {selectedMemory?.session_ids?.length ? selectedMemory.session_ids.join(", ") : "—"}
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="h-[420px] rounded-2xl border border-border bg-card p-4">
            <p className="whitespace-pre-wrap text-sm text-foreground">
              {memoryDetailLoading ? "Loading..." : memoryDetailContent}
            </p>
          </ScrollArea>
          <div className="flex justify-end">
            <Button variant="outline" onClick={() => setSelectedMemory(null)}>
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
