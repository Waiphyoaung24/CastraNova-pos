import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import {
  type SyncReviewResolve,
  SyncReviewService,
  type SyncReviewState,
} from "@/client"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { requireAdmin } from "@/lib/route-guards"
import { isResolvable } from "@/lib/sync-review"

// Admin-only offline sync-review queue (§6.7). STALE/CONFLICT mutations that
// could not auto-apply land here for an admin to keep (commit) or discard.
export const Route = createFileRoute("/_layout/sync-review")({
  component: SyncReview,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Sync review - CastraNova POS" }],
  }),
})

const STATES: SyncReviewState[] = ["PENDING", "RESOLVED", "DISCARDED"]

function SyncReview() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [state, setState] = useState<SyncReviewState>("PENDING")

  const {
    data,
    isPending: isLoading,
    isError,
  } = useQuery({
    queryKey: ["sync-review", state],
    // Review queue reads the full bounded window (backend caps at 500) — no pagination UI yet.
    queryFn: () => SyncReviewService.listSyncReviewItems({ state, limit: 500 }),
  })

  const resolveMutation = useMutation({
    mutationFn: ({
      itemId,
      decision,
    }: {
      itemId: string
      decision: SyncReviewResolve["state"]
    }) =>
      SyncReviewService.resolveSyncReviewItem({
        itemId,
        requestBody: { state: decision },
      }),
    onSuccess: (_data, { decision }) => {
      queryClient.invalidateQueries({ queryKey: ["sync-review"] })
      showSuccessToast(
        decision === "RESOLVED" ? "Item kept." : "Item discarded.",
      )
    },
    onError: () => showErrorToast("Could not resolve the item. Try again."),
  })

  const rows = data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Sync review</h1>
        <p className="text-muted-foreground">
          Offline mutations that need a manual keep/discard decision.
        </p>
      </div>

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
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Mutation</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
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
                <TableCell className="text-right">
                  {isResolvable(item.state) ? (
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        size="sm"
                        disabled={resolveMutation.isPending}
                        onClick={() =>
                          resolveMutation.mutate({
                            itemId: item.id,
                            decision: "RESOLVED",
                          })
                        }
                      >
                        Keep
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={resolveMutation.isPending}
                        onClick={() =>
                          resolveMutation.mutate({
                            itemId: item.id,
                            decision: "DISCARDED",
                          })
                        }
                      >
                        Discard
                      </Button>
                    </div>
                  ) : (
                    <Badge variant="secondary">{item.state}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
