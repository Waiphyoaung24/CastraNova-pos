import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { type FormEvent, Fragment, useState } from "react"

import { SearchService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Search</h1>
        <p className="text-muted-foreground">
          Look up a serialized unit's history or a SKU's batches.
        </p>
      </div>

      <Tabs defaultValue="serial">
        <TabsList>
          <TabsTrigger value="serial">Serial</TabsTrigger>
          <TabsTrigger value="sku">SKU</TabsTrigger>
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

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          placeholder="Scan or type a CastraNova barcode…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="w-full sm:w-80"
        />
        <Button type="submit" disabled={input.trim() === ""}>
          Search
        </Button>
      </form>

      {term === "" ? null : isPending ? (
        <p className="text-muted-foreground text-sm">Searching…</p>
      ) : isError || !data ? (
        <p className="text-muted-foreground text-sm">
          No unit found for “{term}”.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <span className="num font-medium">{data.castranova_barcode}</span>
            <span className="text-muted-foreground">
              {data.sku} · serial {data.supplier_serial}
            </span>
            <Badge variant="secondary">{data.current_state}</Badge>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium">History</h3>
            {data.movements.length === 0 ? (
              <p className="text-muted-foreground text-sm">No movements.</p>
            ) : (
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
                          : (m.to_location_name ?? m.from_location_name ?? "—")}
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
            )}
          </div>
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

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          placeholder="Scan or type a SKU…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="w-full sm:w-80"
        />
        <Button type="submit" disabled={input.trim() === ""}>
          Search
        </Button>
      </form>

      {term === "" ? null : isPending ? (
        <p className="text-muted-foreground text-sm">Searching…</p>
      ) : isError || !data ? (
        <p className="text-muted-foreground text-sm">
          No SKU found for “{term}”.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <span className="num font-medium">{data.sku}</span>
            <Badge variant="secondary">{data.tracking_mode}</Badge>
            <span className="text-muted-foreground">
              On hand: <span className="num">{data.total_on_hand}</span>
            </span>
          </div>
          {data.tracking_mode === "QUANTITY" ? (
            <div>
              <h3 className="mb-2 text-sm font-medium">Batches</h3>
              {data.batches.length === 0 ? (
                <p className="text-muted-foreground text-sm">No batches.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Batch</TableHead>
                      <TableHead>Received</TableHead>
                      <TableHead className="text-right">Received qty</TableHead>
                      <TableHead className="text-right">Remaining</TableHead>
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
          ) : null}
          {data.tracking_mode === "QUANTITY"
            ? (() => {
                const consumption = data.consumption ?? []
                return (
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Consumption</h3>
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
                            <TableHead className="text-right">Qty</TableHead>
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
                          {consumption.map((c) => (
                            <Fragment
                              key={`${c.reference_id}-${c.occurred_at}`}
                            >
                              <TableRow>
                                <TableCell className="text-muted-foreground">
                                  {new Date(c.occurred_at).toLocaleString()}
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
                                      (c as { total_cost_thb: string })
                                        .total_cost_thb
                                    }
                                  </TableCell>
                                ) : null}
                              </TableRow>
                              {"draws" in c ? (
                                <TableRow className="hover:bg-transparent">
                                  <TableCell colSpan={6} className="py-2">
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
                                            c as {
                                              draws: Array<{
                                                batch_no: string
                                                quantity: number
                                                unit_cost_thb: string
                                                total_cost_thb: string
                                              }>
                                            }
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
      )}
    </div>
  )
}
