import { Minus, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { type TicketPartLine, ticketPartsSubtotalThb } from "@/lib/ticket-parts"

/** Post-close summary (authoritative price total from the backend response). */
export type TicketResultSummary = {
  partsCount: number
  totalThb: number
}

interface TicketPartsListProps {
  lines: TicketPartLine[]
  onQuantityChange: (key: string, quantity: number) => void
  onRemove: (key: string) => void
  /** Post-close summary; shown once a ticket has been closed. */
  ticketResult?: TicketResultSummary
}

/** Format a THB amount (display only — never cost). */
function formatThb(value: number): string {
  return `฿${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Presentational repair-parts cart. Controlled: every mutation is delegated to
 * the parent via callbacks; no data fetching, no router, no cost ever shown.
 */
export function TicketPartsList({
  lines,
  onQuantityChange,
  onRemove,
  ticketResult,
}: TicketPartsListProps) {
  const subtotal = ticketPartsSubtotalThb(lines)

  if (lines.length === 0) {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground py-8 text-center text-sm">
          Scan a part to add it to the ticket.
        </p>
        {ticketResult ? (
          <p className="text-center text-sm font-medium" aria-live="polite">
            {`Ticket closed — ${ticketResult.partsCount} part(s), ${formatThb(
              ticketResult.totalThb,
            )}.`}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Part</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-center">Qty</TableHead>
            <TableHead className="text-right">Line total</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.key}>
              <TableCell>
                <div className="font-medium">{line.modelName}</div>
                <div className="text-muted-foreground num text-xs">
                  {line.sku}
                </div>
              </TableCell>
              <TableCell className="num text-right">
                {formatThb(line.unitPriceThb)}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-11"
                    disabled={line.quantity <= 1}
                    aria-label={`Decrease quantity of ${line.sku}`}
                    onClick={() =>
                      onQuantityChange(line.key, line.quantity - 1)
                    }
                  >
                    <Minus />
                  </Button>
                  <span className="num w-8 text-center" aria-hidden="true">
                    {line.quantity}
                  </span>
                  <span className="sr-only" aria-live="polite">
                    {`${line.sku} quantity ${line.quantity}`}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-11"
                    aria-label={`Increase quantity of ${line.sku}`}
                    onClick={() =>
                      onQuantityChange(line.key, line.quantity + 1)
                    }
                  >
                    <Plus />
                  </Button>
                </div>
              </TableCell>
              <TableCell className="num text-right">
                {formatThb(line.unitPriceThb * line.quantity)}
              </TableCell>
              <TableCell>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="text-destructive size-11"
                  aria-label={`Remove ${line.sku}`}
                  onClick={() => onRemove(line.key)}
                >
                  <Trash2 />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex items-center justify-end gap-4">
        <span className="text-muted-foreground text-sm">Subtotal</span>
        <span className="num text-lg font-semibold">{formatThb(subtotal)}</span>
      </div>
    </div>
  )
}
