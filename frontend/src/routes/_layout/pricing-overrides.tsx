import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BadgePercent } from "lucide-react"
import { useState } from "react"

import {
  type OverrideState,
  type PricingOverrideDecision,
  PricingOverridesService,
} from "@/client"
import { LIST_SCROLL, ListShell } from "@/components/Common/ListShell"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { formatDeviationPct, isPending } from "@/lib/pricing-overrides"
import { formatThb } from "@/lib/reports"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only: the pricing-override approval queue (FR-010). Staff request a
// price deviation mid-sale; deviations above the configured threshold land here
// PENDING for an admin to approve or reject.
export const Route = createFileRoute("/_layout/pricing-overrides")({
  component: PricingOverrides,
  beforeLoad: requireAdmin,
  head: () => ({
    meta: [{ title: "Pricing overrides - CastraNova POS" }],
  }),
})

const STATES: OverrideState[] = [
  "PENDING",
  "AUTO_APPROVED",
  "APPROVED",
  "REJECTED",
]

function PricingOverrides() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const [state, setState] = useState<OverrideState>("PENDING")
  const { page, pageSize, skip, limit, setPage, reset } = usePagination()

  const {
    data: overridePage,
    isPending: isLoading,
    isPlaceholderData,
    isFetching,
    isError,
  } = useQuery({
    queryKey: ["pricing-overrides", state, { skip, limit }],
    queryFn: () =>
      PricingOverridesService.listPricingOverrides({ state, skip, limit }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching

  const decideMutation = useMutation({
    mutationFn: ({
      overrideId,
      decision,
    }: {
      overrideId: string
      decision: PricingOverrideDecision["decision"]
    }) =>
      PricingOverridesService.decidePricingOverride({
        overrideId,
        requestBody: { decision },
      }),
    onSuccess: (_data, { decision }) => {
      // Invalidate all state slices — a decided override moves between views.
      queryClient.invalidateQueries({ queryKey: ["pricing-overrides"] })
      showSuccessToast(
        decision === "APPROVED" ? "Override approved." : "Override rejected.",
      )
    },
    onError: () => showErrorToast("Could not record the decision. Try again."),
  })

  const rows = overridePage?.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Pricing overrides"
        description="Approve or reject price-deviation requests above the threshold."
      />

      <Alert>
        <BadgePercent />
        <AlertTitle>Review price-deviation requests</AlertTitle>
        <AlertDescription>
          When staff sell outside the allowed price band, the request lands
          here. Filter by state, check the requested price and deviation, then
          Approve or Reject each pending one.
        </AlertDescription>
      </Alert>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="state">State</Label>
        <Select
          value={state}
          onValueChange={(v) => {
            setState(v as OverrideState)
            reset()
          }}
        >
          <SelectTrigger id="state" className="w-full sm:w-56">
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
          Could not load overrides.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No {state} requests.
        </p>
      ) : isMobile ? (
        <ListShell loading={listLoading}>
          <div className="space-y-3">
            {rows.map((o) => {
              const deciding = decideMutation.isPending
              return (
                <div key={o.id} className="bg-card rounded-lg border p-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="num min-w-0 truncate font-medium">
                      {o.product_sku}
                    </p>
                    <span className="num shrink-0 text-right text-sm">
                      {formatThb(o.requested_price_thb)}
                      <span className="text-muted-foreground block text-xs">
                        was {formatThb(o.default_price_thb)} ·{" "}
                        {formatDeviationPct(o.deviation_pct)}
                      </span>
                    </span>
                  </div>
                  {o.reason ? (
                    <p className="text-muted-foreground mt-2 text-sm">
                      {o.reason}
                    </p>
                  ) : null}
                  <div className="mt-3 border-t pt-3">
                    {isPending(o.state) ? (
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          className="flex-1"
                          disabled={deciding}
                          onClick={() =>
                            decideMutation.mutate({
                              overrideId: o.id,
                              decision: "APPROVED",
                            })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="flex-1"
                          disabled={deciding}
                          onClick={() =>
                            decideMutation.mutate({
                              overrideId: o.id,
                              decision: "REJECTED",
                            })
                          }
                        >
                          Reject
                        </Button>
                      </div>
                    ) : (
                      <Badge variant="secondary">{o.state}</Badge>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </ListShell>
      ) : (
        <ListShell loading={listLoading}>
          <Table containerClassName={LIST_SCROLL}>
            <TableHeader className="bg-background sticky top-0 z-10">
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead className="text-right">Default</TableHead>
                <TableHead className="text-right">Requested</TableHead>
                <TableHead className="text-right">Deviation</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((o) => {
                // One decision at a time: disable every row's actions while any
                // decide is in flight (a single shared mutation isn't re-entrant).
                const deciding = decideMutation.isPending
                return (
                  <TableRow key={o.id}>
                    <TableCell className="num font-medium">
                      {o.product_sku}
                    </TableCell>
                    <TableCell className="num text-right">
                      {formatThb(o.default_price_thb)}
                    </TableCell>
                    <TableCell className="num text-right">
                      {formatThb(o.requested_price_thb)}
                    </TableCell>
                    <TableCell className="num text-right">
                      {formatDeviationPct(o.deviation_pct)}
                    </TableCell>
                    <TableCell className="text-muted-foreground max-w-xs truncate">
                      {o.reason}
                    </TableCell>
                    <TableCell className="text-right">
                      {isPending(o.state) ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            type="button"
                            size="sm"
                            disabled={deciding}
                            onClick={() =>
                              decideMutation.mutate({
                                overrideId: o.id,
                                decision: "APPROVED",
                              })
                            }
                          >
                            Approve
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={deciding}
                            onClick={() =>
                              decideMutation.mutate({
                                overrideId: o.id,
                                decision: "REJECTED",
                              })
                            }
                          >
                            Reject
                          </Button>
                        </div>
                      ) : (
                        <Badge variant="secondary">{o.state}</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </ListShell>
      )}
      <PaginationControls
        total={overridePage?.count ?? 0}
        pageSize={pageSize}
        page={page}
        onPageChange={setPage}
      />
    </div>
  )
}
