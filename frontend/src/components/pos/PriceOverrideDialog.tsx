import { useMutation } from "@tanstack/react-query"
import { useEffect, useId, useState } from "react"

import { type OverrideTargetKind, PricingOverridesService } from "@/client"
import { formatThb } from "@/components/pos/ScanCart"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { canSubmitOverride, deviationPct } from "@/lib/pricing-overrides"
import type { CartLine, LineOverride } from "@/lib/sale-cart"

interface PriceOverrideDialogProps {
  /** The cart line being repriced; null keeps the dialog closed. */
  line: CartLine | null
  onOpenChange: (open: boolean) => void
  /** Called with the created override so the caller applies it to the line. */
  onCreated: (key: string, override: LineOverride) => void
  /** "SALE_LINE" on the Sale screen; tickets will reuse with "SERVICE_TICKET_PART". */
  targetKind: OverrideTargetKind
}

/**
 * Staff price-override request (FR-010), opened by tapping a cart line's
 * price. Submits immediately (request-on-save): within the server-side
 * deviation threshold the request comes back AUTO_APPROVED; larger changes
 * come back PENDING for an admin decision. The threshold value itself is
 * intentionally absent from the copy.
 */
export function PriceOverrideDialog({
  line,
  onOpenChange,
  onCreated,
  targetKind,
}: PriceOverrideDialogProps) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const priceId = useId()
  const reasonId = useId()
  const [price, setPrice] = useState("")
  const [reason, setReason] = useState("")

  // Selecting a line (the parent nulls it on close) starts a fresh form.
  useEffect(() => {
    setPrice("")
    setReason("")
  }, [line?.key])

  const mutation = useMutation({
    mutationFn: (l: CartLine) =>
      PricingOverridesService.createPricingOverride({
        requestBody: {
          target_kind: targetKind,
          product_id: l.productId,
          requested_price_thb: price,
          reason: reason.trim(),
        },
      }),
    onSuccess: (created, l) => {
      onCreated(l.key, {
        id: created.id,
        state: created.state,
        requestedPriceThb: Number(created.requested_price_thb),
      })
      showSuccessToast(
        created.state === "PENDING"
          ? "Sent for admin approval."
          : "Price updated.",
      )
      onOpenChange(false)
    },
    onError: () =>
      showErrorToast("Could not request the price change. Please try again."),
  })

  const parsed = Number(price)
  const pct =
    line !== null &&
    price.trim() !== "" &&
    Number.isFinite(parsed) &&
    parsed > 0
      ? deviationPct(line.unitPriceThb, parsed)
      : null
  const canSubmit =
    line !== null &&
    canSubmitOverride({ priceThb: price, reason }) &&
    !mutation.isPending

  return (
    <Dialog open={line !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change price</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Current price: {line ? formatThb(line.unitPriceThb) : ""}. Large
            changes are sent to an admin for approval.
          </p>
          <div className="space-y-2">
            <Label htmlFor={priceId}>New unit price (฿)</Label>
            <Input
              id={priceId}
              inputMode="decimal"
              value={price}
              placeholder={line ? String(line.unitPriceThb) : ""}
              onChange={(e) => setPrice(e.target.value)}
            />
            <p
              aria-live="polite"
              className="text-muted-foreground min-h-5 text-sm"
            >
              {pct !== null
                ? `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% vs. current price`
                : ""}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={reasonId}>Reason</Label>
            <Input
              id={reasonId}
              value={reason}
              maxLength={512}
              placeholder="e.g. matched competitor quote"
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => line && mutation.mutate(line)}
          >
            {mutation.isPending ? "Saving…" : "Save price"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default PriceOverrideDialog
