import { ClipboardList } from "lucide-react"

import type { ProjectPullPublic, ProjectPullState } from "@/client/types.gen"
import { LIST_SCROLL, ListShell } from "@/components/Common/ListShell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useIsMobile } from "@/hooks/useMobile"

/** State filter value: a concrete state, or ALL for the unfiltered queue. */
export type PullStateFilter = ProjectPullState | "ALL"

interface PullQueueProps {
  pulls: ProjectPullPublic[]
  /** project_id -> "Name (CODE)" label. */
  projectLabels: Map<string, string>
  /** customer_id -> name. */
  customerLabels: Map<string, string>
  stateFilter: PullStateFilter
  isAdmin: boolean
  onStateFilterChange: (value: PullStateFilter) => void
  onSelect: (pull: ProjectPullPublic) => void
  onCancel: (pullId: string) => void
  onNew: () => void
  /** Disables actions while a cancel is in flight. */
  isCancelling: boolean
  /** A page/filter fetch is in flight while the current rows stay on screen. */
  loading?: boolean
}

const STATE_VARIANT: Record<
  ProjectPullState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  PENDING: "secondary",
  FULFILLED: "default",
  SHORT: "destructive",
  CANCELLED: "outline",
}

const STATE_LABEL: Record<ProjectPullState, string> = {
  PENDING: "Waiting",
  FULFILLED: "Done",
  SHORT: "Short",
  CANCELLED: "Cancelled",
}

/** Open / Cancel buttons for one pull, shared by the desktop row and mobile card. */
function PullActions({
  pull,
  isAdmin,
  isCancelling,
  onSelect,
  onCancel,
}: Pick<
  PullQueueProps,
  "isAdmin" | "isCancelling" | "onSelect" | "onCancel"
> & { pull: ProjectPullPublic }) {
  const cancellable =
    isAdmin && (pull.state === "PENDING" || pull.state === "SHORT")
  return (
    <div className="flex justify-end gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onSelect(pull)}
      >
        Give out parts
      </Button>
      {cancellable ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-destructive"
          disabled={isCancelling}
          onClick={() => onCancel(pull.id)}
        >
          Cancel
        </Button>
      ) : null}
    </div>
  )
}

export function PullQueue({
  pulls,
  projectLabels,
  customerLabels,
  stateFilter,
  isAdmin,
  onStateFilterChange,
  onSelect,
  onCancel,
  onNew,
  isCancelling,
  loading = false,
}: PullQueueProps) {
  const isMobile = useIsMobile()
  return (
    <div className="space-y-4">
      <Alert>
        <ClipboardList />
        <AlertTitle>Stock requests waiting</AlertTitle>
        <AlertDescription>
          These are parts requested for projects. Tap “Give out parts” on a
          request, then scan each part to hand it out.{" "}
          {isAdmin ? "Use “New request” to raise one." : null}
        </AlertDescription>
      </Alert>

      <div className="flex items-center justify-between gap-4">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-pressed={stateFilter === "PENDING"}
          onClick={() =>
            onStateFilterChange(stateFilter === "PENDING" ? "ALL" : "PENDING")
          }
        >
          {stateFilter === "PENDING"
            ? "Show all (incl. completed)"
            : "Show only waiting"}
        </Button>

        {isAdmin ? (
          <Button type="button" onClick={onNew}>
            New request
          </Button>
        ) : null}
      </div>

      {pulls.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No requests to show.
        </p>
      ) : isMobile ? (
        <ListShell loading={loading}>
          <div className="space-y-3">
            {pulls.map((pull) => (
              <div key={pull.id} className="bg-card rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {projectLabels.get(pull.project_id) ?? pull.project_id}
                    </p>
                    <p className="text-muted-foreground truncate text-sm">
                      {customerLabels.get(pull.customer_id) ?? pull.customer_id}
                    </p>
                  </div>
                  <Badge variant={STATE_VARIANT[pull.state]}>
                    {STATE_LABEL[pull.state]}
                  </Badge>
                </div>
                <div className="text-muted-foreground mt-2 flex items-center gap-3 text-xs">
                  <span className="num">
                    {new Date(pull.created_at).toLocaleDateString()}
                  </span>
                  <span>
                    {pull.lines.length}{" "}
                    {pull.lines.length === 1 ? "item" : "items"} needed
                  </span>
                </div>
                <div className="mt-3 border-t pt-3">
                  <PullActions
                    pull={pull}
                    isAdmin={isAdmin}
                    isCancelling={isCancelling}
                    onSelect={onSelect}
                    onCancel={onCancel}
                  />
                </div>
              </div>
            ))}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={loading}>
          <Table containerClassName={LIST_SCROLL}>
            <TableHeader className="bg-background sticky top-0 z-10">
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-center">Items</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pulls.map((pull) => (
                <TableRow key={pull.id}>
                  <TableCell className="font-medium">
                    {projectLabels.get(pull.project_id) ?? pull.project_id}
                  </TableCell>
                  <TableCell>
                    {customerLabels.get(pull.customer_id) ?? pull.customer_id}
                  </TableCell>
                  <TableCell className="num text-xs">
                    {new Date(pull.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="num text-center">
                    {pull.lines.length}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATE_VARIANT[pull.state]}>
                      {STATE_LABEL[pull.state]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <PullActions
                      pull={pull}
                      isAdmin={isAdmin}
                      isCancelling={isCancelling}
                      onSelect={onSelect}
                      onCancel={onCancel}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ListShell>
      )}
    </div>
  )
}
