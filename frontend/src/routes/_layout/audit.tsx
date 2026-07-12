import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { ChevronsUpDown } from "lucide-react"
import { type KeyboardEvent, useId, useMemo, useState } from "react"

import {
  type AuditEntryPublic,
  AuditService,
  type MovementType,
  UsersService,
} from "@/client"
import { AuditDetailSheet } from "@/components/audit/AuditDetailSheet"
import { PageHeader } from "@/components/Common/PageHeader"
import { StatCard } from "@/components/reports/StatCard"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useIsMobile } from "@/hooks/useMobile"
import { useProductOptions } from "@/hooks/useProductOptions"
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
// The endpoint's default page size; a full page means there may be older rows.
const PAGE_LIMIT = 100
const EVENT_TYPES: MovementType[] = [
  "RECEIVED",
  "SOLD",
  "MAINTENANCE_OUT",
  "PROJECT_OUT",
  "ADJUSTED_OUT",
]

// Shared fixed-layout column widths so the header table and the scrolling body
// table stay aligned (sum to 100%; long text columns absorb the slack + truncate).
function AuditColGroup() {
  return (
    <colgroup>
      <col className="w-[17%]" /> {/* When */}
      <col className="w-[17%]" /> {/* By */}
      <col className="w-[16%]" /> {/* Event */}
      <col className="w-[15%]" /> {/* Model */}
      <col className="w-[12%]" /> {/* Source */}
      <col className="w-[5%]" /> {/* Qty */}
      <col className="w-[18%]" /> {/* Notes */}
    </colgroup>
  )
}

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

  const { data, isPending, isError } = useQuery({
    queryKey: ["audit", filter],
    queryFn: () => AuditService.listAudit(buildAuditQuery(filter)),
  })
  // Reference data to resolve UUIDs -> readable names (admin-only screen, so
  // both reads are permitted). Held steady; the ledger itself is the live data.
  const { data: users } = useQuery({
    queryKey: ["users"],
    queryFn: () => UsersService.readUsers(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: options } = useProductOptions()
  const skus = useMemo(() => (options ?? []).map((o) => o.sku), [options])

  const userList = users?.data ?? []
  const userNames = useMemo(
    () => new Map(userList.map((u) => [u.id, u.full_name || u.email])),
    [userList],
  )

  const rows = data?.data ?? []
  const summary = useMemo(() => summarizeAudit(rows), [rows])
  const capped = rows.length >= PAGE_LIMIT

  const actorName = (id: string) => userNames.get(id) ?? "Unknown user"
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
            onValueChange={(v) =>
              setFilter((f) => ({ ...f, eventType: v === ALL ? "" : v }))
            }
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
          <Select
            value={filter.actorUserId || ALL}
            onValueChange={(v) =>
              setFilter((f) => ({ ...f, actorUserId: v === ALL ? "" : v }))
            }
          >
            <SelectTrigger id={userSelectId} className="w-full sm:w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All users</SelectItem>
              {userList.map((u) => (
                <SelectItem key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fromId}>From</Label>
          <Input
            id={fromId}
            type="date"
            value={filter.fromDate}
            onChange={(e) =>
              setFilter((f) => ({ ...f, fromDate: e.target.value }))
            }
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={toId}>To</Label>
          <Input
            id={toId}
            type="date"
            value={filter.toDate}
            onChange={(e) =>
              setFilter((f) => ({ ...f, toDate: e.target.value }))
            }
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={skuSelectId}>SKU</Label>
          <SkuCombobox
            skuSelectId={skuSelectId}
            skus={skus ?? []}
            value={filter.sku}
            onChange={(v) => setFilter((f) => ({ ...f, sku: v }))}
          />
        </div>
      </div>

      {rows.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard
            label="Movements"
            value={summary.total}
            hint={capped ? "latest 100 shown" : undefined}
          />
          <StatCard label="Distinct users" value={summary.distinctActors} />
          <StatCard label="Receipts" value={summary.received} />
          <StatCard label="Outflows" value={summary.outflow} />
        </div>
      ) : null}

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
                  <dd className="text-foreground truncate">
                    {actorName(e.actor_user_id)}
                  </dd>
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
        <div className="overflow-hidden rounded-lg border">
          {/* Header lives in its own non-scrolling table so the body's vertical
              scrollbar runs beside the rows only, not the header. */}
          <table className="w-full table-fixed caption-bottom text-sm">
            <AuditColGroup />
            <TableHeader className="bg-muted">
              <TableRow className="hover:bg-transparent">
                <TableHead>When</TableHead>
                <TableHead>By</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
          </table>
          <ScrollArea type="auto" viewportClassName="max-h-[60vh]">
            <table className="w-full table-fixed caption-bottom text-sm">
              <AuditColGroup />
              <TableBody>
                {rows.map((e) => {
                  const source = movementSource(e)
                  return (
                    <TableRow
                      key={e.id}
                      {...rowProps(e)}
                      className="hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer outline-none"
                    >
                      <TableCell className="text-muted-foreground truncate">
                        {new Date(e.occurred_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="truncate font-medium">
                        {actorName(e.actor_user_id)}
                      </TableCell>
                      <TableCell className="truncate">{e.event_type}</TableCell>
                      <TableCell className="truncate">
                        <div className="truncate">
                          {e.product_model_name ?? itemRef(e)}
                        </div>
                        {e.product_sku ? (
                          <div className="text-muted-foreground truncate text-xs">
                            {e.product_sku}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="overflow-hidden">
                        {source ? (
                          <Badge variant="outline">{source.label}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="num text-right">
                        {e.quantity}
                      </TableCell>
                      <TableCell className="text-muted-foreground truncate">
                        {e.notes ?? "—"}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </table>
          </ScrollArea>
        </div>
      )}

      <AuditDetailSheet entry={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

// Single-use searchable SKU filter (Command + Popover). Matches and displays
// SKU only — the Model column already shows the model name.
function SkuCombobox({
  skuSelectId,
  skus,
  value,
  onChange,
}: {
  skuSelectId: string
  skus: string[]
  value: string
  onChange: (v: string) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={skuSelectId}
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between sm:w-48"
        >
          <span className="truncate">{value || "All SKUs"}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-0"
      >
        <Command>
          <CommandInput placeholder="Search SKU…" />
          <CommandList>
            <CommandEmpty>No SKU found.</CommandEmpty>
            <CommandGroup>
              <CommandItem
                value={ALL}
                onSelect={() => {
                  onChange("")
                  setOpen(false)
                }}
              >
                All SKUs
              </CommandItem>
              {skus.map((sku) => (
                <CommandItem
                  key={sku}
                  value={sku}
                  onSelect={() => {
                    onChange(sku)
                    setOpen(false)
                  }}
                >
                  {sku}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
