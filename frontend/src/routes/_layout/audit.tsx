import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { type KeyboardEvent, useId, useMemo, useState } from "react"

import {
  type AuditEntryPublic,
  AuditService,
  type MovementType,
} from "@/client"
import { AuditDetailSheet } from "@/components/audit/AuditDetailSheet"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { StatCard } from "@/components/reports/StatCard"
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
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { useProductOptions } from "@/hooks/useProductOptions"
import { useUserOptions } from "@/hooks/useUserOptions"
import {
  type AuditFilter,
  buildAuditQuery,
  movementSource,
  summarizeAudit,
} from "@/lib/audit"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only append-only audit ledger (FR-019). Read-only view of the unit/part
// movement ledgers with event-type, date, and actor filtering plus per-row
// who-did-what attribution.
export const Route = createFileRoute("/_layout/audit")({
  component: Audit,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Audit - CastraNova POS" }],
  }),
})

const ALL = "ALL"
const PAGE_SIZE = 100
const EVENT_TYPES: MovementType[] = [
  "RECEIVED",
  "SOLD",
  "MAINTENANCE_OUT",
  "PROJECT_OUT",
  "ADJUSTED_OUT",
]

// Column widths in header order (When, By, Event, Model, Source, Qty, Notes);
// sum to 100%. Long text columns (Model, Notes) absorb the slack + truncate.
const AUDIT_WIDTHS = ["17%", "17%", "16%", "15%", "12%", "5%", "18%"]

function Audit() {
  const isMobile = useIsMobile()
  const eventId = useId()
  const fromId = useId()
  const toId = useId()
  const userSelectId = useId()
  const skuSelectId = useId()
  const [filter, setFilter] = useState<AuditFilter>({
    eventType: "",
    fromDate: "",
    toDate: "",
    actorUserId: "",
    sku: "",
  })
  const [selected, setSelected] = useState<AuditEntryPublic | null>(null)
  const {
    page,
    pageSize,
    skip,
    limit,
    setPage,
    reset: resetPage,
  } = usePagination({ pageSize: PAGE_SIZE })

  const { data, isError, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["audit", filter, page],
    queryFn: () =>
      AuditService.listAudit({
        ...buildAuditQuery(filter),
        skip,
        limit,
      }),
    placeholderData: keepPreviousData,
  })
  const listLoading = isPlaceholderData || isFetching
  // No `activeOnly` — the ledger must still reach discontinued products, whose
  // historical movements live in the append-only history forever.
  const { data: options } = useProductOptions()
  const productOptions = options ?? []
  const { data: userOptionsData } = useUserOptions()
  const userOptions = userOptionsData ?? []

  const rows = data?.data ?? []
  const totalCount = data?.count ?? 0
  const summary = useMemo(() => summarizeAudit(rows), [rows])

  const actorName = (e: AuditEntryPublic) => e.actor_full_name ?? "Unknown user"
  const itemRef = (e: AuditEntryPublic) => {
    if (e.product_id) return e.product_sku ?? "Part"
    if (e.unit_id) return `Unit ·${e.unit_id.slice(0, 8)}`
    return "—"
  }
  // A row is a button: click or Enter/Space opens the detail drawer. Shared by
  // the desktop table row and the mobile card so both stay keyboard-accessible.
  const rowProps = (e: AuditEntryPublic) => ({
    role: "button" as const,
    tabIndex: 0,
    "aria-label": `View details: ${e.event_type} ${itemRef(e)}`,
    onClick: () => setSelected(e),
    onKeyDown: (ev: KeyboardEvent) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault()
        setSelected(e)
      }
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit ledger"
        description="Append-only stock-movement history — who moved what, and why. Read-only."
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={eventId}>Event</Label>
          <Select
            value={filter.eventType || ALL}
            onValueChange={(v) => {
              setFilter((f) => ({ ...f, eventType: v === ALL ? "" : v }))
              resetPage()
            }}
          >
            <SelectTrigger id={eventId} className="w-full sm:w-48">
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
          <Label htmlFor={userSelectId}>User</Label>
          <div className="w-full sm:w-56">
            <EntityCombobox
              id={userSelectId}
              items={userOptions}
              value={filter.actorUserId || undefined}
              onChange={(id) => {
                setFilter((f) => ({ ...f, actorUserId: id ?? "" }))
                resetPage()
              }}
              getKey={(u) => u.id}
              getLabel={(u) => u.full_name || u.email}
              placeholder="All users"
              searchPlaceholder="Search user…"
              emptyText="No user found."
              ariaLabel="Filter by user"
              allowClear
            />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fromId}>From</Label>
          <Input
            id={fromId}
            type="date"
            value={filter.fromDate}
            onChange={(e) => {
              setFilter((f) => ({ ...f, fromDate: e.target.value }))
              resetPage()
            }}
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={toId}>To</Label>
          <Input
            id={toId}
            type="date"
            value={filter.toDate}
            onChange={(e) => {
              setFilter((f) => ({ ...f, toDate: e.target.value }))
              resetPage()
            }}
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={skuSelectId}>SKU</Label>
          <div className="w-full sm:w-56">
            <EntityCombobox
              id={skuSelectId}
              items={productOptions}
              value={filter.sku || undefined}
              onChange={(sku) => {
                setFilter((f) => ({ ...f, sku: sku ?? "" }))
                resetPage()
              }}
              getKey={(o) => o.sku}
              getLabel={(o) => `${o.model_name} (${o.sku})`}
              placeholder="All SKUs"
              searchPlaceholder="Search SKU…"
              emptyText="No SKU found."
              ariaLabel="Filter by SKU"
              allowClear
            />
          </div>
        </div>
      </div>

      {totalCount > 0 ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Movements" value={totalCount} />
          <StatCard label="Distinct users" value={summary.distinctActors} />
          <StatCard label="Receipts" value={summary.received} />
          <StatCard label="Outflows" value={summary.outflow} />
        </div>
      ) : null}

      {!data && listLoading ? (
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
      ) : isMobile ? (
        <div className="space-y-3">
          {rows.map((e) => {
            const source = movementSource(e)
            return (
              <div
                key={e.id}
                {...rowProps(e)}
                className="bg-card hover:bg-muted/50 focus-visible:ring-ring cursor-pointer rounded-lg border p-4 outline-none focus-visible:ring-2"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">{e.event_type}</p>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      {new Date(e.occurred_at).toLocaleString()}
                    </p>
                  </div>
                  <span className="num shrink-0 font-semibold">
                    ×{e.quantity}
                  </span>
                </div>
                <dl className="text-muted-foreground mt-3 grid grid-cols-[5rem_1fr] gap-y-1 border-t pt-3 text-sm">
                  <dt>By</dt>
                  <dd className="text-foreground truncate">{actorName(e)}</dd>
                  <dt>Model</dt>
                  <dd className="text-foreground truncate">
                    <div className="truncate">
                      {e.product_model_name ?? itemRef(e)}
                    </div>
                    {e.product_sku ? (
                      <div className="text-muted-foreground truncate text-xs">
                        {e.product_sku}
                      </div>
                    ) : null}
                  </dd>
                  <dt>Source</dt>
                  <dd>
                    {source ? (
                      <Badge variant="outline">{source.label}</Badge>
                    ) : (
                      "—"
                    )}
                  </dd>
                </dl>
                {e.notes ? (
                  <p className="text-muted-foreground mt-2 text-sm">
                    {e.notes}
                  </p>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : (
        <ListShell loading={listLoading}>
          <ListTable
            widths={AUDIT_WIDTHS}
            minWidth={940}
            head={
              <TableRow className="hover:bg-transparent">
                <TableHead>When</TableHead>
                <TableHead>By</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            }
          >
            {rows.map((e) => {
              const source = movementSource(e)
              return (
                <TableRow
                  key={e.id}
                  {...rowProps(e)}
                  className="hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer outline-none"
                >
                  <TableCell className="text-muted-foreground">
                    {new Date(e.occurred_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="font-medium">{actorName(e)}</TableCell>
                  <TableCell>{e.event_type}</TableCell>
                  <TableCell>
                    <div className="truncate">
                      {e.product_model_name ?? itemRef(e)}
                    </div>
                    {e.product_sku ? (
                      <div className="text-muted-foreground truncate text-xs">
                        {e.product_sku}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    {source ? (
                      <Badge variant="outline">{source.label}</Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="num text-right">{e.quantity}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {e.notes ?? "—"}
                  </TableCell>
                </TableRow>
              )
            })}
          </ListTable>
        </ListShell>
      )}

      <PaginationControls
        total={totalCount}
        pageSize={pageSize}
        page={page}
        onPageChange={setPage}
      />

      <AuditDetailSheet entry={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
