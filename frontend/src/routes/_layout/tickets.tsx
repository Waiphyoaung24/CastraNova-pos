import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  ProductsService,
  type ServiceTicketPublic,
  ServiceTicketsService,
} from "@/client"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import {
  TicketPartsList,
  type TicketResultSummary,
} from "@/components/pos/TicketPartsList"
import { ScanInput, type ScanInputHandle } from "@/components/ScanInput"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { useScanLookup } from "@/hooks/useScanLookup"
import { requireAuth } from "@/lib/route-guards"
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

const WALK_IN_RE = /walk[\s-]?in/i

function findWalkIn(customers: CustomerPublic[]): CustomerPublic | undefined {
  return customers.find((c) => WALK_IN_RE.test(c.name))
}

interface CustomerPickerProps {
  customers: CustomerPublic[]
  value: string
  onChange: (value: string) => void
  /** Set on desktop where an external <Label htmlFor> binds to it. */
  triggerId?: string
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
  triggerId,
  ariaLabel,
}: CustomerPickerProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={triggerId} aria-label={ariaLabel} className="w-full">
        <SelectValue placeholder="Select a customer" />
      </SelectTrigger>
      <SelectContent>
        {customers.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            {c.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Run the full ticket lifecycle in one online-only sequence. */
async function submitTicket(s: TicketSubmission): Promise<ServiceTicketPublic> {
  const ticket = await ServiceTicketsService.openServiceTicket({
    requestBody: s.open,
  })
  // The ticket is now open server-side. There is no cancel/void endpoint, so a
  // failure here cannot be rolled back — surface a clear message and let the
  // user retry. The retry reuses the same idempotency key (see handleClose), so
  // openServiceTicket dedupes onto this same ticket instead of orphaning it.
  try {
    for (const part of s.parts) {
      await ServiceTicketsService.addServiceTicketPart({
        ticketId: ticket.id,
        requestBody: part,
      })
    }
    return await ServiceTicketsService.closeServiceTicket({
      ticketId: ticket.id,
      requestBody: s.close,
    })
  } catch {
    // No cancel/void endpoint exists to roll the opened ticket back, so surface
    // a clear retry message; the retry reuses the same idempotency key and
    // resumes this ticket rather than opening a duplicate.
    throw new Error(
      "Ticket opened but could not be completed. Retry to resume it.",
    )
  }
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
  const scanRef = useRef<ScanInputHandle>(null)
  // One idempotency key per logical submission. Reused across retries so a retry
  // after a partial failure resumes the same ticket instead of opening a duplicate.
  // Rotated only after a ticket successfully closes.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID())

  const customerSelectId = useId()
  const issueId = useId()
  const notesId = useId()
  const resolutionId = useId()

  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
    staleTime: 5 * 60 * 1000,
  })

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

  // Default-select the walk-in customer once customers load, if one exists.
  useEffect(() => {
    if (!customers || customerId) return
    const walkIn = findWalkIn(customers)
    if (walkIn) setCustomerId(walkIn.id)
  }, [customers, customerId])

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

  const mutation = useMutation<ServiceTicketPublic, Error, TicketSubmission>({
    mutationFn: submitTicket,
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
    onError: (err) => {
      showErrorToast(
        err.message || "Could not close the ticket. Please try again.",
      )
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
    mutation.mutate(submission)
  }, [canClose, parts, customerId, issue, notes, resolution, mutation])

  const closeButton = (
    <button
      type="button"
      onClick={handleClose}
      disabled={!canClose}
      className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
    >
      {mutation.isPending ? "Closing…" : "Close ticket"}
    </button>
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Service ticket</h1>
        <p className="text-muted-foreground">
          Open a ticket, scan repair parts, then close it.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
        {/* Left pane: issue + scan + parts */}
        <div className="space-y-4">
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
            />
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Scan part</p>
            <ScanInput ref={scanRef} onScan={resolve} />
            <CameraScanFallback onScan={resolve} />
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
          </div>

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
            <Label htmlFor={customerSelectId}>Customer</Label>
            <CustomerPicker
              customers={customers ?? []}
              value={customerId}
              onChange={setCustomerId}
              triggerId={customerSelectId}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={resolutionId}>Resolution (optional)</Label>
            <Input
              id={resolutionId}
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              maxLength={512}
            />
          </div>
          {closeButton}
        </div>
      </div>

      {/* Mobile/tablet: customer + close pinned to a sticky footer. */}
      <div className="bg-background sticky bottom-0 space-y-3 border-t py-4 md:hidden">
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
