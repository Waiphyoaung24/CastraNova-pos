import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Boxes, PackagePlus, Trash2 } from "lucide-react"
import { type ReactNode, useId, useRef, useState } from "react"

import {
  type ProductPublic,
  ProductsService,
  type ReceiptsReceiveQuantityResponse,
  ReceiptsService,
  type ReceiveQuantityRequest,
  type ReceiveSerializedRequest,
  type ReceiveSerializedResponse,
  SuppliersService,
  type UnitPublic,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { EmptyState } from "@/components/EmptyState"
import { PrintLabelButton } from "@/components/PrintLabelButton"
import { ScanField } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectEmpty,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import {
  addPiece,
  buildReceiveQuantityRequest,
  buildReceiveSerializedRequest,
  canSubmitQuantity,
  canSubmitSerialized,
  type DraftPiece,
  type QuantityDraft,
  removePiece,
} from "@/lib/receive-form"
import { requireAdmin } from "@/lib/route-guards"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/receive")({
  component: Receive,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Receive - CastraNova POS" }],
  }),
})

function Receive() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Receive stock"
        description="Record incoming units from a supplier delivery."
      />
      <Alert>
        <PackagePlus />
        <AlertTitle>Book in a delivery</AlertTitle>
        <AlertDescription>
          Use Serialized for items tracked by individual barcode — scan each
          serial and its cost, then receive to print unit labels. Use Quantity
          for bulk SKUs — enter the count and cost to open a new stock batch.
        </AlertDescription>
      </Alert>
      <Tabs defaultValue="serialized">
        <TabsList>
          <TabsTrigger value="serialized">Serialized</TabsTrigger>
          <TabsTrigger value="quantity">Quantity</TabsTrigger>
        </TabsList>
        <TabsContent value="serialized">
          <SerializedTab />
        </TabsContent>
        <TabsContent value="quantity">
          <QuantityTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

/** Full-width uppercase group heading that splits a form into scannable
 * sections (Delivery / Quantity & cost / Optional details). */
function SectionLabel({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <h3
      className={cn(
        "text-muted-foreground text-xs font-semibold tracking-wide uppercase",
        className,
      )}
    >
      {children}
    </h3>
  )
}

function SerializedTab() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const isMobile = useIsMobile()

  const [productId, setProductId] = useState("")
  const [supplierId, setSupplierId] = useState("")
  const [pieces, setPieces] = useState<DraftPiece[]>([])
  const [serial, setSerial] = useState("")
  const [cost, setCost] = useState("")
  const [received, setReceived] = useState<UnitPublic[]>([])
  const [announce, setAnnounce] = useState("")

  const serialInputRef = useRef<HTMLInputElement>(null)
  // Repeated identical announcements are a no-op for React (equal state bails),
  // so aria-live stays silent on a 2nd identical outcome. Toggle an invisible
  // trailing no-break space per announce so the DOM text node always changes;
  // the visible/sr-only text still reads naturally to a screen reader.
  const announceCountRef = useRef(0)
  function announceMessage(message: string) {
    announceCountRef.current += 1
    setAnnounce(message + " ".repeat(announceCountRef.current % 2))
  }

  // Reference data — same staleTime as other reference-data screens.
  const { data: products = [], isPending: productsPending } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: suppliers = [], isPending: suppliersPending } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => SuppliersService.readSuppliers(),
    staleTime: 5 * 60 * 1000,
  })

  const serializedProducts = products.filter(
    (p) => p.tracking_mode === "SERIALIZED",
  )

  // No mutationFn here: it inherits the persisted offline default registered
  // under ["receipts"] in query-client.ts (receiveSerialized), so paused
  // mutations replay after an offline reload.
  const mutation = useMutation<
    ReceiveSerializedResponse,
    Error,
    ReceiveSerializedRequest
  >({
    mutationKey: ["receipts"],
    onSuccess: (data) => {
      setReceived(data.units)
      setPieces([])
      setSerial("")
      setCost("")
      announceMessage(`Received ${data.units.length} unit(s).`)
      showSuccessToast(`Received ${data.units.length} unit(s).`)
      serialInputRef.current?.focus()
    },
    onError: () => {
      announceMessage("Receive failed.")
      showErrorToast("Could not receive units. Please retry.")
    },
  })

  function handleAddPiece() {
    if (serial.trim().length === 0) return
    setPieces((prev) =>
      addPiece(prev, {
        key: crypto.randomUUID(),
        supplierSerial: serial.trim(),
        purchaseCostThb: cost.trim(),
      }),
    )
    announceMessage(`Added piece ${serial.trim()}.`)
    setSerial("")
    setCost("")
    serialInputRef.current?.focus()
  }

  function handleRemovePiece(key: string, removedSerial: string) {
    setPieces((prev) => removePiece(prev, key))
    announceMessage(`Removed piece ${removedSerial}.`)
  }

  function handleSubmit() {
    // Generate the idempotency_key ONCE per attempt, captured in the mutate
    // variables so an offline replay reuses the same key (backend dedupes).
    const request = buildReceiveSerializedRequest(
      pieces,
      productId,
      supplierId,
      crypto.randomUUID(),
    )
    mutation.mutate(request)
  }

  const canSubmit = canSubmitSerialized(pieces, productId, supplierId)

  return (
    <div className="flex flex-col gap-6 py-4">
      <output className="sr-only">{announce}</output>

      <div className="grid gap-4 sm:grid-cols-2">
        <SectionLabel className="col-span-full">Delivery</SectionLabel>
        <div className="flex flex-col gap-2">
          <Label htmlFor="receive-product">
            Product
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Select value={productId} onValueChange={setProductId}>
            <SelectTrigger
              id="receive-product"
              className="h-11 w-full"
              aria-required="true"
              disabled={productsPending || mutation.isPending}
            >
              <SelectValue placeholder="Select a serialized product" />
            </SelectTrigger>
            <SelectContent>
              {serializedProducts.length ? (
                serializedProducts.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.model_name} ({p.sku})
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No serialized products available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="receive-supplier">
            Supplier
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Select value={supplierId} onValueChange={setSupplierId}>
            <SelectTrigger
              id="receive-supplier"
              className="h-11 w-full"
              aria-required="true"
              disabled={suppliersPending || mutation.isPending}
            >
              <SelectValue placeholder="Select a supplier" />
            </SelectTrigger>
            <SelectContent>
              {suppliers.length ? (
                suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No suppliers available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add piece</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* Scanning fills the serial field below; the operator confirms the
              cost and presses Add. (No useScanLookup — units don't exist yet.) */}
          <ScanField
            label="Scan serial"
            placeholder="Scan serial…"
            clearOnScan
            onScan={(code) => {
              setSerial(code)
              serialInputRef.current?.focus()
            }}
          />

          <div className="grid gap-4 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
            <div className="flex flex-col gap-2">
              <Label htmlFor="receive-serial">
                Supplier serial
                <span aria-hidden="true" className="text-destructive">
                  {" "}
                  *
                </span>
              </Label>
              <Input
                id="receive-serial"
                ref={serialInputRef}
                className="num h-11"
                aria-required="true"
                disabled={mutation.isPending}
                value={serial}
                onChange={(e) => setSerial(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    handleAddPiece()
                  }
                }}
                placeholder="Serial number"
                autoComplete="off"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="receive-cost">
                Purchase cost (THB)
                <span aria-hidden="true" className="text-destructive">
                  {" "}
                  *
                </span>
              </Label>
              <Input
                id="receive-cost"
                className="num h-11"
                inputMode="decimal"
                aria-required="true"
                disabled={mutation.isPending}
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                placeholder="0.00"
                autoComplete="off"
              />
            </div>
            <Button
              type="button"
              size="lg"
              className="h-11"
              onClick={handleAddPiece}
              disabled={
                serial.trim() === "" || cost.trim() === "" || mutation.isPending
              }
            >
              Add piece
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Pieces ({pieces.length})</h2>
        {pieces.length === 0 ? (
          <EmptyState
            icon={Boxes}
            title="No pieces added yet"
            hint="Scan or type a serial above, then add it."
          />
        ) : isMobile ? (
          <div className="space-y-3">
            {pieces.map((p) => (
              <div
                key={p.key}
                className="bg-card flex items-center justify-between gap-3 rounded-lg border p-4"
              >
                <div className="min-w-0">
                  <p className="num truncate font-medium">{p.supplierSerial}</p>
                  <p className="text-muted-foreground num text-sm">
                    ฿{p.purchaseCostThb}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-11 shrink-0"
                  aria-label={`Remove piece ${p.supplierSerial}`}
                  disabled={mutation.isPending}
                  onClick={() => handleRemovePiece(p.key, p.supplierSerial)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Supplier serial</TableHead>
                <TableHead>Cost (THB)</TableHead>
                <TableHead className="w-0" aria-label="Actions" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {pieces.map((p) => (
                <TableRow key={p.key}>
                  <TableCell className="num">{p.supplierSerial}</TableCell>
                  <TableCell className="num">{p.purchaseCostThb}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-11"
                      aria-label={`Remove piece ${p.supplierSerial}`}
                      disabled={mutation.isPending}
                      onClick={() => handleRemovePiece(p.key, p.supplierSerial)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div>
        <Button
          type="button"
          size="lg"
          className="h-11"
          disabled={!canSubmit || mutation.isPending}
          onClick={handleSubmit}
        >
          {mutation.isPending ? "Receiving…" : "Receive"}
        </Button>
      </div>

      {received.length > 0 && <ReceivedUnits units={received} />}
    </div>
  )
}

const EMPTY_QUANTITY_DRAFT: QuantityDraft = {
  productId: "",
  supplierId: "",
  receivedQty: "",
  purchaseCostThb: "",
  supplierBatchRef: "",
  expectedQty: "",
  note: "",
}

function QuantityTab() {
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [draft, setDraft] = useState<QuantityDraft>(EMPTY_QUANTITY_DRAFT)
  const [receivedBatch, setReceivedBatch] =
    useState<ReceiptsReceiveQuantityResponse | null>(null)
  const [announce, setAnnounce] = useState("")

  const fieldId = useId()
  // See SerializedTab: aria-live re-announce trick for repeated identical text.
  const announceCountRef = useRef(0)
  function announceMessage(message: string) {
    announceCountRef.current += 1
    setAnnounce(message + " ".repeat(announceCountRef.current % 2))
  }

  // Reference data — keyed identically to the Serialized tab, so TanStack Query
  // serves both tabs from one shared cache entry (no duplicate fetch).
  const { data: products = [], isPending: productsPending } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: suppliers = [], isPending: suppliersPending } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => SuppliersService.readSuppliers(),
    staleTime: 5 * 60 * 1000,
  })

  const quantityProducts = products.filter(
    (p) => p.tracking_mode === "QUANTITY",
  )

  // Online-only: quantity receive has its OWN mutationFn and is intentionally
  // NOT registered under the ["receipts"] offline default (that key replays
  // receiveSerialized only). No mutationKey here.
  const mutation = useMutation<
    ReceiptsReceiveQuantityResponse,
    Error,
    ReceiveQuantityRequest
  >({
    mutationFn: (body) =>
      ReceiptsService.receiveQuantity({ requestBody: body }),
    onSuccess: (batch) => {
      setReceivedBatch(batch)
      setDraft(EMPTY_QUANTITY_DRAFT)
      announceMessage(
        `Received ${batch.received_qty} unit(s) into batch ${batch.batch_no}.`,
      )
      showSuccessToast(`Received batch ${batch.batch_no}.`)
    },
    onError: () => {
      announceMessage("Receive failed.")
      showErrorToast("Could not receive batch. Please retry.")
    },
  })

  function patch(field: keyof QuantityDraft, value: string) {
    setDraft((prev) => ({ ...prev, [field]: value }))
  }

  function handleSubmit() {
    // Generate the idempotency_key ONCE per attempt; resubmitting the same key
    // lets the backend dedupe.
    mutation.mutate(buildReceiveQuantityRequest(draft, crypto.randomUUID()))
  }

  const canSubmit = canSubmitQuantity(draft)

  return (
    <form
      className="flex flex-col gap-6 py-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit && !mutation.isPending) handleSubmit()
      }}
    >
      <output className="sr-only">{announce}</output>

      <div className="grid gap-4 sm:grid-cols-2">
        <SectionLabel className="col-span-full">Delivery</SectionLabel>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-product`}>
            Product
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Select
            value={draft.productId}
            onValueChange={(v) => patch("productId", v)}
          >
            <SelectTrigger
              id={`${fieldId}-product`}
              className="h-11 w-full"
              aria-required="true"
              disabled={productsPending || mutation.isPending}
            >
              <SelectValue placeholder="Select a quantity product" />
            </SelectTrigger>
            <SelectContent>
              {quantityProducts.length ? (
                quantityProducts.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.model_name} ({p.sku})
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No quantity products available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-supplier`}>
            Supplier
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Select
            value={draft.supplierId}
            onValueChange={(v) => patch("supplierId", v)}
          >
            <SelectTrigger
              id={`${fieldId}-supplier`}
              className="h-11 w-full"
              aria-required="true"
              disabled={suppliersPending || mutation.isPending}
            >
              <SelectValue placeholder="Select a supplier" />
            </SelectTrigger>
            <SelectContent>
              {suppliers.length ? (
                suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No suppliers available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <SectionLabel className="col-span-full">
          Quantity &amp; cost
        </SectionLabel>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-qty`}>
            Received qty
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Input
            id={`${fieldId}-qty`}
            className="num h-11"
            inputMode="numeric"
            aria-required="true"
            disabled={mutation.isPending}
            value={draft.receivedQty}
            onChange={(e) => patch("receivedQty", e.target.value)}
            placeholder="0"
            autoComplete="off"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-cost`}>
            Purchase cost (THB)
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Input
            id={`${fieldId}-cost`}
            className="num h-11"
            inputMode="decimal"
            aria-required="true"
            disabled={mutation.isPending}
            value={draft.purchaseCostThb}
            onChange={(e) => patch("purchaseCostThb", e.target.value)}
            placeholder="0.00"
            autoComplete="off"
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <SectionLabel className="col-span-full">Optional details</SectionLabel>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-batch-ref`}>
            Supplier batch ref (optional)
          </Label>
          <Input
            id={`${fieldId}-batch-ref`}
            className="h-11"
            disabled={mutation.isPending}
            value={draft.supplierBatchRef}
            onChange={(e) => patch("supplierBatchRef", e.target.value)}
            placeholder="Supplier batch reference"
            autoComplete="off"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-expected`}>Expected qty (optional)</Label>
          <Input
            id={`${fieldId}-expected`}
            className="num h-11"
            inputMode="numeric"
            disabled={mutation.isPending}
            value={draft.expectedQty}
            onChange={(e) => patch("expectedQty", e.target.value)}
            placeholder="0"
            autoComplete="off"
          />
        </div>
        <div className="flex flex-col gap-2 sm:col-span-2">
          <Label htmlFor={`${fieldId}-note`}>Note (optional)</Label>
          <Input
            id={`${fieldId}-note`}
            className="h-11"
            disabled={mutation.isPending}
            value={draft.note}
            onChange={(e) => patch("note", e.target.value)}
            placeholder="Optional note"
            autoComplete="off"
          />
        </div>
      </div>

      <div>
        <Button
          type="submit"
          size="lg"
          className="h-11"
          disabled={!canSubmit || mutation.isPending}
        >
          {mutation.isPending ? "Receiving…" : "Receive"}
        </Button>
      </div>
      {receivedBatch ? (
        // key by batch id so a second receive remounts the block, re-seeding
        // the qty input's mount-only defaultQty to the new batch's quantity.
        <ReceivedBatchLabels
          key={receivedBatch.id}
          batch={receivedBatch}
          products={quantityProducts}
        />
      ) : null}
    </form>
  )
}

function ReceivedUnits({ units }: { units: UnitPublic[] }) {
  const isMobile = useIsMobile()
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Received units ({units.length})</h2>
      {isMobile ? (
        <div className="space-y-3">
          {units.map((u) => (
            <div
              key={u.id}
              className="bg-card flex items-center justify-between gap-3 rounded-lg border p-4"
            >
              <div className="min-w-0">
                <p className="num truncate font-medium">
                  {u.castranova_barcode}
                </p>
                <p className="num text-muted-foreground truncate text-sm">
                  {u.supplier_serial}
                </p>
              </div>
              <PrintLabelButton
                target={{
                  kind: "unit",
                  unitId: u.id,
                  serial: u.supplier_serial,
                }}
              />
            </div>
          ))}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>CastraNova barcode</TableHead>
              <TableHead>Supplier serial</TableHead>
              <TableHead className="w-0" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {units.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="num">{u.castranova_barcode}</TableCell>
                <TableCell className="num">{u.supplier_serial}</TableCell>
                <TableCell className="text-right">
                  <PrintLabelButton
                    target={{
                      kind: "unit",
                      unitId: u.id,
                      serial: u.supplier_serial,
                    }}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function ReceivedBatchLabels({
  batch,
  products,
}: {
  batch: ReceiptsReceiveQuantityResponse
  products: ProductPublic[]
}) {
  const product = products.find((p) => p.id === batch.product_id)
  if (!product) return null
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Print SKU labels</h2>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-muted-foreground text-sm">
          {product.sku} — batch {batch.batch_no}
        </span>
        <PrintLabelButton
          target={{ kind: "sku", productId: product.id, sku: product.sku }}
          defaultQty={Math.min(batch.received_qty, 1000)}
        />
      </div>
    </div>
  )
}
