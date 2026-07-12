import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

interface ListShellProps {
  /**
   * A fetch is in flight while rows are already on screen (page turn, filter
   * change, background refetch). The rows stay mounted and dimmed rather than
   * unmounting, so the list never flashes an empty or "no results" state.
   */
  loading?: boolean
  className?: string
  children: ReactNode
}

/**
 * Loading affordance only. The scroll box lives inside `ListTable`, which
 * splits the header and body into separate tables so the row scrollbar never
 * runs beside the header.
 */
export function ListShell({
  loading = false,
  className,
  children,
}: ListShellProps) {
  return (
    <div className="relative" aria-busy={loading || undefined}>
      {loading && (
        <div className="bg-primary/15 absolute inset-x-0 top-0 z-20 h-0.5 overflow-hidden rounded-full">
          <div className="bg-primary animate-list-loading h-full w-1/3" />
        </div>
      )}
      <div
        className={cn(
          "transition-opacity",
          loading && "pointer-events-none opacity-60",
          className,
        )}
      >
        {children}
      </div>
    </div>
  )
}
