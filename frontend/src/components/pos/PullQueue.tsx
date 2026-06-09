import type { ProjectPullPublic, ProjectPullState } from "@/client/types.gen"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/** State filter value: a concrete state, or ALL for the unfiltered queue. */
export type PullStateFilter = ProjectPullState | "ALL"

export const PULL_STATE_FILTERS: PullStateFilter[] = [
  "PENDING",
  "SHORT",
  "FULFILLED",
  "CANCELLED",
  "ALL",
]

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
}: PullQueueProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <Select
          value={stateFilter}
          onValueChange={(v) => onStateFilterChange(v as PullStateFilter)}
        >
          <SelectTrigger className="w-44" aria-label="Filter by state">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PULL_STATE_FILTERS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {isAdmin ? (
          <Button type="button" onClick={onNew}>
            New pull
          </Button>
        ) : null}
      </div>

      {pulls.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No pulls for this filter.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Project</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-center">Lines</TableHead>
              <TableHead>State</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pulls.map((pull) => {
              const cancellable =
                isAdmin && (pull.state === "PENDING" || pull.state === "SHORT")
              return (
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
                      {pull.state}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => onSelect(pull)}
                      >
                        Open
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
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
