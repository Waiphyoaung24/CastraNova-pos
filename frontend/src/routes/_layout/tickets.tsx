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

/** Run the full ticket lifecycle in one online-only sequence. */
async function submitTicket(s: TicketSubmission): Promise<ServiceTicketPublic> {
  const ticket = await ServiceTicketsService.openServiceTicket({
    requestBody: s.open,
  })
  for (const part of s.parts) {
    await ServiceTicketsService.addServiceTicketPart({
      ticketId: ticket.id,
      requestBody: part,
    })
  }
  return ServiceTicketsService.closeServiceTicket({
    ticketId: ticket.id,
    requestBody: s.close,
  })
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
      crypto.randomUUID(),
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
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger id={customerSelectId} className="w-full">
                <SelectValue placeholder="Select a customer" />
              </SelectTrigger>
              <SelectContent>
                {(customers ?? []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
        <Select value={customerId} onValueChange={setCustomerId}>
          <SelectTrigger className="w-full" aria-label="Customer">
            <SelectValue placeholder="Select a customer" />
          </SelectTrigger>
          <SelectContent>
            {(customers ?? []).map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {closeButton}
      </div>
    </div>
  )
}
