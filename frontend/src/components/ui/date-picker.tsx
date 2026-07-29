import { CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { CalendarGrid, MonthGrid } from "@/components/ui/calendar"
import { inputClassName } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  addMonths,
  clampDate,
  clampMonth,
  formatDisplay,
  formatMonthDisplay,
  monthOf,
  todayISO,
} from "@/lib/date-field"
import { cn } from "@/lib/utils"

// Click-to-open date and month pickers. There is deliberately no typed text
// entry: parsing free-form dates forces a dd/mm-vs-mm/dd and a two-digit-year
// assumption, both of which are silent-wrong-date hazards on a screen that
// backdates inventory receipts. Radix Popover supplies focus containment,
// Escape, outside-click dismissal and focus return to the trigger.

type FieldTriggerProps = {
  id?: string
  /** id of the visible `<Label>`. The trigger names itself from that label AND
   * its own text, so a screen reader announces "Receive date 25 Jul 2026"
   * rather than a bare date. A `<button>` takes its accessible name from its
   * contents, so a plain `<Label htmlFor>` would otherwise be ignored. */
  labelledBy?: string
  /** Rendered field text — either the formatted value or the placeholder. */
  label: string
  isPlaceholder: boolean
  disabled?: boolean
  required?: boolean
  className?: string
  onOpen: () => void
}

/** The trigger reuses `inputClassName` so it is pixel-identical to every other
 * field. Radix adds `aria-haspopup="dialog"` and `aria-expanded` itself. */
function FieldTrigger({
  id,
  labelledBy,
  label,
  isPlaceholder,
  disabled,
  required,
  className,
  onOpen,
}: FieldTriggerProps) {
  return (
    <PopoverTrigger asChild>
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-required={required || undefined}
        aria-labelledby={labelledBy && id ? `${labelledBy} ${id}` : undefined}
        onKeyDown={(event) => {
          // APG: Down (and Alt+Down) opens the dialog. Enter and Space already
          // activate the button natively.
          if (event.key === "ArrowDown") {
            event.preventDefault()
            onOpen()
          }
        }}
        className={cn(
          inputClassName,
          "flex items-center justify-between gap-2 text-left font-normal",
          className,
        )}
      >
        <span className={cn(isPlaceholder && "text-muted-foreground")}>
          {label}
        </span>
        <CalendarIcon
          aria-hidden="true"
          className="size-4 shrink-0 opacity-60"
        />
      </button>
    </PopoverTrigger>
  )
}

type StepperProps = {
  onPrev: () => void
  prevLabel: string
  onNext: () => void
  nextLabel: string
  children: ReactNode
}

/** `< caption >` header shared by the day view, the year view and MonthPicker. */
function Stepper({
  onPrev,
  prevLabel,
  onNext,
  nextLabel,
  children,
}: StepperProps) {
  return (
    <div className="flex items-center justify-between pb-2">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={prevLabel}
        onClick={onPrev}
      >
        <ChevronLeft className="size-4" />
      </Button>
      {children}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={nextLabel}
        onClick={onNext}
      >
        <ChevronRight className="size-4" />
      </Button>
    </div>
  )
}

export type DatePickerProps = {
  id?: string
  /** id of the visible `<Label>` — see `FieldTriggerProps.labelledBy`. */
  labelledBy?: string
  /** ISO `YYYY-MM-DD`, or `""` when unset. */
  value: string
  /** Receives the ISO string — not a change event. `""` when cleared. */
  onChange: (iso: string) => void
  min?: string
  max?: string
  disabled?: boolean
  /** Hides the Clear button. */
  required?: boolean
  placeholder?: string
  className?: string
}

export function DatePicker({
  id,
  labelledBy,
  value,
  onChange,
  min,
  max,
  disabled,
  required,
  placeholder = "Pick a date",
  className,
}: DatePickerProps) {
  const bounds = { min, max }
  const monthBounds = {
    min: min ? monthOf(min) : undefined,
    max: max ? monthOf(max) : undefined,
  }

  const [open, setOpen] = useState(false)
  const [view, setView] = useState<"days" | "months">("days")
  const [visibleMonth, setVisibleMonth] = useState(() =>
    value ? monthOf(value) : clampMonth(monthOf(todayISO()), monthBounds),
  )
  const [focused, setFocused] = useState(
    () => value || clampDate(todayISO(), bounds),
  )

  // Every opening starts from the current value (or today, clamped into range)
  // so a half-finished browse from last time is never resurrected.
  useEffect(() => {
    if (!open) return
    const start = value || clampDate(todayISO(), { min, max })
    setFocused(start)
    setVisibleMonth(monthOf(start))
    setView("days")
  }, [open, value, min, max])

  function moveFocus(iso: string) {
    setFocused(iso)
    setVisibleMonth(monthOf(iso))
  }

  function select(iso: string) {
    onChange(iso)
    setOpen(false)
  }

  const today = todayISO()
  const todayOutOfRange = clampDate(today, bounds) !== today

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <FieldTrigger
        id={id}
        labelledBy={labelledBy}
        label={value ? formatDisplay(value) : placeholder}
        isPlaceholder={!value}
        disabled={disabled}
        required={required}
        className={className}
        onOpen={() => setOpen(true)}
      />
      <PopoverContent
        align="start"
        aria-label="Choose date"
        className="w-auto rounded-lg p-3"
        onOpenAutoFocus={(event) => {
          // The grid focuses its own roving cell; let it, so the popover opens
          // on the selected day rather than on the container.
          event.preventDefault()
        }}
      >
        {view === "days" ? (
          <>
            <Stepper
              prevLabel="Previous month"
              onPrev={() => setVisibleMonth(addMonths(visibleMonth, -1))}
              nextLabel="Next month"
              onNext={() => setVisibleMonth(addMonths(visibleMonth, 1))}
            >
              <button
                type="button"
                aria-live="polite"
                onClick={() => setView("months")}
                className="rounded-md px-2 py-1 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                {formatMonthDisplay(visibleMonth)}
              </button>
            </Stepper>
            <CalendarGrid
              month={visibleMonth}
              selected={value}
              focused={focused}
              bounds={bounds}
              onSelect={select}
              onFocusedChange={moveFocus}
            />
            <div className="mt-2 flex items-center justify-between border-t pt-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={todayOutOfRange}
                onClick={() => select(today)}
              >
                Today
              </Button>
              {!required && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onChange("")
                    setOpen(false)
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <Stepper
              prevLabel="Previous year"
              onPrev={() => setVisibleMonth(addMonths(visibleMonth, -12))}
              nextLabel="Next year"
              onNext={() => setVisibleMonth(addMonths(visibleMonth, 12))}
            >
              <span aria-live="polite" className="text-sm font-medium">
                {visibleMonth.slice(0, 4)}
              </span>
            </Stepper>
            <MonthGrid
              year={Number(visibleMonth.slice(0, 4))}
              selected={value ? monthOf(value) : ""}
              focused={visibleMonth}
              bounds={monthBounds}
              onSelect={(ym) => {
                setVisibleMonth(ym)
                setFocused(clampDate(`${ym}-01`, bounds))
                setView("days")
              }}
              onFocusedChange={setVisibleMonth}
            />
          </>
        )}
      </PopoverContent>
    </Popover>
  )
}
