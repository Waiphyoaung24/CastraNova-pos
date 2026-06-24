import {
  ArrowDownLeft,
  ArrowDownToLine,
  ArrowRightLeft,
  ArrowUpRight,
  Boxes,
  Clock,
  type LucideIcon,
  Receipt,
  ShoppingCart,
  SlidersHorizontal,
  Tag,
  Wrench,
} from "lucide-react"
import { type ReactNode, useState } from "react"

import type { AuditEntryPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import useCustomToast from "@/hooks/useCustomToast"
import { type MovementSourceKind, movementSource } from "@/lib/audit"
import { openAuthedPdf } from "@/lib/print-pdf"
import { cn } from "@/lib/utils"

// Stock direction drives the one accent in the drawer: inbound movements read
// success-green, outbound read brand-gold. Colour is always paired with the
// "Stock in/out" caption + arrow so meaning never rests on hue alone.
type Direction = "in" | "out"

const EVENT_META: Record<string, { icon: LucideIcon; dir: Direction }> = {
  RECEIVED: { icon: ArrowDownToLine, dir: "in" },
  ADJUSTED_IN: { icon: SlidersHorizontal, dir: "in" },
  SOLD: { icon: ShoppingCart, dir: "out" },
  MAINTENANCE_OUT: { icon: Wrench, dir: "out" },
  PROJECT_OUT: { icon: Boxes, dir: "out" },
  ADJUSTED_OUT: { icon: SlidersHorizontal, dir: "out" },
}

const DIRECTION: Record<
  Direction,
  { tile: string; arrow: LucideIcon; label: string }
> = {
  in: {
    tile: "bg-success/10 text-success ring-success/25",
    arrow: ArrowDownLeft,
    label: "Stock in",
  },
  out: {
    tile: "bg-primary/10 text-primary ring-primary/25",
    arrow: ArrowUpRight,
    label: "Stock out",
  },
}

const SOURCE_ICONS: Record<MovementSourceKind, LucideIcon> = {
  sale: ShoppingCart,
  ticket: Wrench,
  pull: Boxes,
  adjustment: SlidersHorizontal,
}

/** "MAINTENANCE_OUT" -> "Maintenance out". */
function humanizeEvent(type: string): string {
  const words = type.replace(/_/g, " ").toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon
  title: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="text-muted-foreground flex items-center gap-1.5 text-xs font-semibold tracking-wider uppercase">
        <Icon className="size-3.5" />
        {title}
      </h3>
      <dl className="grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-2 text-sm">
        {children}
      </dl>
    </section>
  )
}

function Field({
  label,
  children,
  mono,
}: {
  label: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "num break-all" : "break-words"}>{children}</dd>
    </>
  )
}

/** Opens the sale's receipt PDF (authed) in a new tab. Disabled while the PDF
 * is in flight so a double-tap cannot spawn two tabs. */
function ReceiptButton({ saleId }: { saleId: string }) {
  const { showErrorToast } = useCustomToast()
  const [isOpening, setIsOpening] = useState(false)

  async function handleOpen() {
    setIsOpening(true)
    const result = await openAuthedPdf(`/sales/${saleId}/receipt.pdf`)
    setIsOpening(false)
    if (result === "no-token") {
      showErrorToast("Session expired. Please log in again.")
    } else if (result === "popup-blocked") {
      showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
    } else if (result === "fetch-failed") {
      showErrorToast("Could not load receipt PDF.")
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      className="h-11 w-full"
      aria-label="View receipt for this sale"
      disabled={isOpening}
      onClick={handleOpen}
    >
      <Receipt className="size-4" />
      {isOpening ? "Opening…" : "View receipt"}
    </Button>
  )
}

/** Right-side detail drawer for a single audit movement. The audit screen is
 * admin-only, so every hydrated field is safe to show; no cost/money is present
 * by design (the ledger stays non-financial). `entry` null keeps it closed. */
export function AuditDetailSheet({
  entry,
  onClose,
}: {
  entry: AuditEntryPublic | null
  onClose: () => void
}) {
  return (
    <Sheet
      open={entry !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto sm:max-w-md"
      >
        {entry ? <AuditDetailBody entry={entry} /> : null}
      </SheetContent>
    </Sheet>
  )
}

function AuditDetailBody({ entry }: { entry: AuditEntryPublic }) {
  const meta = EVENT_META[entry.event_type] ?? {
    icon: ArrowRightLeft,
    dir: "out" as Direction,
  }
  const dir = DIRECTION[meta.dir]
  const Icon = meta.icon
  const DirArrow = dir.arrow
  const source = movementSource(entry)
  const SourceIcon = source ? SOURCE_ICONS[source.kind] : null
  const when = new Date(entry.occurred_at).toLocaleString()
  const hasUnit = Boolean(
    entry.unit_castranova_barcode || entry.unit_supplier_serial,
  )

  return (
    <>
      <SheetHeader className="gap-3 pe-10">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-xl ring-1",
              dir.tile,
            )}
          >
            <Icon className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <SheetTitle className="text-lg leading-tight">
              {humanizeEvent(entry.event_type)}
            </SheetTitle>
            <SheetDescription className="flex items-center gap-1.5">
              <DirArrow className="size-3.5 shrink-0" />
              <span className="truncate">
                {dir.label} · {when}
              </span>
            </SheetDescription>
          </div>
        </div>
      </SheetHeader>

      <div className="flex flex-col gap-5 px-4 pt-2 pb-6">
        {/* Subject hero: what moved, and how many. */}
        <div className="bg-muted/40 rounded-lg border p-4">
          <div className="flex items-baseline justify-between gap-3">
            <div className="min-w-0">
              <p className="font-display truncate text-base font-semibold">
                {entry.product_model_name ?? "Unknown product"}
              </p>
              {entry.product_sku ? (
                <p className="num text-muted-foreground mt-0.5 text-xs">
                  {entry.product_sku}
                </p>
              ) : null}
            </div>
            <div className="shrink-0 text-right">
              <p className="num text-2xl leading-none font-semibold">
                ×{entry.quantity}
              </p>
              <p className="text-muted-foreground mt-1 text-[11px] tracking-wide uppercase">
                {entry.quantity === 1 ? "unit" : "units"}
              </p>
            </div>
          </div>
          {hasUnit ? (
            <dl className="mt-3 grid grid-cols-[7.5rem_1fr] gap-y-1.5 border-t pt-3 text-sm">
              {entry.unit_castranova_barcode ? (
                <Field label="Shop barcode" mono>
                  {entry.unit_castranova_barcode}
                </Field>
              ) : null}
              {entry.unit_supplier_serial ? (
                <Field label="Maker's serial" mono>
                  {entry.unit_supplier_serial}
                </Field>
              ) : null}
            </dl>
          ) : null}
        </div>

        <Section icon={Tag} title="Source">
          <Field label="Raised by">
            {source && SourceIcon ? (
              <Badge variant="secondary" className="gap-1">
                <SourceIcon className="size-3" />
                {source.label}
              </Badge>
            ) : (
              <span className="text-muted-foreground">Direct receipt</span>
            )}
          </Field>
          {entry.customer_name ? (
            <Field label="Customer">{entry.customer_name}</Field>
          ) : null}
        </Section>

        <Section icon={Clock} title="Who & when">
          <Field label="By">{entry.actor_full_name ?? "Unknown user"}</Field>
          <Field label="When">{when}</Field>
        </Section>

        {entry.notes ? (
          <div className="bg-muted/40 rounded-md border p-3 text-sm">
            <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
              Note
            </span>
            <p className="mt-1 break-words">{entry.notes}</p>
          </div>
        ) : null}

        {entry.sale_id ? <ReceiptButton saleId={entry.sale_id} /> : null}
      </div>
    </>
  )
}
