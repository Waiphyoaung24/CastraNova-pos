import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Barcode, Boxes } from "lucide-react"
import { Fragment, useState } from "react"

import { SearchService, type SkuConsumptionEventAdminPublic } from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { ScanField } from "@/components/ScanField"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { trackingModeLabel, unitStatusLabel } from "@/lib/labels"
import { requireAuth } from "@/lib/route-guards"

export const Route = createFileRoute("/_layout/search")({
  component: Search,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Search - CastraNova POS" }],
  }),
})

function consumptionLabel(eventType: string): string {
  switch (eventType) {
    case "SOLD":
      return "Sale"
    case "MAINTENANCE_OUT":
      return "Service"
    case "PROJECT_OUT":
      return "Project"
    case "ADJUSTED_OUT":
      return "Adjustment"
    default:
      return eventType
  }
}

function Search() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Search"
        description="Find one item by scanning its barcode, or find a product by its code."
      />

      <Tabs defaultValue="serial">
        <TabsList>
          <TabsTrigger value="serial">Find one item</TabsTrigger>
          <TabsTrigger value="sku">Find a product</TabsTrigger>
        </TabsList>
        <TabsContent value="serial" className="pt-4">
          <SerialSearch />
        </TabsContent>
        <TabsContent value="sku" className="pt-4">
          <SkuSearch />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function SerialSearch() {
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")

  const { data, isPending, isError } = useQuery({
    queryKey: ["search-serial", term],
    queryFn: () => SearchService.searchSerial({ barcode: term }),
    enabled: term !== "",
    retry: false,
  })

  return (
    <div className="space-y-4">
      <Alert>
        <Barcode />
        <AlertTitle>Track one physical unit</AlertTitle>
        <AlertDescription>
          Use this when you have an item in hand. Returns where the unit is
          right now and its full timeline — when it was received, moved, sold,
          or sent for service.
        </AlertDescription>
      </Alert>

      <ScanField
        label="Shop barcode"
        placeholder="Scan or type a shop barcode…"
        value={input}
        onValueChange={setInput}
        onScan={setTerm}
        submitLabel="Search"
      />
      <p className="text-muted-foreground text-sm">
        The barcode label we printed and stuck on the unit at receiving — not
        the maker's serial number.
      </p>

      {term === "" ? null : isPending ? (
        <p className="text-muted-foreground text-sm">Searching…</p>
      ) : isError || !data ? (
        <p className="text-muted-foreground text-sm">
          No unit found for “{term}”.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border p-4">
            <div className="num mb-3 text-base font-semibold">
              <span className="sr-only">Product code: </span>
              {data.sku}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt>
              <dd>{unitStatusLabel(data.current_state)}</dd>
              <dt className="text-muted-foreground">Shop barcode</dt>
              <dd className="num">{data.castranova_barcode}</dd>
              <dt className="text-muted-foreground">Maker's serial no.</dt>
              <dd className="num">{data.supplier_serial}</dd>
            </dl>
          </div>

          {data.movements.length === 0 ? null : (
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Show history
              </summary>
              <div className="pt-3">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Event</TableHead>
                      <TableHead>When</TableHead>
                      <TableHead>Location</TableHead>
                      <TableHead>By</TableHead>
                      <TableHead>Reference</TableHead>
                      <TableHead>Notes</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.movements.map((m, i) => (
                      <TableRow key={`${m.event_type}-${m.occurred_at}-${i}`}>
                        <TableCell>
                          <Badge variant="outline">{m.event_type}</Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {new Date(m.occurred_at).toLocaleString()}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.from_location_name && m.to_location_name
                            ? `${m.from_location_name} → ${m.to_location_name}`
                            : (m.to_location_name ??
                              m.from_location_name ??
                              "—")}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.actor_name ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.reference_label ?? m.reference_kind ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.notes ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function SkuSearch() {
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")

  const { data, isPending, isError } = useQuery({
    queryKey: ["search-sku", term],
    queryFn: () => SearchService.searchSku({ sku: term }),
    enabled: term !== "",
    retry: false,
  })

  return (
    <div className="space-y-4">
      <Alert>
        <Boxes />
        <AlertTitle>Check stock for a product line</AlertTitle>
        <AlertDescription>
          Use this to see all units of one product. Returns total quantity on
          hand, the open batches (oldest stock is used first), and a history of
          where the stock has gone.
        </AlertDescription>
      </Alert>

      <ScanField
        label="Product code (SKU)"
        placeholder="Scan or type a product code…"
        value={input}
        onValueChange={setInput}
        onScan={setTerm}
        submitLabel="Search"
      />
      <p className="text-muted-foreground text-sm">
        The product code shared by every unit of this item — the same code shown
        on the Products list.
      </p>

      {term === "" ? null : isPending ? (
        <p className="text-muted-foreground text-sm">Searching…</p>
      ) : isError || !data ? (
        <p className="text-muted-foreground text-sm">
          No SKU found for “{term}”.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border p-4">
            <div className="num mb-3 text-base font-semibold">
              <span className="sr-only">Product code: </span>
              {data.sku}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Type</dt>
              <dd>{trackingModeLabel(data.tracking_mode)}</dd>
              <dt className="text-muted-foreground">In stock</dt>
              <dd className="num">{data.total_on_hand}</dd>
            </dl>
          </div>
          {data.tracking_mode === "QUANTITY" ? (
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Show deliveries & history
              </summary>
              <div className="space-y-4 pt-3">
                <div>
                  <h3 className="mb-2 text-sm font-medium">Deliveries</h3>
                  {data.batches.length === 0 ? (
                    <p className="text-muted-foreground text-sm">No batches.</p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Batch</TableHead>
                          <TableHead>Received</TableHead>
                          <TableHead className="text-right">
                            Received qty
                          </TableHead>
                          <TableHead className="text-right">
                            Remaining
                          </TableHead>
                          <TableHead>Type</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {data.batches.map((b) => (
                          <TableRow key={b.batch_no}>
                            <TableCell className="num">{b.batch_no}</TableCell>
                            <TableCell className="text-muted-foreground">
                              {new Date(b.received_at).toLocaleDateString()}
                            </TableCell>
                            <TableCell className="num text-right">
                              {b.received_qty}
                            </TableCell>
                            <TableCell className="num text-right">
                              {b.remaining_qty}
                            </TableCell>
                            <TableCell>
                              {b.is_adjustment ? (
                                <Badge variant="outline">ADJ</Badge>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
                {data.tracking_mode === "QUANTITY"
                  ? (() => {
                      const consumption = data.consumption ?? []
                      return (
                        <div>
                          <h3 className="mb-2 text-sm font-medium">
                            Consumption
                          </h3>
                          {consumption.length === 0 ? (
                            <p className="text-muted-foreground text-sm">
                              No consumption yet.
                            </p>
                          ) : (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead>When</TableHead>
                                  <TableHead>Type</TableHead>
                                  <TableHead className="text-right">
                                    Qty
                                  </TableHead>
                                  <TableHead>Customer / Project</TableHead>
                                  <TableHead>By</TableHead>
                                  {"total_cost_thb" in consumption[0] ? (
                                    <TableHead className="text-right">
                                      COGS (฿)
                                    </TableHead>
                                  ) : null}
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {consumption.map((c, i) => (
                                  <Fragment
                                    key={`${c.reference_id}-${c.occurred_at}-${i}`}
                                  >
                                    <TableRow>
                                      <TableCell className="text-muted-foreground">
                                        {new Date(
                                          c.occurred_at,
                                        ).toLocaleString()}
                                      </TableCell>
                                      <TableCell>
                                        <Badge variant="outline">
                                          {consumptionLabel(c.event_type)}
                                        </Badge>
                                      </TableCell>
                                      <TableCell className="num text-right">
                                        {c.quantity}
                                      </TableCell>
                                      <TableCell className="text-muted-foreground">
                                        {c.project_name
                                          ? `${c.project_code ?? ""} ${c.project_name}`.trim()
                                          : (c.customer_name ?? "—")}
                                      </TableCell>
                                      <TableCell className="text-muted-foreground">
                                        {c.actor_name ?? "—"}
                                      </TableCell>
                                      {"total_cost_thb" in c ? (
                                        <TableCell className="num text-right">
                                          {
                                            (
                                              c as SkuConsumptionEventAdminPublic
                                            ).total_cost_thb
                                          }
                                        </TableCell>
                                      ) : null}
                                    </TableRow>
                                    {"draws" in c ? (
                                      <TableRow className="hover:bg-transparent">
                                        <TableCell colSpan={6} className="py-2">
                                          {/* admin column count */}
                                          <details className="text-sm">
                                            <summary className="cursor-pointer text-muted-foreground">
                                              FIFO draws
                                            </summary>
                                            <Table className="mt-2">
                                              <TableHeader>
                                                <TableRow>
                                                  <TableHead>Batch</TableHead>
                                                  <TableHead className="text-right">
                                                    Qty
                                                  </TableHead>
                                                  <TableHead className="text-right">
                                                    Unit cost (฿)
                                                  </TableHead>
                                                  <TableHead className="text-right">
                                                    Line total (฿)
                                                  </TableHead>
                                                </TableRow>
                                              </TableHeader>
                                              <TableBody>
                                                {(
                                                  c as SkuConsumptionEventAdminPublic
                                                ).draws.map((d) => (
                                                  <TableRow key={d.batch_no}>
                                                    <TableCell className="num">
                                                      {d.batch_no}
                                                    </TableCell>
                                                    <TableCell className="num text-right">
                                                      {d.quantity}
                                                    </TableCell>
                                                    <TableCell className="num text-right">
                                                      {d.unit_cost_thb}
                                                    </TableCell>
                                                    <TableCell className="num text-right">
                                                      {d.total_cost_thb}
                                                    </TableCell>
                                                  </TableRow>
                                                ))}
                                              </TableBody>
                                            </Table>
                                          </details>
                                        </TableCell>
                                      </TableRow>
                                    ) : null}
                                  </Fragment>
                                ))}
                              </TableBody>
                            </Table>
                          )}
                        </div>
                      )
                    })()
                  : null}
              </div>
            </details>
          ) : null}
        </div>
      )}
    </div>
  )
}
