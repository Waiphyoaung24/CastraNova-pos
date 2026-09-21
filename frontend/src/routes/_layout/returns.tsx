import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Undo2 } from "lucide-react"
import { useId, useState } from "react"

import { type ApiError, ProjectPullsService, SalesService } from "@/client"
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
import {
  buildPullReturnPayload,
  buildReturnPayload,
  canSubmitReturn,
  clampReturnQuantity,
  emptyReturnDraft,
  lookupErrorMessage,
  type PickerOption,
  pickerOptions,
  type ReturnDraft,
} from "@/lib/sale-return"
import { extractErrorMessage } from "@/utils"

// Sale returns (design 2026-07-25), moved off the admin-only Stock adjustment
// screen on 2026-09-21: returns are a shared sale-desk action, so staff and
// admin both use this page. The backend redacts cost fields for staff.
export const Route = createFileRoute("/_layout/returns")({
  component: Returns,
  head: () => ({
    meta: [{ title: "Returns - CastraNova POS" }],
  }),
})

type TargetKind = "UNIT" | "QUANTITY"

function Returns() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const barcodeId = useId()
  const skuId = useId()
  const reasonId = useId()
  const salePickerId = useId()
  const qtyId = useId()

  const [targetKind, setTargetKind] = useState<TargetKind>("UNIT")
  /** Barcode (UNIT) or SKU (QUANTITY) as typed. */
  const [code, setCode] = useState("")
  const [draft, setDraft] = useState<ReturnDraft>(emptyReturnDraft)
  const set = (patch: Partial<ReturnDraft>) =>
    setDraft((d) => ({ ...d, ...patch }))

  const scanned = code.trim()

  // A scanned barcode that resolves to a still-returnable sale line means the
  // unit is SOLD and can come back; for a SKU the result feeds the sale picker.
  const lookup = useQuery({
    queryKey: [
      "returnable-sales",
      targetKind === "UNIT" ? "barcode" : "sku",
      scanned,
    ],
    queryFn: () =>
      targetKind === "UNIT"
        ? SalesService.readReturnableSales({ castranovaBarcode: scanned })
        : SalesService.readReturnableSales({ sku: scanned }),
    enabled: scanned.length > 0,
    // An unknown SKU is a 404 — show it, don't retry it.
    retry: false,
  })
  // The same scan against the project-pull ledger: stock that went out on a
  // project request comes back through the pull-return endpoint, not a sale.
  const pullLookup = useQuery({
    queryKey: [
      "returnable-pulls",
      targetKind === "UNIT" ? "barcode" : "sku",
      scanned,
    ],
    queryFn: () =>
      targetKind === "UNIT"
        ? ProjectPullsService.readReturnablePulls({
            castranovaBarcode: scanned,
          })
        : ProjectPullsService.readReturnablePulls({ sku: scanned }),
    enabled: scanned.length > 0,
    retry: false,
  })
  const unitSale = lookup.data?.sales[0]
  const unitLine = unitSale?.lines[0]
  const unitPull = pullLookup.data?.pulls[0]
  const unitPullLine = unitPull?.lines[0]
  const options = pickerOptions(lookup.data, pullLookup.data)
  const selected: PickerOption | undefined = options.find(
    (o) => o.lineId === draft.saleLineId && o.source === draft.source,
  )
  // A 404 from either lookup means the same thing (unknown SKU/barcode).
  const lookupError = lookup.error ?? pullLookup.error

  // Takes the draft as a variable rather than reading state, so a click that
  // both selects a line and submits cannot post a stale draft.
  const mutation = useMutation({
    // Two different endpoints, two different response shapes; neither is used.
    mutationFn: (vars: { draft: ReturnDraft }): Promise<unknown> =>
      vars.draft.source === "pull"
        ? ProjectPullsService.returnProjectPull({
            pullId: vars.draft.pullId,
            requestBody: buildPullReturnPayload(
              vars.draft,
              crypto.randomUUID(),
            ),
          })
        : SalesService.createSaleReturn({
            saleId: vars.draft.saleId,
            requestBody: buildReturnPayload(vars.draft, crypto.randomUUID()),
          }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stock-on-hand"] })
      queryClient.invalidateQueries({ queryKey: ["search-sku"] })
      queryClient.invalidateQueries({ queryKey: ["search-serial"] })
      queryClient.invalidateQueries({ queryKey: ["returnable-sales"] })
      queryClient.invalidateQueries({ queryKey: ["returnable-pulls"] })
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Return recorded. The stock is back on hand.")
      setDraft(emptyReturnDraft)
      setCode("")
    },
    // Surface the server reason (already returned, over-return, sale not
    // found); the shared helper also copes with 422 validation arrays.
    onError: (err: ApiError) => {
      showErrorToast(extractErrorMessage(err), "Return not recorded")
    },
  })

  // The unit tab has nothing to choose: only the reason is real state.
  const unitPending: ReturnDraft = {
    ...draft,
    source: "sale",
    pullId: "",
    saleId: unitSale?.sale_id ?? "",
    saleLineId: unitLine?.sale_line_id ?? "",
    quantity: "1",
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Returns"
        description="Take stock back from a customer or a project. A sale refund is the original sale price; returns are recorded permanently."
      />

      <Alert>
        <Undo2 />
        <AlertTitle>Return sold stock</AlertTitle>
        <AlertDescription>
          Pick Serialized unit or Quantity SKU and scan the item. A sold unit is
          offered back straight away; for a SKU, pick the sale or project
          request it is coming back from and enter how many. Every return is
          logged permanently, so double-check before recording.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New return</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs
            value={targetKind}
            onValueChange={(v) => {
              setTargetKind(v as TargetKind)
              setCode("")
              setDraft(emptyReturnDraft)
            }}
          >
            <TabsList>
              <TabsTrigger value="UNIT">Serialized unit</TabsTrigger>
              <TabsTrigger value="QUANTITY">Quantity SKU</TabsTrigger>
            </TabsList>
          </Tabs>

          {targetKind === "UNIT" ? (
            <div className="space-y-2">
              <Label htmlFor={barcodeId}>CastraNova barcode</Label>
              <ScanField
                id={barcodeId}
                value={code}
                onValueChange={setCode}
                onScan={setCode}
                placeholder="Scan or type the unit barcode…"
              />
              {unitSale && unitLine ? (
                <div className="border-primary/30 bg-primary/5 space-y-3 rounded-lg border p-4">
                  <p className="font-medium">
                    This unit was sold — you can return it to stock.
                  </p>
                  <p className="text-muted-foreground text-sm">
                    {unitLine.label} · sold{" "}
                    {new Date(unitSale.sold_at).toLocaleDateString()} to{" "}
                    {unitSale.customer_name}
                  </p>
                  <p className="text-sm">
                    Refund:{" "}
                    <span className="num">{unitLine.unit_price_thb}</span> THB —
                    the original sale price, which cannot be changed here.
                  </p>
                  <div className="space-y-2">
                    <Label htmlFor={reasonId}>Reason for the return</Label>
                    <Input
                      id={reasonId}
                      value={draft.reason}
                      maxLength={512}
                      onChange={(e) => set({ reason: e.target.value })}
                      placeholder="Why is the customer returning this?"
                    />
                  </div>
                  <Button
                    type="button"
                    disabled={
                      !canSubmitReturn(
                        unitPending,
                        unitLine.quantity_returnable,
                      ) || mutation.isPending
                    }
                    onClick={() => mutation.mutate({ draft: unitPending })}
                  >
                    {mutation.isPending ? "Returning…" : "Return to stock"}
                  </Button>
                </div>
              ) : unitPull && unitPullLine ? (
                <div className="border-primary/30 bg-primary/5 space-y-3 rounded-lg border p-4">
                  <p className="font-medium">
                    This unit went out on a project request — you can return it
                    to stock.
                  </p>
                  <p className="text-muted-foreground text-sm">
                    {unitPullLine.label} · {unitPull.project_name} (
                    {unitPull.project_code}) · {unitPull.customer_name}
                  </p>
                  <Button
                    type="button"
                    disabled={mutation.isPending}
                    onClick={() =>
                      mutation.mutate({
                        draft: {
                          ...emptyReturnDraft,
                          source: "pull",
                          pullId: unitPull.pull_id,
                          saleLineId: unitPullLine.line_id,
                          quantity: "1",
                        },
                      })
                    }
                  >
                    {mutation.isPending ? "Returning…" : "Return to stock"}
                  </Button>
                </div>
              ) : scanned.length > 0 &&
                (lookup.isError || pullLookup.isError) ? (
                <p className="text-destructive text-sm">
                  {lookupErrorMessage(lookupError)}
                </p>
              ) : scanned.length > 0 && lookup.data && pullLookup.data ? (
                <p className="text-muted-foreground text-sm">
                  Nothing to return — this unit has no recent sale or project
                  request that can still be returned.
                </p>
              ) : null}
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor={skuId}>SKU</Label>
                <ScanField
                  id={skuId}
                  value={code}
                  onValueChange={(sku) => {
                    setCode(sku)
                    set({
                      source: "sale",
                      saleId: "",
                      pullId: "",
                      saleLineId: "",
                    })
                  }}
                  onScan={(sku) => {
                    setCode(sku)
                    set({
                      source: "sale",
                      saleId: "",
                      pullId: "",
                      saleLineId: "",
                    })
                  }}
                  placeholder="Scan or type the SKU…"
                />
              </div>

              {/* Nothing to pick from until a SKU has been entered, so the
                  label and the picker stay hidden until then. */}
              {scanned.length === 0 ? null : lookup.isError ||
                pullLookup.isError ? (
                <p className="text-destructive text-sm">
                  {lookupErrorMessage(lookupError)}
                </p>
              ) : lookup.data && pullLookup.data && options.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  Nothing from this SKU can be returned — no recent sale or
                  project request still has returnable stock.
                </p>
              ) : (
                <div className="space-y-2">
                  <Label htmlFor={salePickerId}>
                    Sale or request being returned from
                  </Label>
                  <Select
                    value={
                      draft.saleLineId
                        ? `${draft.source}:${draft.saleLineId}`
                        : ""
                    }
                    onValueChange={(value) => {
                      const hit = options.find((o) => o.value === value)
                      if (!hit) return
                      set({
                        source: hit.source,
                        saleLineId: hit.lineId,
                        saleId: hit.saleId ?? "",
                        pullId: hit.pullId ?? "",
                        quantity: "1",
                      })
                    }}
                  >
                    <SelectTrigger id={salePickerId}>
                      <SelectValue placeholder="Pick the sale this is coming back from…" />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {selected ? (
                <>
                  <div className="space-y-2">
                    <Label htmlFor={qtyId}>Quantity returned</Label>
                    <Input
                      id={qtyId}
                      inputMode="numeric"
                      className="num"
                      value={draft.quantity}
                      onChange={(e) =>
                        set({
                          quantity: clampReturnQuantity(
                            e.target.value,
                            selected.quantityReturnable,
                          ),
                        })
                      }
                      placeholder="How many are coming back?"
                    />
                    <p className="text-muted-foreground text-sm">
                      Up to {selected.quantityReturnable} can still be returned
                      from this{" "}
                      {selected.source === "sale"
                        ? "sale line"
                        : "project request"}
                      .
                    </p>
                  </div>
                  {selected.source === "sale" ? (
                    <>
                      <div className="space-y-2">
                        <Label htmlFor={reasonId}>Reason for the return</Label>
                        <Input
                          id={reasonId}
                          value={draft.reason}
                          maxLength={512}
                          onChange={(e) => set({ reason: e.target.value })}
                          placeholder="Why is the customer returning this?"
                        />
                      </div>
                      <p className="text-sm">
                        Refund:{" "}
                        <span className="num">{selected.unitPriceThb}</span> THB
                        each — the original sale price, which cannot be changed
                        here.
                      </p>
                    </>
                  ) : null}
                  <Button
                    type="button"
                    disabled={
                      !canSubmitReturn(draft, selected.quantityReturnable) ||
                      mutation.isPending
                    }
                    onClick={() => mutation.mutate({ draft })}
                  >
                    {mutation.isPending ? "Recording…" : "Record return"}
                  </Button>
                </>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
