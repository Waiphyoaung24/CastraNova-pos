import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { SlidersHorizontal } from "lucide-react"
import { useId, useState } from "react"

import { ApiError, SearchService, StockAdjustmentsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { ScanField } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { requireAdmin } from "@/lib/route-guards"
import {
  type AdjustmentDraft,
  buildAdjustmentPayload,
  canSubmitAdjustment,
  emptyAdjustmentDraft,
  latestCostBatch,
} from "@/lib/stock-adjustment"

export const Route = createFileRoute("/_layout/stock-adjustment")({
  component: StockAdjustment,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Stock adjustment - CastraNova POS" }],
  }),
})

function StockAdjustment() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const barcodeId = useId()
  const skuId = useId()
  const deltaId = useId()
  const costId = useId()
  const reasonId = useId()

  const [draft, setDraft] = useState<AdjustmentDraft>(emptyAdjustmentDraft)
  const set = (patch: Partial<AdjustmentDraft>) =>
    setDraft((d) => ({ ...d, ...patch }))

  const sku = draft.sku.trim()

  const deltaNum = Number.parseInt(draft.qtyDelta, 10)
  const showCost =
    draft.targetKind === "QUANTITY" && Number.isFinite(deltaNum) && deltaNum > 0

  // The cost basis for a found-stock batch defaults to what this SKU last cost.
  // Same query key as the Search screen, so the two share a cache entry and the
  // invalidation below refreshes the suggestion after a recorded adjustment.
  // ponytail: no debounce — editing the SKU while a positive delta is already
  // typed fires one 404 per keystroke. Debounce, or commit the SKU on blur like
  // search.tsx does, if this admin-only screen ever gets chatty.
  const costQuery = useQuery({
    queryKey: ["search-sku", sku],
    queryFn: () => SearchService.searchSku({ sku }),
    enabled: showCost && sku.length > 0,
    retry: false,
  })
  const suggestedBatch = latestCostBatch(costQuery.data)
  // Derived, not synced into state: an untouched cost field shows the
  // suggestion, and typing over it (or clearing it) wins.
  const effectiveDraft: AdjustmentDraft =
    draft.purchaseCost === "" && suggestedBatch
      ? { ...draft, purchaseCost: suggestedBatch.purchase_cost_thb }
      : draft

  const mutation = useMutation({
    mutationFn: (d: AdjustmentDraft) =>
      StockAdjustmentsService.createStockAdjustment({
        requestBody: buildAdjustmentPayload(d, crypto.randomUUID()),
      }),
    onSuccess: () => {
      // On-hand totals and any open search results are now stale.
      queryClient.invalidateQueries({ queryKey: ["stock-on-hand"] })
      queryClient.invalidateQueries({ queryKey: ["search-sku"] })
      queryClient.invalidateQueries({ queryKey: ["search-serial"] })
      showSuccessToast("Adjustment recorded.")
      setDraft({ ...emptyAdjustmentDraft, targetKind: draft.targetKind })
    },
    onError: (err) => {
      // Surface the server reason on a conflict (e.g. unit not IN_STOCK,
      // insufficient stock for a negative delta); generic otherwise.
      const detail =
        err instanceof ApiError && err.body && typeof err.body === "object"
          ? (err.body as { detail?: string }).detail
          : undefined
      showErrorToast(detail ?? "Could not record the adjustment.")
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Stock adjustment"
        description="Write off or recount stock. Adjustments are recorded permanently and cannot be undone."
      />

      <Alert>
        <SlidersHorizontal />
        <AlertTitle>Correct your stock counts</AlertTitle>
        <AlertDescription>
          Pick Serialized unit or Quantity SKU, scan the item, and enter the
          change with a reason — a negative delta writes stock off, a positive
          one adds it back. Every adjustment is logged permanently, so
          double-check before recording.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New adjustment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs
            value={draft.targetKind}
            onValueChange={(v) => {
              setDraft({
                ...emptyAdjustmentDraft,
                targetKind: v as AdjustmentDraft["targetKind"],
              })
            }}
          >
            <TabsList>
              <TabsTrigger value="UNIT">Serialized unit</TabsTrigger>
              <TabsTrigger value="QUANTITY">Quantity SKU</TabsTrigger>
            </TabsList>
          </Tabs>

          {draft.targetKind === "UNIT" ? (
            <div className="space-y-2">
              <Label htmlFor={barcodeId}>CastraNova barcode</Label>
              <ScanField
                id={barcodeId}
                value={draft.barcode}
                onValueChange={(barcode) => set({ barcode })}
                onScan={(barcode) => set({ barcode })}
                placeholder="Scan or type the unit barcode…"
              />
              <p className="text-muted-foreground text-sm">
                The unit moves to the terminal ADJUSTED_OUT state.
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor={skuId}>SKU</Label>
                <ScanField
                  id={skuId}
                  value={draft.sku}
                  onValueChange={(sku) => set({ sku })}
                  onScan={(sku) => set({ sku })}
                  placeholder="Scan or type the SKU…"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor={deltaId}>Quantity delta</Label>
                <Input
                  id={deltaId}
                  inputMode="numeric"
                  className="num"
                  value={draft.qtyDelta}
                  onChange={(e) => set({ qtyDelta: e.target.value })}
                  placeholder="e.g. -3 (write-off) or 5 (found)"
                />
                <p className="text-muted-foreground text-sm">
                  Negative consumes oldest batches first (FIFO); positive adds a
                  new adjustment batch.
                </p>
              </div>
              {showCost ? (
                <div className="space-y-2">
                  <Label htmlFor={costId}>Purchase cost (THB)</Label>
                  <Input
                    id={costId}
                    inputMode="decimal"
                    className="num"
                    value={effectiveDraft.purchaseCost}
                    onChange={(e) => set({ purchaseCost: e.target.value })}
                    placeholder="Cost basis for the new batch"
                  />
                  {suggestedBatch ? (
                    <p className="text-muted-foreground text-sm">
                      Last received at ฿
                      <span className="num">
                        {suggestedBatch.purchase_cost_thb}
                      </span>{" "}
                      on{" "}
                      {new Date(
                        suggestedBatch.received_at,
                      ).toLocaleDateString()}
                      .
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          )}

          <div className="space-y-2">
            <Label htmlFor={reasonId}>Reason</Label>
            <Input
              id={reasonId}
              value={draft.reason}
              maxLength={512}
              onChange={(e) => set({ reason: e.target.value })}
              placeholder="Why is this adjustment being made?"
            />
          </div>

          <Button
            type="button"
            disabled={
              !canSubmitAdjustment(effectiveDraft) || mutation.isPending
            }
            onClick={() => mutation.mutate(effectiveDraft)}
          >
            {mutation.isPending ? "Recording…" : "Record adjustment"}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
