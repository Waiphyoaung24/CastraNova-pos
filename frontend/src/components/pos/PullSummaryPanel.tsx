import { ArrowLeft, CircleCheck, Undo2 } from "lucide-react"

import type { ProjectPullPublic } from "@/client/types.gen"
import {
  dateTime,
  itemName,
  STATE_LABEL,
  STATE_VARIANT,
  StockBar,
} from "@/components/pos/PullHistory"
import { StatCard } from "@/components/reports/StatCard"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useIsMobile } from "@/hooks/useMobile"
import { pullTotals, suppliedReturned } from "@/lib/pull-history"

interface PullSummaryPanelProps {
  /** A finished request: FULFILLED, SHORT or CANCELLED. */
  pull: ProjectPullPublic
  projectLabel: string
  customerLabel: string
  onBack: () => void
  canReturn: boolean
  onReturn: () => void
}

/**
 * Read-only view of a finished request: what was asked for, what went out,
 * what came back and what is still on site. Its one action is Return.
 */
export function PullSummaryPanel({
  pull,
  projectLabel,
  customerLabel,
  onBack,
  canReturn,
  onReturn,
}: PullSummaryPanelProps) {
  const totals = pullTotals([pull])
  const isMobile = useIsMobile()
  const closedAt =
    pull.state === "CANCELLED" ? pull.cancelled_at : pull.fulfilled_at

  return (
    <div className="space-y-6">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to requests
      </Button>

      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display text-xl font-semibold">{projectLabel}</h2>
          <Badge variant={STATE_VARIANT[pull.state]}>
            {STATE_LABEL[pull.state]}
          </Badge>
        </div>
        <p className="text-muted-foreground text-sm">{customerLabel}</p>
        <p className="text-muted-foreground text-sm">
          Requested <span className="num">{dateTime(pull.created_at)}</span>
          {closedAt ? (
            <>
              , {pull.state === "CANCELLED" ? "cancelled" : "given out"}{" "}
              <span className="num">{dateTime(closedAt)}</span>
            </>
          ) : null}
        </p>
      </header>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Allocated" value={totals.allocated} />
          <StatCard label="Supplied" value={totals.supplied} />
          <StatCard label="Returned" value={totals.returned} />
          <StatCard
            label="Still out"
            value={
              <span className={totals.stillOut > 0 ? "text-primary" : ""}>
                {totals.stillOut}
              </span>
            }
            hint="On site, not back in stock"
          />
        </div>
        <StockBar totals={totals} />
      </div>

      {pull.admin_notes ? (
        <p className="bg-muted/40 rounded-md px-4 py-3 text-sm">
          {pull.admin_notes}
        </p>
      ) : null}

      {isMobile ? (
        <ul className="bg-card divide-y rounded-lg border">
          {pull.lines.map((line) => {
            const out = line.returnable_qty ?? 0
            return (
              <li key={line.id} className="space-y-1 px-4 py-3 text-sm">
                <p className="font-medium">{itemName(line)}</p>
                <p className="text-muted-foreground text-xs">
                  Supplied{" "}
                  <span className="num text-foreground">
                    {line.fulfilled_qty}/{line.requested_qty ?? 1}
                  </span>
                  , {suppliedReturned(line)} returned,{" "}
                  <span className={out > 0 ? "text-primary font-semibold" : ""}>
                    {out} still out
                  </span>
                </p>
              </li>
            )
          })}
        </ul>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Allocated</TableHead>
              <TableHead className="text-right">Supplied</TableHead>
              <TableHead className="text-right">Returned</TableHead>
              <TableHead className="text-right">Still out</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pull.lines.map((line) => {
              const out = line.returnable_qty ?? 0
              return (
                <TableRow key={line.id}>
                  <TableCell className="font-medium">
                    {itemName(line)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {/* A UNIT line is one serial, so it carries no qty. */}
                    {line.requested_qty ?? 1}
                  </TableCell>
                  <TableCell className="num text-right">
                    {line.fulfilled_qty}
                  </TableCell>
                  <TableCell className="num text-right">
                    {suppliedReturned(line) || "—"}
                  </TableCell>
                  <TableCell
                    className={`num text-right font-semibold ${out > 0 ? "text-primary" : ""}`}
                  >
                    {out}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      {canReturn ? (
        <button
          type="button"
          onClick={onReturn}
          className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring flex h-11 w-full items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <Undo2 className="size-4" aria-hidden="true" />
          Return items to stock
        </button>
      ) : totals.supplied > 0 ? (
        <p className="text-success flex items-center justify-center gap-2 text-sm">
          <CircleCheck className="size-4" aria-hidden="true" />
          Everything that went out is back in stock.
        </p>
      ) : null}
    </div>
  )
}
