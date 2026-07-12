import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Users } from "lucide-react"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { TierBadge } from "@/components/Admin/TierBadge"
import { UserActionsMenu } from "@/components/Admin/UserActionsMenu"
import { DataTable } from "@/components/Common/DataTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import useAuth from "@/hooks/useAuth"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { requireSuperuser } from "@/lib/route-guards"
import { cn } from "@/lib/utils"

function getUsersQueryOptions(skip: number, limit: number) {
  return {
    queryFn: () => UsersService.readUsers({ skip, limit }),
    queryKey: ["users", skip, limit],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: () => requireSuperuser(),
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
        <TierBadge user={user} />
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
  const pagination = usePagination()
  const { data: users } = useSuspenseQuery(
    getUsersQueryOptions(pagination.skip, pagination.limit),
  )

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  if (isMobile) {
    return (
      <>
        {tableData.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No results found.
          </p>
        ) : (
          <div className="space-y-3">
            {tableData.map((user) => (
              <UserCard key={user.id} user={user} />
            ))}
          </div>
        )}
        <PaginationControls
          total={users.count}
          pageSize={pagination.pageSize}
          page={pagination.page}
          onPageChange={pagination.setPage}
        />
      </>
    )
  }

  return (
    <DataTable
      columns={columns}
      data={tableData}
      manualPagination={{
        pageCount: pagination.pageCount(users.count),
        pageIndex: pagination.page - 1,
        pageSize: pagination.pageSize,
        total: users.count,
        onPageChange: (pageIndex) => pagination.setPage(pageIndex + 1),
      }}
    />
  )
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
          Add teammates with Add User and pick a role — Admins see financial
          reports, overrides, and config; Staff get day-to-day POS access. Only
          Superusers (the primary account) manage user accounts. Use the row
          menu to edit or deactivate an account. Every user's stock actions stay
          traceable in the Audit ledger.
        </AlertDescription>
      </Alert>

      <UsersTable />
    </div>
  )
}
