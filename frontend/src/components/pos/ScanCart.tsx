import { Minus, Plus, ScanLine, Trash2 } from "lucide-react"
import { EmptyState } from "@/components/EmptyState"
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
import {
  type CartLine,
  cartSubtotalThb,
  lineUnitPriceThb,
} from "@/lib/sale-cart"

/**
 * Post-sale totals from the backend (authoritative). COGS/margin are admin-only.
 * Values are decimal strings (Postgres NUMERIC) straight off the SDK's
 * `SalePublic`; parse with `Number(...)` at the display boundary.
 */
export type SaleResultSummary = {
  totalThb: string
  totalCogsThb?: string
}

interface ScanCartProps {
  lines: CartLine[]
  /** Gates the post-sale COGS/margin region (with `saleResult`). */
  isAdmin: boolean
  onQuantityChange: (key: string, quantity: number) => void
  onRemove: (key: string) => void
  /** Post-sale totals; enables the COGS/margin region for admins. */
  saleResult?: SaleResultSummary
  /** When set, the price cell becomes a tap target to request an override. */
  onPriceClick?: (key: string) => void
}

/**
 * Format a THB amount. Accepts a number (local subtotal) or a decimal string
 * (SDK total). Strings are parsed here at the boundary; an unparseable value
 * surfaces loudly as "฿NaN" rather than silently corrupting arithmetic.
 */
export function formatThb(value: number | string): string {
  const n = typeof value === "string" ? Number(value) : value
  return `฿${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/**
 * Presentational line-item cart for the Sale screen. Controlled: all mutations
 * are delegated to the parent via callbacks; no data fetching, no router.
 */
export function ScanCart({
  lines,
  isAdmin,
  onQuantityChange,
  onRemove,
  saleResult,
  onPriceClick,
}: ScanCartProps) {
  const subtotal = cartSubtotalThb(lines)
  const showCogs =
    isAdmin && saleResult != null && saleResult.totalCogsThb != null

  if (lines.length === 0) {
    return (
      <EmptyState
        icon={ScanLine}
        title="No items yet"
        hint="Scan an item to start a sale."
      />
    )
  }

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Item</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead className="text-center">Qty</TableHead>
            <TableHead className="text-right">Line total</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => {
            const isUnit = line.lineKind === "UNIT"
            const code = isUnit ? line.barcode : line.sku
            return (
              <TableRow key={line.key}>
                <TableCell className="num">{code}</TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {line.lineKind}
                </TableCell>
                <TableCell className="num text-right">
                  {/* While PENDING the price is plain text: re-requesting would
                      orphan the first request in the admin queue. */}
                  {onPriceClick && line.override?.state !== "PENDING" ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="num h-auto px-2 py-1 underline decoration-dotted underline-offset-4"
                      aria-label={`Change price of ${code}, ${formatThb(lineUnitPriceThb(line))}`}
                      onClick={() => onPriceClick(line.key)}
                    >
                      {formatThb(lineUnitPriceThb(line))}
                    </Button>
                  ) : (
                    formatThb(lineUnitPriceThb(line))
                  )}
                  {line.override?.state === "PENDING" ? (
                    <Badge
                      variant="outline"
                      className="mt-1 block w-fit border-amber-500 text-amber-600 dark:text-amber-400"
                    >
                      Pending approval ·{" "}
                      {formatThb(line.override.requestedPriceThb)}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-center gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={isUnit || line.quantity <= 1}
                      aria-label={`Decrease quantity of ${code}`}
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
                      {`${code} quantity ${line.quantity}`}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={isUnit}
                      aria-label={`Increase quantity of ${code}`}
                      onClick={() =>
                        onQuantityChange(line.key, line.quantity + 1)
                      }
                    >
                      <Plus />
                    </Button>
                  </div>
                </TableCell>
                <TableCell className="num text-right">
                  {formatThb(lineUnitPriceThb(line) * line.quantity)}
                </TableCell>
                <TableCell>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="text-destructive size-11"
                    aria-label={`Remove ${code}`}
                    onClick={() => onRemove(line.key)}
                  >
                    <Trash2 />
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <div className="space-y-1 text-right">
        <div className="flex items-center justify-end gap-4">
          <span className="text-muted-foreground text-sm">Subtotal</span>
          <span className="num text-lg font-semibold">
            {formatThb(subtotal)}
          </span>
        </div>

        {showCogs && saleResult.totalCogsThb != null ? (
          <>
            <div className="flex items-center justify-end gap-4">
              <span className="text-muted-foreground text-sm">COGS</span>
              <span className="num text-sm">
                {formatThb(saleResult.totalCogsThb)}
              </span>
            </div>
            <div className="flex items-center justify-end gap-4">
              <span className="text-muted-foreground text-sm">Margin</span>
              <span className="num text-sm">
                {formatThb(
                  Number(saleResult.totalThb) - Number(saleResult.totalCogsThb),
                )}
              </span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
