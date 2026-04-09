import { SectionHeader } from "@/components/SectionHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StateMessage } from "@/features/admin/components/StateMessage";
import type { UserListItem } from "@/lib/types";

type UsersViewProps = {
  usersLoading: boolean;
  usersError: string | null;
  usersData: UserListItem[];
  userUpdating: Record<string, boolean>;
  refreshUsers: () => void;
  renderUser: (userId: string) => React.ReactNode;
  openProfileManager: (userId: string) => void;
  handleUserApproval: (userId: string, approved: boolean) => void;
  handleUserDeny: (userId: string) => void;
};

export function UsersView({
  usersLoading,
  usersError,
  usersData,
  userUpdating,
  refreshUsers,
  renderUser,
  openProfileManager,
  handleUserApproval,
  handleUserDeny,
}: UsersViewProps) {
  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <SectionHeader
            title="Users"
            subtitle="Approve new accounts and manage the agent profiles they own."
            actionLabel={usersLoading ? "Refreshing..." : "Refresh"}
            onAction={usersLoading ? undefined : refreshUsers}
          />
        </CardHeader>
        <CardContent className="space-y-4">
          {usersLoading ? (
            <StateMessage>Loading users...</StateMessage>
          ) : usersError ? (
            <StateMessage>{usersError}</StateMessage>
          ) : usersData.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Transport ID</TableHead>
                  <TableHead>Default profile</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usersData.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-semibold">{renderUser(user.id)}</TableCell>
                    <TableCell className="text-xs text-mutedForeground">{user.transport_user_id}</TableCell>
                    <TableCell className="text-mutedForeground">{user.default_profile_slug ?? "default"}</TableCell>
                    <TableCell>
                      <Badge variant={user.approved ? "success" : "warning"}>
                        {user.approved ? "Approved" : "Pending"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={() => openProfileManager(user.id)}>
                          Manage profiles
                        </Button>
                        {!user.approved ? (
                          <>
                            <Button
                              size="sm"
                              onClick={() => handleUserApproval(user.id, true)}
                              disabled={userUpdating[user.id]}
                            >
                              {userUpdating[user.id] ? "Approving..." : "Approve"}
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => handleUserDeny(user.id)}
                              disabled={userUpdating[user.id]}
                            >
                              {userUpdating[user.id] ? "Denying..." : "Deny"}
                            </Button>
                          </>
                        ) : (
                          <span className="text-xs text-mutedForeground">—</span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <StateMessage>No users yet.</StateMessage>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
