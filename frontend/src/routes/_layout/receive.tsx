import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Printer, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  ProductsService,
  type ReceiveSerializedRequest,
  type ReceiveSerializedResponse,
  SuppliersService,
  type UnitPublic,
} from "@/client"
import { ScanInput } from "@/components/ScanInput"
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
import {
  addPiece,
  buildReceiveSerializedRequest,
  canSubmitSerialized,
  type DraftPiece,
  removePiece,
} from "@/lib/receive-form"
import { requireAdmin } from "@/lib/route-guards"

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
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Receive stock</h1>
        <p className="text-muted-foreground">
          Record incoming units from a supplier delivery.
        </p>
      </div>
      <Tabs defaultValue="serialized">
        <TabsList>
          <TabsTrigger value="serialized">Serialized</TabsTrigger>
          <TabsTrigger value="quantity">Quantity</TabsTrigger>
        </TabsList>
        <TabsContent value="serialized">
          <SerializedTab />
        </TabsContent>
        <TabsContent value="quantity">
          {/* Task 4.3 fills this tab. */}
          <p className="text-muted-foreground py-6">Coming soon.</p>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function SerializedTab() {
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [productId, setProductId] = useState("")
  const [supplierId, setSupplierId] = useState("")
  const [pieces, setPieces] = useState<DraftPiece[]>([])
  const [serial, setSerial] = useState("")
  const [cost, setCost] = useState("")
  const [received, setReceived] = useState<UnitPublic[]>([])
  const [announce, setAnnounce] = useState("")

  const serialInputRef = useRef<HTMLInputElement>(null)

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
      setAnnounce(`Received ${data.units.length} unit(s).`)
      showSuccessToast(`Received ${data.units.length} unit(s).`)
      serialInputRef.current?.focus()
    },
    onError: () => {
      setAnnounce("Receive failed.")
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
    setAnnounce(`Added piece ${serial.trim()}.`)
    setSerial("")
    setCost("")
    serialInputRef.current?.focus()
  }

  function handleRemovePiece(key: string, removedSerial: string) {
    setPieces((prev) => removePiece(prev, key))
    setAnnounce(`Removed piece ${removedSerial}.`)
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
        <div className="flex flex-col gap-2">
          <Label htmlFor="receive-product">Product</Label>
          <Select value={productId} onValueChange={setProductId}>
            <SelectTrigger
              id="receive-product"
              className="h-11 w-full"
              disabled={productsPending}
            >
              <SelectValue placeholder="Select a serialized product" />
            </SelectTrigger>
            <SelectContent>
              {serializedProducts.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.model_name} ({p.sku})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="receive-supplier">Supplier</Label>
          <Select value={supplierId} onValueChange={setSupplierId}>
            <SelectTrigger
              id="receive-supplier"
              className="h-11 w-full"
              disabled={suppliersPending}
            >
              <SelectValue placeholder="Select a supplier" />
            </SelectTrigger>
            <SelectContent>
              {suppliers.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add piece</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            {/* Plain visual label: ScanInput renders a bare input whose own
                aria-label covers screen readers, so no htmlFor association. */}
            <p className="text-sm font-medium">Scan serial</p>
            {/* Scanning fills the serial field below; the operator confirms the
                cost and presses Add. (No useScanLookup — units don't exist yet.) */}
            <ScanInput
              placeholder="Scan serial…"
              onScan={(code) => {
                setSerial(code)
                serialInputRef.current?.focus()
              }}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
            <div className="flex flex-col gap-2">
              <Label htmlFor="receive-serial">Supplier serial</Label>
              <Input
                id="receive-serial"
                ref={serialInputRef}
                className="num h-11"
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
              <Label htmlFor="receive-cost">Purchase cost (THB)</Label>
              <Input
                id="receive-cost"
                className="num h-11"
                inputMode="decimal"
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
              disabled={serial.trim() === "" || cost.trim() === ""}
            >
              Add piece
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Pieces ({pieces.length})</h2>
        {pieces.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No pieces added yet. Scan or type a serial above.
          </p>
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

function ReceivedUnits({ units }: { units: UnitPublic[] }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Received units ({units.length})</h2>
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
                <PrintLabelButton unitId={u.id} serial={u.supplier_serial} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function PrintLabelButton({
  unitId,
  serial,
}: {
  unitId: string
  serial: string
}) {
  const { showErrorToast } = useCustomToast()
  const objectUrlRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    }
  }, [])

  async function handlePrint() {
    // Sanctioned bare-fetch exception: the label is a binary PDF the generated
    // SDK types as `unknown`, so it can't reliably yield a usable blob. This is
    // the only authed binary download on the screen.
    const token = localStorage.getItem("access_token")
    if (!token) {
      showErrorToast("Session expired. Please log in again.")
      return
    }
    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_URL}/api/v1/receipts/serialized/${unitId}/label.pdf`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      if (!res.ok) {
        showErrorToast("Could not load label PDF.")
        return
      }
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
      const url = URL.createObjectURL(await res.blob())
      objectUrlRef.current = url
      const win = window.open(url, "_blank", "noopener,noreferrer")
      if (!win) {
        showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
        URL.revokeObjectURL(url)
        objectUrlRef.current = null
        return
      }
    } catch {
      showErrorToast("Could not load label PDF.")
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-11"
      aria-label={`Print label for serial ${serial}`}
      onClick={handlePrint}
    >
      <Printer className="size-4" />
      Print label
    </Button>
  )
}
