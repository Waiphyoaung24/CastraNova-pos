import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Users } from "lucide-react"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { UserActionsMenu } from "@/components/Admin/UserActionsMenu"
import { DataTable } from "@/components/Common/DataTable"
import { PageHeader } from "@/components/Common/PageHeader"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import useAuth from "@/hooks/useAuth"
import { tierLabel } from "@/hooks/useRole"
import { useIsMobile } from "@/hooks/useMobile"
import { requireAdmin } from "@/lib/route-guards"
import { cn } from "@/lib/utils"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    queryKey: ["users"],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [
      {
        title: "Admin · CASTRA NOVA",
      },
    ],
  }),
})

/** Mobile presentation of one user row: the desktop table can't fit Full
 * name / Email / Role / Status / actions on a phone without horizontal scroll. */
function UserCard({ user }: { user: UserTableData }) {
  return (
    <div className="bg-card rounded-lg border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "font-medium",
                !user.full_name && "text-muted-foreground",
              )}
            >
              {user.full_name || "N/A"}
            </span>
            {user.isCurrentUser && (
              <Badge variant="outline" className="text-xs">
                You
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground truncate text-sm">{user.email}</p>
        </div>
        <UserActionsMenu user={user} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 border-t pt-3">
        <Badge variant={tierLabel(user) === "Staff" ? "secondary" : "default"}>
          {tierLabel(user)}
        </Badge>
        <div className="flex items-center gap-2 text-sm">
          <span
            className={cn(
              "size-2 rounded-full",
              user.is_active ? "bg-green-500" : "bg-gray-400",
            )}
          />
          <span className={user.is_active ? "" : "text-muted-foreground"}>
            {user.is_active ? "Active" : "Inactive"}
          </span>
        </div>
      </div>
    </div>
  )
}

function UsersTableContent() {
  const isMobile = useIsMobile()
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  if (isMobile) {
    return tableData.length === 0 ? (
      <p className="text-muted-foreground py-6 text-center text-sm">
        No results found.
      </p>
    ) : (
      <div className="space-y-3">
        {tableData.map((user) => (
          <UserCard key={user.id} user={user} />
        ))}
      </div>
    )
  }

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Manage user accounts and permissions"
        actions={<AddUser />}
      />

      <Alert>
        <Users />
        <AlertTitle>Manage who has access</AlertTitle>
        <AlertDescription>
          Add teammates with Add User and set each one's role — Superusers
          manage users and see financial reports; staff get day-to-day POS
          access. Use the row menu to edit or deactivate an account. Every
          user's stock actions stay traceable in the Audit ledger.
        </AlertDescription>
      </Alert>

      <UsersTable />
    </div>
  )
}
