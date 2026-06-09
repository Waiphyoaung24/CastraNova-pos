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
import { type CartLine, cartSubtotalThb } from "@/lib/sale-cart"

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
}

/**
 * Format a THB amount. Accepts a number (local subtotal) or a decimal string
 * (SDK total). Strings are parsed here at the boundary; an unparseable value
 * surfaces loudly as "฿NaN" rather than silently corrupting arithmetic.
 */
function formatThb(value: number | string): string {
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
}: ScanCartProps) {
  const subtotal = cartSubtotalThb(lines)
  const showCogs =
    isAdmin && saleResult != null && saleResult.totalCogsThb != null

  if (lines.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center text-sm">
        Scan an item to start a sale.
      </p>
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
                  {formatThb(line.unitPriceThb)}
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
                  {formatThb(line.unitPriceThb * line.quantity)}
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
