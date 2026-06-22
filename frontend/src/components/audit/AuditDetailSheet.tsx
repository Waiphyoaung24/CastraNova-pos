import {
  ArrowDownToLine,
  ArrowRightLeft,
  Boxes,
  type LucideIcon,
  ShoppingCart,
  SlidersHorizontal,
  Wrench,
} from "lucide-react"
import type { ReactNode } from "react"

import type { AuditEntryPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { movementSource } from "@/lib/audit"

// One icon per movement type — the drawer's single visual "signature". Unknown
// types fall back to a neutral exchange glyph.
const EVENT_ICONS: Record<string, LucideIcon> = {
  RECEIVED: ArrowDownToLine,
  SOLD: ShoppingCart,
  MAINTENANCE_OUT: Wrench,
  PROJECT_OUT: Boxes,
  ADJUSTED_OUT: SlidersHorizontal,
  ADJUSTED_IN: SlidersHorizontal,
}

/** "MAINTENANCE_OUT" -> "Maintenance out". */
function humanizeEvent(type: string): string {
  const words = type.replace(/_/g, " ").toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
        {title}
      </h3>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2 text-sm">
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
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        {entry ? <AuditDetailBody entry={entry} /> : null}
      </SheetContent>
    </Sheet>
  )
}

function AuditDetailBody({ entry }: { entry: AuditEntryPublic }) {
  const Icon = EVENT_ICONS[entry.event_type] ?? ArrowRightLeft
  const source = movementSource(entry)
  const when = new Date(entry.occurred_at).toLocaleString()
  return (
    <>
      <SheetHeader>
        <div className="flex items-center gap-3">
          <span className="bg-muted text-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
            <Icon className="size-5" />
          </span>
          <div className="min-w-0">
            <SheetTitle>{humanizeEvent(entry.event_type)}</SheetTitle>
            <SheetDescription>{when}</SheetDescription>
          </div>
        </div>
      </SheetHeader>

      <div className="flex flex-col gap-6 px-4 pb-6">
        <Section title="Item">
          <Field label="Model">{entry.product_model_name ?? "—"}</Field>
          {entry.product_sku ? (
            <Field label="SKU" mono>
              {entry.product_sku}
            </Field>
          ) : null}
          {entry.unit_castranova_barcode ? (
            <Field label="Shop barcode" mono>
              {entry.unit_castranova_barcode}
            </Field>
          ) : null}
          {entry.unit_supplier_serial ? (
            <Field label="Maker's serial no." mono>
              {entry.unit_supplier_serial}
            </Field>
          ) : null}
          <Field label="Quantity" mono>
            ×{entry.quantity}
          </Field>
        </Section>

        <Section title="Source">
          <Field label="Raised by">
            {source ? (
              <Badge variant="outline">{source.label}</Badge>
            ) : (
              <span className="text-muted-foreground">Direct receipt</span>
            )}
          </Field>
          {entry.customer_name ? (
            <Field label="Customer">{entry.customer_name}</Field>
          ) : null}
          {entry.notes ? <Field label="Notes">{entry.notes}</Field> : null}
        </Section>

        <Section title="Who & when">
          <Field label="By">{entry.actor_full_name ?? "Unknown user"}</Field>
          <Field label="When">{when}</Field>
        </Section>
      </div>
    </>
  )
}
