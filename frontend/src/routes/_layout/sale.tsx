import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  ProductsService,
  type SaleCreateRequest,
  type SalePublic,
  type SaleStaffPublic,
} from "@/client"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import { type SaleResultSummary, ScanCart } from "@/components/pos/ScanCart"
import { ScanInput, type ScanInputHandle } from "@/components/ScanInput"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { useRole } from "@/hooks/useRole"
import { useScanLookup } from "@/hooks/useScanLookup"
import { requireAuth } from "@/lib/route-guards"
import {
  addScanToCart,
  buildSaleRequest,
  type CartLine,
  removeLine,
  setLineQuantity,
} from "@/lib/sale-cart"

export const Route = createFileRoute("/_layout/sale")({
  component: Sale,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Sale - CastraNova POS" }],
  }),
})

const WALK_IN_RE = /walk[\s-]?in/i

/** A walk-in customer is the default counter sale when no specific customer is chosen. */
function findWalkIn(customers: CustomerPublic[]): CustomerPublic | undefined {
  return customers.find((c) => WALK_IN_RE.test(c.name))
}

interface CheckoutPanelProps {
  customers: CustomerPublic[]
  customerId: string
  onCustomerChange: (value: string) => void
  canCheckout: boolean
  onCheckout: () => void
  /** Drives the button label: queued (offline) vs. completing vs. idle. */
  isPaused: boolean
  isPending: boolean
}

/**
 * Customer picker + checkout button. Extracted as its own component so each
 * rendered instance (desktop pane + mobile sticky footer) gets a unique `useId`
 * for the Customer label/select association — rendering one shared JSX node in
 * two DOM slots would duplicate the id and break the label binding.
 */
function CheckoutPanel({
  customers,
  customerId,
  onCustomerChange,
  canCheckout,
  onCheckout,
  isPaused,
  isPending,
}: CheckoutPanelProps) {
  const customerSelectId = useId()

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={customerSelectId}>Customer</Label>
        <Select value={customerId} onValueChange={onCustomerChange}>
          <SelectTrigger id={customerSelectId} className="w-full">
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
      </div>

      <button
        type="button"
        onClick={onCheckout}
        disabled={!canCheckout}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPaused
          ? "Queued (offline)…"
          : isPending
            ? "Completing…"
            : "Complete sale"}
      </button>
    </div>
  )
}

function Sale() {
  const { isAdmin } = useRole()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [lines, setLines] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState<string>("")
  const [saleResult, setSaleResult] = useState<SaleResultSummary | undefined>()
  const scanRef = useRef<ScanInputHandle>(null)

  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    // Reference data: hold steady mid-sale to avoid price drift / refetch churn.
    staleTime: 5 * 60 * 1000,
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
    // Reference data: hold steady mid-sale to avoid price drift / refetch churn.
    staleTime: 5 * 60 * 1000,
  })

  const priceMap = useMemo(
    () =>
      new Map((products ?? []).map((p) => [p.id, Number(p.retail_price_thb)])),
    [products],
  )

  // Default-select the walk-in customer once customers load, if one exists.
  useEffect(() => {
    if (!customers || customerId) return
    const walkIn = findWalkIn(customers)
    if (walkIn) setCustomerId(walkIn.id)
  }, [customers, customerId])

  const { resolve, result, isSearching, notFound, isError, reset } =
    useScanLookup()

  // Fold each resolved scan into the cart, then reset so the next scan registers.
  // A fresh scan also clears any stale post-sale totals.
  useEffect(() => {
    if (!result) return
    if (result.kind !== "NOT_FOUND") {
      setLines((prev) => addScanToCart(prev, result, priceMap))
      setSaleResult(undefined)
    }
    reset()
  }, [result, priceMap, reset])

  const mutation = useMutation<
    SalePublic | SaleStaffPublic,
    Error,
    SaleCreateRequest
  >({
    // No mutationFn here on purpose: inherit the persisted ["sales"] default from
    // query-client.ts so offline mutations are queued and replayed by key.
    mutationKey: ["sales"],
    onSuccess: (data) => {
      setSaleResult({
        totalThb: data.total_thb,
        totalCogsThb:
          "total_cogs_thb" in data ? data.total_cogs_thb : undefined,
      })
      setLines([])
      showSuccessToast("Sale completed.")
      // Return focus to the scan field so the next sale can begin immediately.
      scanRef.current?.focus()
    },
    onError: () => {
      showErrorToast("Could not complete the sale. Please try again.")
    },
  })

  // Gating on !isPending intentionally locks checkout while a sale is in flight
  // OR queued offline (isPaused keeps isPending true). This is the single-sale-
  // offline design: the spec only requires one queued sale surviving reload +
  // replay — multi-sale-offline cart-clearing is explicitly out of scope.
  const canCheckout =
    lines.length > 0 && customerId !== "" && !mutation.isPending

  const handleCheckout = useCallback(() => {
    if (!canCheckout) return
    // One idempotency key per attempt, captured into the variables passed to
    // mutate — an offline replay reuses the same key so the backend dedupes.
    const request = buildSaleRequest(lines, customerId, crypto.randomUUID())
    mutation.mutate(request)
  }, [canCheckout, lines, customerId, mutation])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Sale</h1>
        <p className="text-muted-foreground">
          Scan items to build a sale, then check out.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
        {/* Left pane: scan bar + cart lines */}
        <div className="space-y-4">
          <div className="space-y-2">
            {/* ScanInput carries its own aria-label="Scan barcode"; this is a
                visible caption, not a form-control label. */}
            <p className="text-sm font-medium">Scan item</p>
            <ScanInput ref={scanRef} onScan={resolve} />
            <CameraScanFallback onScan={resolve} />
            {/* Two statically-typed live regions: a dynamic aria-live value is
                unreliable across screen readers, so each politeness level gets
                its own always-present region. */}
            <p
              aria-live="assertive"
              className="text-muted-foreground min-h-5 text-sm"
            >
              {isError
                ? "Scan lookup failed. Try again."
                : notFound
                  ? "No item found for that code."
                  : ""}
            </p>
            <p
              aria-live="polite"
              className="text-muted-foreground min-h-5 text-sm"
            >
              {isSearching ? "Searching…" : ""}
            </p>
          </div>

          <ScanCart
            lines={lines}
            isAdmin={isAdmin}
            onQuantityChange={(key, qty) =>
              setLines((prev) => setLineQuantity(prev, key, qty))
            }
            onRemove={(key) => setLines((prev) => removeLine(prev, key))}
            saleResult={saleResult}
          />
        </div>

        {/* Right pane (desktop): customer + checkout */}
        <div className="hidden md:block">
          <CheckoutPanel
            customers={customers ?? []}
            customerId={customerId}
            onCustomerChange={setCustomerId}
            canCheckout={canCheckout}
            onCheckout={handleCheckout}
            isPaused={mutation.isPaused}
            isPending={mutation.isPending}
          />
        </div>
      </div>

      {/* Mobile/tablet: checkout pinned to a sticky footer. Rendered as a second
          CheckoutPanel instance (not a shared node) so its useId stays unique;
          only one slot is visible per breakpoint. */}
      <div className="bg-background sticky bottom-0 border-t py-4 md:hidden">
        <CheckoutPanel
          customers={customers ?? []}
          customerId={customerId}
          onCustomerChange={setCustomerId}
          canCheckout={canCheckout}
          onCheckout={handleCheckout}
          isPaused={mutation.isPaused}
          isPending={mutation.isPending}
        />
      </div>
    </div>
  )
}
