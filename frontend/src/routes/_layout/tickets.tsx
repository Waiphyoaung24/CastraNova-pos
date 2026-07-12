import { useMutation } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Wrench } from "lucide-react"
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"

import {
  type CustomerOption,
  type ServiceTicketPublic,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { CustomerCreateDialog } from "@/components/pos/CustomerCreateDialog"
import {
  TicketPartsList,
  type TicketResultSummary,
} from "@/components/pos/TicketPartsList"
import { ScanField, type ScanFieldHandle } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { useProductOptions } from "@/hooks/useProductOptions"
import { useCustomerOptions } from "@/hooks/useCustomerOptions"
import { useScanLookup } from "@/hooks/useScanLookup"
import { queued } from "@/lib/query-client"
import { requireAuth } from "@/lib/route-guards"
import type { Queued } from "@/lib/sync-producer"
import {
  addScanToTicketParts,
  buildTicketSubmission,
  type PartCatalogEntry,
  removePart,
  setPartQuantity,
  type TicketPartLine,
  type TicketSubmission,
} from "@/lib/ticket-parts"

export const Route = createFileRoute("/_layout/tickets")({
  component: Tickets,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Tickets - CastraNova POS" }],
  }),
})

interface CustomerPickerProps {
  customers: CustomerOption[]
  value: string
  onChange: (value: string) => void
  /** Set on mobile where there is no visible label. */
  ariaLabel?: string
}

/**
 * Customer dropdown shared by the desktop pane and the mobile footer. Extracted
 * so the option list lives in one place; the two call sites differ only in how
 * the trigger is labelled (id+<Label> on desktop, aria-label on mobile).
 */
function CustomerPicker({
  customers,
  value,
  onChange,
  ariaLabel,
}: CustomerPickerProps) {
  return (
    <div className="space-y-2">
      <EntityCombobox
        items={customers}
        value={value || undefined}
        onChange={(next) => onChange(next ?? "")}
        getKey={(customer) => customer.id}
        getLabel={(customer) => customer.name}
        placeholder="Select a customer"
        searchPlaceholder="Search customers…"
        emptyText="No customers available"
        ariaLabel={ariaLabel}
      />
      <CustomerCreateDialog onCreated={(c) => onChange(c.id)} />
    </div>
  )
}

function Tickets() {
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [parts, setParts] = useState<TicketPartLine[]>([])
  const [customerId, setCustomerId] = useState<string>("")
  const [issue, setIssue] = useState<string>("")
  const [notes, setNotes] = useState<string>("")
  const [resolution, setResolution] = useState<string>("")
  const [ticketResult, setTicketResult] = useState<
    TicketResultSummary | undefined
  >()
  // UNIT-rejection notice: a UNIT scan resolves successfully (not notFound/error),
  // so it needs its own message slot, cleared on the next successful PART add.
  const [scanNotice, setScanNotice] = useState<string>("")
  const scanRef = useRef<ScanFieldHandle>(null)
  // One idempotency key per logical submission. Reused across an offline replay
  // so record_service_ticket dedupes onto the same ticket. Rotated only after a
  // ticket successfully closes.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID())

  const issueId = useId()
  const notesId = useId()
  const resolutionId = useId()

  const { data: products } = useProductOptions({ activeOnly: true })
  const { data: customers } = useCustomerOptions()

  // sku → catalog entry, restricted to QUANTITY products (the only valid parts).
  const partLookup = useMemo(() => {
    const map = new Map<string, PartCatalogEntry>()
    for (const p of products ?? []) {
      if (p.tracking_mode !== "QUANTITY") continue
      map.set(p.sku, {
        productId: p.id,
        modelName: p.model_name,
        repairPriceThb: Number(p.repair_price_thb),
      })
    }
    return map
  }, [products])

  const { resolve, result, isSearching, notFound, isError, reset } =
    useScanLookup()

  // Fold each resolved scan into the cart. PART → add (clears stale notice +
  // post-close summary); UNIT → show the not-a-part notice; NOT_FOUND → handled
  // by the `notFound` live region below.
  useEffect(() => {
    if (!result) return
    if (result.kind === "PART") {
      setParts((prev) => addScanToTicketParts(prev, result, partLookup))
      setScanNotice("")
      setTicketResult(undefined)
    } else if (result.kind === "UNIT") {
      setScanNotice("Serialized units can't be added as repair parts.")
    } else {
      setScanNotice("")
    }
    reset()
  }, [result, partLookup, reset])

  const mutation = useMutation<
    ServiceTicketPublic,
    Error,
    Queued<TicketSubmission>
  >({
    // No mutationFn here on purpose: inherit the persisted ["tickets"] default
    // from query-client.ts so an offline close is queued and replayed by key
    // (the whole-ticket idempotency_key makes the replay safe).
    mutationKey: ["tickets"],
    onSuccess: (ticket) => {
      const total = ticket.parts.reduce(
        (sum, p) => sum + Number(p.unit_price_thb) * p.quantity,
        0,
      )
      setTicketResult({ partsCount: ticket.parts.length, totalThb: total })
      setParts([])
      setIssue("")
      setNotes("")
      setResolution("")
      idempotencyKeyRef.current = crypto.randomUUID()
      showSuccessToast("Ticket closed.")
      scanRef.current?.focus()
    },
    onError: () => {
      showErrorToast("Could not close the ticket. Please try again.")
    },
  })

  const canClose =
    customerId !== "" && issue.trim() !== "" && !mutation.isPending

  const handleClose = useCallback(() => {
    if (!canClose) return
    const submission = buildTicketSubmission(
      parts,
      customerId,
      issue,
      notes,
      resolution,
      idempotencyKeyRef.current,
    )
    // One idempotency key per attempt, reused across an offline replay so the
    // backend dedupes (record_service_ticket is idempotent on it).
    mutation.mutate(queued(submission, idempotencyKeyRef.current))
  }, [canClose, parts, customerId, issue, notes, resolution, mutation])

  const closeButton = (
    <Button
      type="button"
      variant="cta"
      onClick={handleClose}
      disabled={!canClose}
      className="h-11 w-full text-sm font-semibold"
    >
      {mutation.isPending ? "Closing…" : "Close ticket"}
    </Button>
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Service ticket"
        description="Open a ticket, scan repair parts, then close it."
      />

      <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
        {/* Left pane: issue + scan + parts */}
        <div className="space-y-4">
          <Alert>
            <Wrench />
            <AlertTitle>Log a repair</AlertTitle>
            <AlertDescription>
              Describe the issue and pick a customer, then scan each repair part
              to add it — parts are priced automatically. Close the ticket to
              record the repair and draw the parts from stock.
            </AlertDescription>
          </Alert>

          <div className="space-y-2">
            <Label htmlFor={issueId}>Issue</Label>
            <Input
              id={issueId}
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
              maxLength={512}
              placeholder="What needs fixing?"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor={notesId}>Notes (optional)</Label>
            <Input
              id={notesId}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={512}
              placeholder="Any extra details (optional)"
            />
          </div>

          <ScanField
            ref={scanRef}
            label="Scan part"
            clearOnScan
            onScan={resolve}
            status={
              <>
                <p
                  aria-live="assertive"
                  className="text-muted-foreground min-h-5 text-sm"
                >
                  {isError
                    ? "Scan lookup failed. Try again."
                    : notFound
                      ? "No item found for that code."
                      : scanNotice}
                </p>
                <p
                  aria-live="polite"
                  className="text-muted-foreground min-h-5 text-sm"
                >
                  {isSearching ? "Searching…" : ""}
                </p>
              </>
            }
          />

          <TicketPartsList
            lines={parts}
            onQuantityChange={(key, qty) =>
              setParts((prev) => setPartQuantity(prev, key, qty))
            }
            onRemove={(key) => setParts((prev) => removePart(prev, key))}
            ticketResult={ticketResult}
          />
        </div>

        {/* Right pane (desktop): customer + resolution + close */}
        <div className="hidden space-y-4 md:block">
          <div className="space-y-2">
            <Label>Customer</Label>
            <CustomerPicker
              customers={customers ?? []}
              value={customerId}
              onChange={setCustomerId}
              ariaLabel="Customer"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={resolutionId}>What was done (optional)</Label>
            <Input
              id={resolutionId}
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              maxLength={512}
              placeholder="Describe the repair or outcome"
            />
          </div>
          {closeButton}
        </div>
      </div>

      {/* Mobile/tablet: customer + close pinned to a sticky footer. */}
      <div className="bg-background/90 supports-[backdrop-filter]:bg-background/75 sticky bottom-0 z-10 space-y-3 border-t py-4 backdrop-blur md:hidden">
        <CustomerPicker
          customers={customers ?? []}
          value={customerId}
          onChange={setCustomerId}
          ariaLabel="Customer"
        />
        {closeButton}
      </div>
    </div>
  )
}
