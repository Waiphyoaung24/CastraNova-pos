import { type KeyboardEvent, useEffect, useRef } from "react"

import {
  type Bounds,
  buildMonthGrid,
  buildYearGrid,
  formatDisplay,
  formatMonthDisplay,
  type NavKey,
  nextFocusDate,
  nextFocusMonth,
  WEEKDAYS,
} from "@/lib/date-field"
import { cn } from "@/lib/utils"

// Presentational calendar grids. They own roving focus and key handling but no
// open/close state — `date-picker.tsx` composes them into a popover. Keeping
// the split means the grid can be restyled without touching trigger behaviour.

const NAV_KEYS = new Set<string>([
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
  "PageUp",
  "PageDown",
])

// size-11 on touch, size-9 from `sm` up — WCAG target size where it matters.
const CELL =
  "inline-flex items-center justify-center rounded-md text-sm outline-none " +
  "transition-colors hover:bg-accent hover:text-accent-foreground " +
  "focus-visible:ring-ring/50 focus-visible:ring-[3px] " +
  "disabled:pointer-events-none disabled:text-muted-foreground/40"

/** Focus whichever cell the parent says is focused, whenever that changes.
 * The ref is attached conditionally to that one cell, so it always points at
 * the right element by the time the effect runs. */
function useRovingFocus(focused: string) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [focused])
  return ref
}

type CalendarGridProps = {
  /** The visible month, `YYYY-MM`. */
  month: string
  /** The selected date, `YYYY-MM-DD`, or `""` when the field is empty. */
  selected: string
  /** The date holding `tabIndex={0}`. */
  focused: string
  bounds?: Bounds
  onSelect: (iso: string) => void
  onFocusedChange: (iso: string) => void
}

export function CalendarGrid({
  month,
  selected,
  focused,
  bounds = {},
  onSelect,
  onFocusedChange,
}: CalendarGridProps) {
  const cells = buildMonthGrid(month, bounds)
  const weeks = Array.from({ length: 6 }, (_, w) =>
    cells.slice(w * 7, w * 7 + 7),
  )
  const focusRef = useRovingFocus(focused)

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!NAV_KEYS.has(event.key)) return
    event.preventDefault()
    onFocusedChange(
      nextFocusDate(focused, event.key as NavKey, bounds, event.shiftKey),
    )
  }

  return (
    <div role="grid" aria-label="Calendar" onKeyDown={handleKeyDown}>
      <div role="row" className="flex">
        {WEEKDAYS.map((weekday) => (
          <div
            key={weekday}
            role="columnheader"
            className="inline-flex size-11 items-center justify-center text-xs text-muted-foreground sm:size-9"
          >
            {weekday}
          </div>
        ))}
      </div>
      {weeks.map((week) => (
        <div key={week[0].iso} role="row" className="flex">
          {week.map((cell) => (
            <button
              key={cell.iso}
              ref={cell.iso === focused ? focusRef : undefined}
              type="button"
              role="gridcell"
              aria-label={formatDisplay(cell.iso)}
              aria-selected={cell.iso === selected}
              aria-disabled={cell.disabled}
              disabled={cell.disabled}
              tabIndex={cell.iso === focused ? 0 : -1}
              onClick={() => onSelect(cell.iso)}
              className={cn(
                CELL,
                "size-11 sm:size-9",
                cell.outside && "text-muted-foreground/50",
                cell.today && cell.iso !== selected && "ring-1 ring-ring",
                cell.iso === selected &&
                  "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
              )}
            >
              {cell.day}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

type MonthGridProps = {
  year: number
  /** The selected month, `YYYY-MM`, or `""`. */
  selected: string
  /** The month holding `tabIndex={0}`, `YYYY-MM`. */
  focused: string
  bounds?: Bounds
  onSelect: (ym: string) => void
  onFocusedChange: (ym: string) => void
}

export function MonthGrid({
  year,
  selected,
  focused,
  bounds = {},
  onSelect,
  onFocusedChange,
}: MonthGridProps) {
  const cells = buildYearGrid(year, bounds)
  const rows = Array.from({ length: 4 }, (_, r) => cells.slice(r * 3, r * 3 + 3))
  const focusRef = useRovingFocus(focused)

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!NAV_KEYS.has(event.key)) return
    event.preventDefault()
    onFocusedChange(nextFocusMonth(focused, event.key as NavKey, bounds))
  }

  return (
    <div
      role="grid"
      aria-label="Months"
      onKeyDown={handleKeyDown}
      className="grid w-63 grid-cols-3 gap-1"
    >
      {rows.map((row) => (
        // `contents` keeps the CSS grid flat while preserving the row role.
        <div key={row[0].ym} role="row" className="contents">
          {row.map((cell) => (
            <button
              key={cell.ym}
              ref={cell.ym === focused ? focusRef : undefined}
              type="button"
              role="gridcell"
              aria-label={formatMonthDisplay(cell.ym)}
              aria-selected={cell.ym === selected}
              aria-disabled={cell.disabled}
              disabled={cell.disabled}
              tabIndex={cell.ym === focused ? 0 : -1}
              onClick={() => onSelect(cell.ym)}
              className={cn(
                CELL,
                "h-11 w-full sm:h-9",
                cell.current && cell.ym !== selected && "ring-1 ring-ring",
                cell.ym === selected &&
                  "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
              )}
            >
              {cell.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}
