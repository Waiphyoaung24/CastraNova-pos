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
  invalid?: boolean
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
  invalid,
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
        aria-invalid={invalid || undefined}
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
  /** Marks the field as failing validation. `inputClassName` already carries
   * the `aria-invalid:` styling, so the trigger turns destructive for free. */
  invalid?: boolean
  placeholder?: string
  className?: string
  /** Fires whenever the popover opens or closes. A parent Dialog needs this to
   * know one of its own pickers is up — see ProjectEditDialog. */
  onOpenChange?: (open: boolean) => void
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
  invalid,
  placeholder = "Pick a date",
  className,
  onOpenChange,
}: DatePickerProps) {
  const bounds = { min, max }
  const monthBounds = {
    min: min ? monthOf(min) : undefined,
    max: max ? monthOf(max) : undefined,
  }

  const [open, setRawOpen] = useState(false)
  const setOpen = (next: boolean) => {
    setRawOpen(next)
    onOpenChange?.(next)
  }
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
        invalid={invalid}
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
        onKeyDown={(event) => {
          // Close on Escape from the popover's own subtree. Radix's layer
          // dismissal is not enough inside a modal={false} Dialog, where the
          // Dialog's handler also fires and ordering is not guaranteed.
          if (event.key === "Escape") setOpen(false)
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
                onClick={() => setView("months")}
                className="rounded-md px-2 py-1 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                {/* The live region is this inner span, not the button: a live
                    region on an interactive control is tracked for focus as
                    well, which makes some screen readers double-announce it or
                    drop the announcement. Matches the year captions below. */}
                <span aria-live="polite">{formatMonthDisplay(visibleMonth)}</span>
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

export type MonthPickerProps = {
  id?: string
  /** id of the visible `<Label>` — see `FieldTriggerProps.labelledBy`. */
  labelledBy?: string
  /** ISO `YYYY-MM`, or `""` when unset. */
  value: string
  /** Receives the `YYYY-MM` string — not a change event. */
  onChange: (ym: string) => void
  min?: string
  max?: string
  disabled?: boolean
  placeholder?: string
  className?: string
  /** Fires whenever the popover opens or closes. */
  onOpenChange?: (open: boolean) => void
}

/** Opens straight into the year view — the same MonthGrid the DatePicker
 * caption drops to, which is what makes the report screens match the date
 * pickers for free. No Today/Clear footer: both report screens always hold a
 * month (`currentMonth()` seeds them) and `isValidMonth()` rejects "". */
export function MonthPicker({
  id,
  labelledBy,
  value,
  onChange,
  min,
  max,
  disabled,
  placeholder = "Pick a month",
  className,
  onOpenChange,
}: MonthPickerProps) {
  const bounds = { min, max }
  const [open, setRawOpen] = useState(false)
  const setOpen = (next: boolean) => {
    setRawOpen(next)
    onOpenChange?.(next)
  }
  const [focused, setFocused] = useState(
    () => value || clampMonth(monthOf(todayISO()), bounds),
  )
  const [visibleYear, setVisibleYear] = useState(() =>
    Number((value || todayISO()).slice(0, 4)),
  )

  useEffect(() => {
    if (!open) return
    const start = value || clampMonth(monthOf(todayISO()), { min, max })
    setFocused(start)
    setVisibleYear(Number(start.slice(0, 4)))
  }, [open, value, min, max])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <FieldTrigger
        id={id}
        labelledBy={labelledBy}
        label={value ? formatMonthDisplay(value) : placeholder}
        isPlaceholder={!value}
        disabled={disabled}
        className={className}
        onOpen={() => setOpen(true)}
      />
      <PopoverContent
        align="start"
        aria-label="Choose month"
        className="w-auto rounded-lg p-3"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
        }}
        onKeyDown={(event) => {
          // Close on Escape from the popover's own subtree. Radix's layer
          // dismissal is not enough inside a modal={false} Dialog, where the
          // Dialog's handler also fires and ordering is not guaranteed.
          if (event.key === "Escape") setOpen(false)
        }}
      >
        <Stepper
          prevLabel="Previous year"
          onPrev={() => setVisibleYear((y) => y - 1)}
          nextLabel="Next year"
          onNext={() => setVisibleYear((y) => y + 1)}
        >
          <span aria-live="polite" className="text-sm font-medium">
            {visibleYear}
          </span>
        </Stepper>
        <MonthGrid
          year={visibleYear}
          selected={value}
          focused={focused}
          bounds={bounds}
          onSelect={(ym) => {
            onChange(ym)
            setOpen(false)
          }}
          onFocusedChange={(ym) => {
            setFocused(ym)
            setVisibleYear(Number(ym.slice(0, 4)))
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
