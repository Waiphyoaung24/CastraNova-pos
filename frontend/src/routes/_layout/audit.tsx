import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { AuditService, type MovementType } from "@/client"
import { Badge } from "@/components/ui/badge"
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
import { type AuditFilter, buildAuditQuery } from "@/lib/audit"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only append-only audit ledger (FR-019). Read-only view of the unit/part
// movement ledgers with event-type + date filtering.
export const Route = createFileRoute("/_layout/audit")({
  component: Audit,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Audit - CastraNova POS" }],
  }),
})

const ALL = "ALL"
const EVENT_TYPES: MovementType[] = [
  "RECEIVED",
  "SOLD",
  "MAINTENANCE_OUT",
  "PROJECT_OUT",
  "ADJUSTED_OUT",
]

function Audit() {
  const [filter, setFilter] = useState<AuditFilter>({
    eventType: "",
    fromDate: "",
    toDate: "",
  })

  const { data, isPending, isError } = useQuery({
    queryKey: ["audit", filter],
    queryFn: () => AuditService.listAudit(buildAuditQuery(filter)),
  })

  const rows = data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Audit ledger</h1>
        <p className="text-muted-foreground">
          Append-only stock-movement history. Read-only.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="event">Event</Label>
          <Select
            value={filter.eventType || ALL}
            onValueChange={(v) =>
              setFilter((f) => ({ ...f, eventType: v === ALL ? "" : v }))
            }
          >
            <SelectTrigger id="event" className="w-full sm:w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All events</SelectItem>
              {EVENT_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="from">From</Label>
          <Input
            id="from"
            type="date"
            value={filter.fromDate}
            onChange={(e) =>
              setFilter((f) => ({ ...f, fromDate: e.target.value }))
            }
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="to">To</Label>
          <Input
            id="to"
            type="date"
            value={filter.toDate}
            onChange={(e) =>
              setFilter((f) => ({ ...f, toDate: e.target.value }))
            }
            className="w-full sm:w-44"
          />
        </div>
      </div>

      {isPending ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Loading…
        </p>
      ) : isError ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Could not load the audit ledger.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          No movements match the filter.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Ledger</TableHead>
              <TableHead>Event</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead>Notes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="text-muted-foreground">
                  {new Date(e.occurred_at).toLocaleString()}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{e.ledger}</Badge>
                </TableCell>
                <TableCell className="font-medium">{e.event_type}</TableCell>
                <TableCell className="num text-right">{e.quantity}</TableCell>
                <TableCell className="text-muted-foreground max-w-xs truncate">
                  {e.notes ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
