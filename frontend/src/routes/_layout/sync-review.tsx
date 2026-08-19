import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { RefreshCw } from "lucide-react"
import { useState } from "react"

import { SyncReviewService, type SyncReviewState } from "@/client"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { requireAdmin } from "@/lib/route-guards"
import { isResolvable } from "@/lib/sync-review"

// Admin-only offline sync-review queue (§6.7). STALE/CONFLICT mutations that
// could not auto-apply land here for an admin to triage. Triage is status-only:
// discarding clears the item from the queue, it never replays the payload.
export const Route = createFileRoute("/_layout/sync-review")({
  component: SyncReview,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Sync review - CastraNova POS" }],
  }),
})

const STATES: SyncReviewState[] = ["PENDING", "DISCARDED"]

// Column widths in header order (When, Mutation, Reason, Actions); sum to 100%.
const SYNC_REVIEW_WIDTHS = ["22%", "28%", "24%", "26%"]

function SyncReview() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const [state, setState] = useState<SyncReviewState>("PENDING")

  const {
    data,
    isPending: isLoading,
    isPlaceholderData,
    isFetching,
    isError,
  } = useQuery({
    queryKey: ["sync-review", state],
    // Review queue reads the full bounded window (backend caps at 500) — no pagination UI yet.
    queryFn: () => SyncReviewService.listSyncReviewItems({ state, limit: 500 }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching

  const discardMutation = useMutation({
    mutationFn: (itemId: string) =>
      SyncReviewService.resolveSyncReviewItem({
        itemId,
        requestBody: { state: "DISCARDED" },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-review"] })
      showSuccessToast("Item discarded.")
    },
    onError: () => showErrorToast("Could not discard the item. Try again."),
  })

  const rows = data ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Sync review"
        description="Offline mutations that failed to replay and need admin triage."
      />

      <Alert>
        <RefreshCw />
        <AlertTitle>Review offline conflicts</AlertTitle>
        <AlertDescription>
          Actions taken offline that clashed on sync wait here. Review each
          one's mutation and reason, then Discard it to clear it from the queue.
        </AlertDescription>
      </Alert>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="state">State</Label>
        <Select
          value={state}
          onValueChange={(v) => setState(v as SyncReviewState)}
        >
          <SelectTrigger id="state" className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load the queue.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No {state} items.
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {rows.map((item) => (
              <div key={item.id} className="bg-card rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{item.mutation_kind}</p>
                    <p className="text-muted-foreground mt-1 text-xs">
                      {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <Badge variant="secondary" className="shrink-0">
                    {item.reason}
                  </Badge>
                </div>
                <div className="mt-3 border-t pt-3">
                  {isResolvable(item.state) ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="w-full"
                      disabled={discardMutation.isPending}
                      onClick={() => discardMutation.mutate(item.id)}
                    >
                      Discard
                    </Button>
                  ) : (
                    <Badge variant="secondary">{item.state}</Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <ListTable
            widths={SYNC_REVIEW_WIDTHS}
            minWidth={780}
            head={
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Mutation</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            }
          >
            {rows.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="text-muted-foreground">
                  {new Date(item.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-medium">
                  {item.mutation_kind}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{item.reason}</Badge>
                </TableCell>
                <TableCell className="overflow-visible! text-right">
                  {isResolvable(item.state) ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={discardMutation.isPending}
                      onClick={() => discardMutation.mutate(item.id)}
                    >
                      Discard
                    </Button>
                  ) : (
                    <Badge variant="secondary">{item.state}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </ListTable>
        </ListShell>
      )}
    </div>
  )
}
