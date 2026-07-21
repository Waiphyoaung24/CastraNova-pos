import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ShoppingCart } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type {
  ApiError,
  CustomerOption,
  PricingOverridePublic,
  SaleCreateRequest,
  SalePublic,
  SaleStaffPublic,
} from "@/client"
import { PricingOverridesService } from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { PageHeader } from "@/components/Common/PageHeader"
import { CustomerCreateDialog } from "@/components/pos/CustomerCreateDialog"
import { PriceOverrideDialog } from "@/components/pos/PriceOverrideDialog"
import { type SaleResultSummary, ScanCart } from "@/components/pos/ScanCart"
import { ScanField, type ScanFieldHandle } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { useCustomerOptions } from "@/hooks/useCustomerOptions"
import useCustomToast from "@/hooks/useCustomToast"
import { useProductOptions } from "@/hooks/useProductOptions"
import { useRole } from "@/hooks/useRole"
import { useScanLookup } from "@/hooks/useScanLookup"
import { queued } from "@/lib/query-client"
import { requireAuth } from "@/lib/route-guards"
import {
  addScanToCart,
  applyOverride,
  buildSaleRequest,
  cartHasPendingOverride,
  type CartLine,
  clearOverride,
  type LineOverride,
  removeLine,
  setLineQuantity,
} from "@/lib/sale-cart"
import type { Queued } from "@/lib/sync-producer"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/sale")({
  component: Sale,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Sale - CastraNova POS" }],
  }),
})

interface CheckoutPanelProps {
  customers: CustomerOption[]
  customerId: string
  onCustomerChange: (value: string) => void
  canCheckout: boolean
  onCheckout: () => void
  /** Drives the button label: queued (offline) vs. completing vs. idle. */
  isPaused: boolean
  isPending: boolean
  waitingForOverride: boolean
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
  waitingForOverride,
}: CheckoutPanelProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Customer</Label>
        <EntityCombobox
          items={customers}
          value={customerId || undefined}
          onChange={(value) => onCustomerChange(value ?? "")}
          getKey={(customer) => customer.id}
          getLabel={(customer) => customer.name}
          placeholder="Select a customer"
          searchPlaceholder="Search customers…"
          emptyText="No customers available"
          ariaLabel="Customer"
        />
        <CustomerCreateDialog onCreated={(c) => onCustomerChange(c.id)} />
      </div>

      <Button
        type="button"
        variant="cta"
        onClick={onCheckout}
        disabled={!canCheckout}
        className="h-11 w-full text-sm font-semibold"
      >
        {isPaused
          ? "Queued (offline)…"
          : isPending
            ? "Completing…"
            : "Complete sale"}
      </Button>
      {waitingForOverride ? (
        <p className="text-muted-foreground text-center text-sm">
          Waiting for override approval
        </p>
      ) : null}
    </div>
  )
}

function Sale() {
  const { isAdmin } = useRole()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [lines, setLines] = useState<CartLine[]>([])
  const [customerId, setCustomerId] = useState<string>("")
  const [saleResult, setSaleResult] = useState<SaleResultSummary | undefined>()
  const scanRef = useRef<ScanFieldHandle>(null)
  const [overrideKey, setOverrideKey] = useState<string | null>(null)
  const overrideLine = lines.find((l) => l.key === overrideKey) ?? null

  const { data: products } = useProductOptions({ activeOnly: true })
  const { data: customers } = useCustomerOptions()

  const priceMap = useMemo(
    () =>
      new Map((products ?? []).map((p) => [p.id, Number(p.retail_price_thb)])),
    [products],
  )

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
    ApiError,
    Queued<SaleCreateRequest>
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
    // Surface the server reason (e.g. "Product X is inactive", "Unit already
    // SOLD", insufficient stock) — these are user-actionable and retrying will
    // never clear them. Falls back to a generic message. Insufficient-stock
    // conflicts get a dedicated title so they don't read as a generic fault.
    onError: (err: ApiError) => {
      const detail = (err.body as { detail?: unknown } | undefined)?.detail
      if (
        err.status === 409 &&
        typeof detail === "string" &&
        detail.startsWith("Insufficient stock")
      ) {
        showErrorToast(detail, "Insufficient Stock")
        return
      }
      handleError.call(showErrorToast, err)
    },
  })

  const handleOverrideCreated = useCallback(
    (key: string, override: LineOverride) => {
      setLines((prev) => applyOverride(prev, key, override))
    },
    [],
  )

  const handleOverrideDecided = useCallback(
    (key: string, decided: PricingOverridePublic) => {
      if (decided.state === "APPROVED") {
        setLines((prev) =>
          applyOverride(prev, key, {
            id: decided.id,
            state: decided.state,
            requestedPriceThb: Number(decided.requested_price_thb),
          }),
        )
        showSuccessToast("Override approved.")
      } else if (decided.state === "REJECTED") {
        setLines((prev) => clearOverride(prev, key))
        showErrorToast("Override rejected — price reverted.")
      }
    },
    [showSuccessToast, showErrorToast],
  )

  // Gating on !isPending intentionally locks checkout while a sale is in flight
  // OR queued offline (isPaused keeps isPending true). This is the single-sale-
  // offline design: the spec only requires one queued sale surviving reload +
  // replay — multi-sale-offline cart-clearing is explicitly out of scope.
  const waitingForOverride = cartHasPendingOverride(lines)
  const canCheckout =
    lines.length > 0 &&
    customerId !== "" &&
    !mutation.isPending &&
    !waitingForOverride

  const handleCheckout = useCallback(() => {
    if (!canCheckout) return
    // One idempotency key per attempt, captured into the variables passed to
    // mutate — an offline replay reuses the same key so the backend dedupes.
    const request = buildSaleRequest(lines, customerId, crypto.randomUUID())
    mutation.mutate(queued(request, request.idempotency_key))
  }, [canCheckout, lines, customerId, mutation])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Sale"
        description="Scan items to build a sale, then check out."
      />

      <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
        {/* Left pane: scan bar + cart lines */}
        <div className="space-y-4">
          <Alert>
            <ShoppingCart />
            <AlertTitle>Build a counter sale</AlertTitle>
            <AlertDescription>
              Scan each item as you go — it's added to the cart and priced
              automatically. Choose a customer, then complete the sale to record
              it and draw the stock down.
            </AlertDescription>
          </Alert>

          <ScanField
            ref={scanRef}
            label="Scan item"
            clearOnScan
            onScan={resolve}
            status={
              // Two statically-typed live regions: a dynamic aria-live value is
              // unreliable across screen readers, so each politeness level gets
              // its own always-present region.
              <>
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
              </>
            }
          />
          <p className="text-muted-foreground text-sm">
            Scan the shop barcode on a unit, or a product code (SKU) for counted
            items.
          </p>

          <ScanCart
            lines={lines}
            isAdmin={isAdmin}
            onQuantityChange={(key, qty) =>
              setLines((prev) => setLineQuantity(prev, key, qty))
            }
            onRemove={(key) => setLines((prev) => removeLine(prev, key))}
            saleResult={saleResult}
            onPriceClick={setOverrideKey}
          />
          <PriceOverrideDialog
            line={overrideLine}
            onOpenChange={(open) => {
              if (!open) setOverrideKey(null)
            }}
            onCreated={handleOverrideCreated}
            targetKind="SALE_LINE"
          />
          {lines
            .filter((l) => l.override?.state === "PENDING")
            .map((l) =>
              l.override ? (
                <PendingOverrideWatcher
                  key={l.override.id}
                  overrideId={l.override.id}
                  lineKey={l.key}
                  onDecided={handleOverrideDecided}
                />
              ) : null,
            )}
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
            waitingForOverride={waitingForOverride}
          />
        </div>
      </div>

      {/* Mobile/tablet: checkout pinned to a sticky footer. Rendered as a second
          CheckoutPanel instance (not a shared node) so its useId stays unique;
          only one slot is visible per breakpoint. */}
      <div className="bg-background/90 supports-[backdrop-filter]:bg-background/75 sticky bottom-0 z-10 border-t py-4 backdrop-blur md:hidden">
        <CheckoutPanel
          customers={customers ?? []}
          customerId={customerId}
          onCustomerChange={setCustomerId}
          canCheckout={canCheckout}
          onCheckout={handleCheckout}
          isPaused={mutation.isPaused}
          isPending={mutation.isPending}
          waitingForOverride={waitingForOverride}
        />
      </div>
    </div>
  )
}

/**
 * Polls one PENDING override until the admin decides it (FR-010). One instance
 * is rendered per pending line — a component per query keeps hooks out of
 * loops. Unmounts once the decision is applied (the line stops being PENDING).
 */
function PendingOverrideWatcher({
  overrideId,
  lineKey,
  onDecided,
}: {
  overrideId: string
  lineKey: string
  onDecided: (key: string, decided: PricingOverridePublic) => void
}) {
  const { data } = useQuery({
    queryKey: ["pricing-override", overrideId],
    queryFn: () => PricingOverridesService.getPricingOverride({ overrideId }),
    // v5 function form — keep polling every 4s until a decision lands.
    refetchInterval: (query) =>
      query.state.data === undefined || query.state.data.state === "PENDING"
        ? 4_000
        : false,
  })

  // Toast fns from useCustomToast change identity every render, which would
  // churn onDecided and re-fire this effect on unrelated re-renders; a ref
  // keeps the latest callback without re-running the effect.
  const onDecidedRef = useRef(onDecided)
  onDecidedRef.current = onDecided

  useEffect(() => {
    if (data && data.state !== "PENDING") onDecidedRef.current(lineKey, data)
  }, [data, lineKey])

  return null
}
