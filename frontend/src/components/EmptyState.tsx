import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  hint?: string
  className?: string
}

/**
 * Consistent placeholder for "nothing here yet" regions (carts, queues, tables).
 * A dashed, slightly-raised card reads as an intentional empty slot rather than
 * stray text floating in whitespace.
 */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "border-border/60 bg-card/30 flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <Icon className="text-muted-foreground/60 size-8" aria-hidden="true" />
      ) : null}
      <p className="text-foreground/80 text-sm font-medium">{title}</p>
      {hint ? <p className="text-muted-foreground text-sm">{hint}</p> : null}
    </div>
  )
}
