import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { SlidersHorizontal } from "lucide-react"
import { useId, useState } from "react"

import { ApiError, SalesService, StockAdjustmentsService } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { ScanField } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { requireAdmin } from "@/lib/route-guards"
import {
  buildReturnPayload,
  canSubmitReturn,
  clampReturnQuantity,
  emptyReturnDraft,
  type ReturnDraft,
} from "@/lib/sale-return"
import {
  type AdjustmentDraft,
  buildAdjustmentPayload,
  canSubmitAdjustment,
  emptyAdjustmentDraft,
} from "@/lib/stock-adjustment"

export const Route = createFileRoute("/_layout/stock-adjustment")({
  component: StockAdjustment,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Stock adjustment - CastraNova POS" }],
  }),
})

/** Quantity-tab mode: correct the count, or take stock back from a sale. */
type QtyAction = "ADJUST" | "RETURN"

function StockAdjustment() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const barcodeId = useId()
  const skuId = useId()
  const deltaId = useId()
  const costId = useId()
  const reasonId = useId()
  const returnReasonId = useId()
  const salePickerId = useId()
  const returnQtyId = useId()

  const [draft, setDraft] = useState<AdjustmentDraft>(emptyAdjustmentDraft)
  const [returnDraft, setReturnDraft] = useState<ReturnDraft>(emptyReturnDraft)
  const [qtyAction, setQtyAction] = useState<QtyAction>("ADJUST")
  const set = (patch: Partial<AdjustmentDraft>) =>
    setDraft((d) => ({ ...d, ...patch }))
  const setReturn = (patch: Partial<ReturnDraft>) =>
    setReturnDraft((d) => ({ ...d, ...patch }))

  const barcode = draft.barcode.trim()
  const sku = draft.sku.trim()

  // A scanned barcode that resolves to a still-returnable sale line means the
  // unit is SOLD and can come back; an empty result means write-off is the only
  // action available for it.
  const unitReturnQuery = useQuery({
    queryKey: ["returnable-sales", "barcode", barcode],
    queryFn: () =>
      SalesService.readReturnableSales({ castranovaBarcode: barcode }),
    enabled: draft.targetKind === "UNIT" && barcode.length > 0,
  })
  const unitReturn = unitReturnQuery.data?.sales[0]
  const unitReturnLine = unitReturn?.lines[0]

  const skuReturnQuery = useQuery({
    queryKey: ["returnable-sales", "sku", sku],
    queryFn: () => SalesService.readReturnableSales({ sku }),
    enabled:
      draft.targetKind === "QUANTITY" &&
      qtyAction === "RETURN" &&
      sku.length > 0,
  })
  const selectedLine = skuReturnQuery.data?.sales
    .flatMap((s) => s.lines)
    .find((l) => l.sale_line_id === returnDraft.saleLineId)

  const mutation = useMutation({
    mutationFn: () =>
      StockAdjustmentsService.createStockAdjustment({
        requestBody: buildAdjustmentPayload(draft, crypto.randomUUID()),
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

  // Takes the draft as a variable rather than reading state, so a click that
  // both selects a line and submits cannot post a stale draft.
  const returnMutation = useMutation({
    mutationFn: (vars: { saleId: string; draft: ReturnDraft }) =>
      SalesService.createSaleReturn({
        saleId: vars.saleId,
        requestBody: buildReturnPayload(vars.draft, crypto.randomUUID()),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stock-on-hand"] })
      queryClient.invalidateQueries({ queryKey: ["search-sku"] })
      queryClient.invalidateQueries({ queryKey: ["search-serial"] })
      queryClient.invalidateQueries({ queryKey: ["returnable-sales"] })
      showSuccessToast("Return recorded. The stock is back on hand.")
      setReturnDraft(emptyReturnDraft)
      setDraft({ ...emptyAdjustmentDraft, targetKind: draft.targetKind })
    },
    onError: (err) => {
      const detail =
        err instanceof ApiError && err.body && typeof err.body === "object"
          ? (err.body as { detail?: string }).detail
          : undefined
      showErrorToast(detail ?? "Could not record the return.")
    },
  })

  const deltaNum = Number.parseInt(draft.qtyDelta, 10)
  const isQuantityReturn =
    draft.targetKind === "QUANTITY" && qtyAction === "RETURN"
  const showCost =
    draft.targetKind === "QUANTITY" &&
    !isQuantityReturn &&
    Number.isFinite(deltaNum) &&
    deltaNum > 0

  // The unit tab has nothing to choose: only the reason is real state.
  const unitPending: ReturnDraft = {
    ...returnDraft,
    saleId: unitReturn?.sale_id ?? "",
    saleLineId: unitReturnLine?.sale_line_id ?? "",
    quantity: "1",
  }
  const offeringUnitReturn = Boolean(unitReturn && unitReturnLine)

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
              setReturnDraft(emptyReturnDraft)
              setQtyAction("ADJUST")
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
              {unitReturn && unitReturnLine ? (
                <div className="border-primary/30 bg-primary/5 space-y-3 rounded-lg border p-4">
                  <p className="font-medium">
                    This unit was sold — you can return it to stock.
                  </p>
                  <p className="text-muted-foreground text-sm">
                    {unitReturnLine.label} · sold{" "}
                    {new Date(unitReturn.sold_at).toLocaleDateString()} to{" "}
                    {unitReturn.customer_name}
                  </p>
                  <p className="text-sm">
                    Refund:{" "}
                    <span className="num">{unitReturnLine.unit_price_thb}</span>{" "}
                    THB — the original sale price, which cannot be changed here.
                  </p>
                  <div className="space-y-2">
                    <Label htmlFor={returnReasonId}>
                      Reason for the return
                    </Label>
                    <Input
                      id={returnReasonId}
                      value={returnDraft.reason}
                      maxLength={512}
                      onChange={(e) => setReturn({ reason: e.target.value })}
                      placeholder="Why is the customer returning this?"
                    />
                  </div>
                  <Button
                    type="button"
                    disabled={
                      !canSubmitReturn(
                        unitPending,
                        unitReturnLine.quantity_returnable,
                      ) || returnMutation.isPending
                    }
                    onClick={() =>
                      returnMutation.mutate({
                        saleId: unitReturn.sale_id,
                        draft: unitPending,
                      })
                    }
                  >
                    {returnMutation.isPending
                      ? "Returning…"
                      : "Return to stock"}
                  </Button>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  The unit moves to the terminal ADJUSTED_OUT state.
                </p>
              )}
            </div>
          ) : (
            <>
              <Tabs
                value={qtyAction}
                onValueChange={(v) => {
                  setQtyAction(v as QtyAction)
                  setDraft({
                    ...emptyAdjustmentDraft,
                    targetKind: "QUANTITY",
                    sku: draft.sku,
                  })
                  setReturnDraft(emptyReturnDraft)
                }}
              >
                <TabsList>
                  <TabsTrigger value="ADJUST">Found / Lost</TabsTrigger>
                  <TabsTrigger value="RETURN">Return</TabsTrigger>
                </TabsList>
              </Tabs>

              <div className="space-y-2">
                <Label htmlFor={skuId}>SKU</Label>
                <ScanField
                  id={skuId}
                  value={draft.sku}
                  onValueChange={(sku) => {
                    set({ sku })
                    setReturn({ saleId: "", saleLineId: "" })
                  }}
                  onScan={(sku) => {
                    set({ sku })
                    setReturn({ saleId: "", saleLineId: "" })
                  }}
                  placeholder="Scan or type the SKU…"
                />
              </div>

              {isQuantityReturn ? (
                <>
                  {/* Nothing to pick from until a SKU has been entered, so the
                      label and the picker stay hidden until then. */}
                  {sku.length === 0 ? null : skuReturnQuery.data &&
                    skuReturnQuery.data.sales.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      Nothing from this SKU can be returned — no recent sale of
                      it still has returnable stock.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      <Label htmlFor={salePickerId}>
                        Sale being returned from
                      </Label>
                      <Select
                        value={returnDraft.saleLineId}
                        onValueChange={(saleLineId) => {
                          const hit = skuReturnQuery.data?.sales.find((s) =>
                            s.lines.some((l) => l.sale_line_id === saleLineId),
                          )
                          setReturn({
                            saleLineId,
                            saleId: hit?.sale_id ?? "",
                            quantity: "1",
                          })
                        }}
                      >
                        <SelectTrigger id={salePickerId}>
                          <SelectValue placeholder="Pick the sale this is coming back from…" />
                        </SelectTrigger>
                        <SelectContent>
                          {skuReturnQuery.data?.sales.flatMap((s) =>
                            s.lines.map((l) => (
                              <SelectItem
                                key={l.sale_line_id}
                                value={l.sale_line_id}
                              >
                                {new Date(s.sold_at).toLocaleDateString()} ·{" "}
                                {s.customer_name} · {l.quantity_returnable} of{" "}
                                {l.quantity_sold} returnable
                              </SelectItem>
                            )),
                          )}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {selectedLine ? (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor={returnQtyId}>Quantity returned</Label>
                        <Input
                          id={returnQtyId}
                          inputMode="numeric"
                          className="num"
                          value={returnDraft.quantity}
                          onChange={(e) =>
                            setReturn({
                              quantity: clampReturnQuantity(
                                e.target.value,
                                selectedLine.quantity_returnable,
                              ),
                            })
                          }
                          placeholder="How many are coming back?"
                        />
                        <p className="text-muted-foreground text-sm">
                          Up to {selectedLine.quantity_returnable} can still be
                          returned from this sale line.
                        </p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor={returnReasonId}>
                          Reason for the return
                        </Label>
                        <Input
                          id={returnReasonId}
                          value={returnDraft.reason}
                          maxLength={512}
                          onChange={(e) =>
                            setReturn({ reason: e.target.value })
                          }
                          placeholder="Why is the customer returning this?"
                        />
                      </div>
                      <p className="text-sm">
                        Refund:{" "}
                        <span className="num">
                          {selectedLine.unit_price_thb}
                        </span>{" "}
                        THB each — the original sale price, which cannot be
                        changed here.
                      </p>
                      <Button
                        type="button"
                        disabled={
                          !canSubmitReturn(
                            returnDraft,
                            selectedLine.quantity_returnable,
                          ) || returnMutation.isPending
                        }
                        onClick={() =>
                          returnMutation.mutate({
                            saleId: returnDraft.saleId,
                            draft: returnDraft,
                          })
                        }
                      >
                        {returnMutation.isPending
                          ? "Recording…"
                          : "Record return"}
                      </Button>
                    </>
                  ) : null}
                </>
              ) : (
                <>
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
                      Negative consumes oldest batches first (FIFO); positive
                      adds a new adjustment batch.
                    </p>
                  </div>
                  {showCost ? (
                    <div className="space-y-2">
                      <Label htmlFor={costId}>Purchase cost (THB)</Label>
                      <Input
                        id={costId}
                        inputMode="decimal"
                        className="num"
                        value={draft.purchaseCost}
                        onChange={(e) => set({ purchaseCost: e.target.value })}
                        placeholder="Cost basis for the new batch"
                      />
                    </div>
                  ) : null}
                </>
              )}
            </>
          )}

          {/* Hidden whenever a return is on offer, so a sold unit cannot be
              written off when it should be returned instead. */}
          {!isQuantityReturn && !offeringUnitReturn ? (
            <>
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
                disabled={!canSubmitAdjustment(draft) || mutation.isPending}
                onClick={() => mutation.mutate()}
              >
                {mutation.isPending ? "Recording…" : "Record adjustment"}
              </Button>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
