import { SlidersHorizontal } from "lucide-react"
import { type ReactNode, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetTitle,
} from "@/components/ui/sheet"
import { useIsMobile } from "@/hooks/useMobile"
import { cn } from "@/lib/utils"

interface ListFiltersProps {
  /** Count of filters currently narrowing the list. Drives the badge and gates "Clear all". */
  activeCount: number
  /** Reset every filter to its default (and reset pagination). */
  onClear: () => void
  children: ReactNode
  className?: string
}

/**
 * On desktop, an unchanged flex-wrap filter row. On mobile, the same filter
 * controls move into a bottom sheet behind a "Filters" button, so the list
 * itself is the first thing visible instead of being pushed below a stack of
 * full-width inputs.
 */
export function ListFilters({
  activeCount,
  onClear,
  children,
  className,
}: ListFiltersProps) {
  const isMobile = useIsMobile()
  const [open, setOpen] = useState(false)

  if (!isMobile) {
    return (
      <div className={cn("flex flex-wrap items-end gap-3", className)}>
        {children}
      </div>
    )
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Button
        type="button"
        variant="outline"
        className="w-full justify-start"
        aria-label={activeCount ? `Filters, ${activeCount} active` : "Filters"}
        onClick={() => setOpen(true)}
      >
        <SlidersHorizontal className="h-4 w-4" />
        Filters
        {activeCount > 0 ? <Badge>{activeCount}</Badge> : null}
      </Button>
      <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto">
        <SheetTitle className="px-4 pt-4">Filters</SheetTitle>
        <div className="flex flex-col gap-4 px-4">{children}</div>
        <SheetFooter className="flex-row justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={activeCount === 0}
            onClick={onClear}
          >
            Clear all
          </Button>
          <Button type="button" onClick={() => setOpen(false)}>
            Done
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
