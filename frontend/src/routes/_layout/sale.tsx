import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useId, useMemo, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  type ProductPublic,
  ProductsService,
  type SaleCreateRequest,
  type SalePublic,
  type SaleStaffPublic,
} from "@/client"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import { type SaleResultSummary, ScanCart } from "@/components/pos/ScanCart"
import { ScanInput } from "@/components/ScanInput"
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

/** A walk-in customer is the default counter sale when no specific customer is chosen. */
function findWalkIn(customers: CustomerPublic[]): CustomerPublic | undefined {
  return customers.find((c) => /walk[\s-]?in/i.test(c.name))
}

function Sale() {
  const { isAdmin } = useRole()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const customerSelectId = useId()

  const [lines, setLines] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState<string>("")
  const [saleResult, setSaleResult] = useState<SaleResultSummary | undefined>()

  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
  })

  const priceMap = useMemo(
    () =>
      new Map(
        (products ?? []).map((p: ProductPublic) => [
          p.id,
          Number(p.retail_price_thb),
        ]),
      ),
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
    },
    onError: () => {
      showErrorToast("Could not complete the sale. Please try again.")
    },
  })

  const canCheckout =
    lines.length > 0 && customerId !== "" && !mutation.isPending

  function handleCheckout() {
    if (!canCheckout) return
    // One idempotency key per attempt, captured into the variables passed to
    // mutate — an offline replay reuses the same key so the backend dedupes.
    const request = buildSaleRequest(lines, customerId, crypto.randomUUID())
    mutation.mutate(request)
  }

  const scanStatus = isError
    ? "Scan lookup failed. Try again."
    : notFound
      ? "No item found for that code."
      : isSearching
        ? "Searching…"
        : ""

  const checkoutPanel = (
    <div className="space-y-4">
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

      <button
        type="button"
        onClick={handleCheckout}
        disabled={!canCheckout}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {mutation.isPending ? "Completing…" : "Complete sale"}
      </button>
    </div>
  )

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
            <ScanInput onScan={resolve} />
            <CameraScanFallback onScan={resolve} />
            <p
              aria-live={isError || notFound ? "assertive" : "polite"}
              className="text-muted-foreground min-h-5 text-sm"
            >
              {scanStatus}
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
        <div className="hidden md:block">{checkoutPanel}</div>
      </div>

      {/* Mobile/tablet: checkout pinned to a sticky footer */}
      <div className="bg-background sticky bottom-0 border-t py-4 md:hidden">
        {checkoutPanel}
      </div>
    </div>
  )
}
