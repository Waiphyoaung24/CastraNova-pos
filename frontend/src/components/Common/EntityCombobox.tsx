import { Check, ChevronsUpDown } from "lucide-react"
import { type UIEvent, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { cn } from "@/lib/utils"

const VISIBLE_LIMIT = 50
/** Reveal the next page once the list is scrolled this close to its end. */
const REVEAL_MARGIN_PX = 64

export interface EntityComboboxProps<T> {
  items: T[]
  value: string | undefined
  onChange: (id: string | undefined) => void
  getKey: (item: T) => string
  getLabel: (item: T) => string
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  allowClear?: boolean
  ariaLabel?: string
  id?: string
  required?: boolean
  disabled?: boolean
}

export function EntityCombobox<T>({
  items,
  value,
  onChange,
  getKey,
  getLabel,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyText = "No match found.",
  allowClear = false,
  ariaLabel,
  id,
  required = false,
  disabled = false,
}: EntityComboboxProps<T>) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [shown, setShown] = useState(VISIBLE_LIMIT)

  // The input stays instant; only the filter over the complete option list is
  // deferred, so a fast typist doesn't pay for a re-filter per keystroke.
  const debouncedQuery = useDebouncedValue(query)

  const matches = useMemo(() => {
    const normalized = debouncedQuery.trim().toLowerCase()
    return normalized
      ? items.filter((item) =>
          getLabel(item).toLowerCase().includes(normalized),
        )
      : items
  }, [items, debouncedQuery, getLabel])
  const visible = matches.slice(0, shown)
  const hidden = matches.length - visible.length
  const selectedLabel = useMemo(() => {
    if (!value) return undefined
    const selected = items.find((item) => getKey(item) === value)
    return selected ? getLabel(selected) : undefined
  }, [items, value, getKey, getLabel])

  const close = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (!nextOpen) {
      setQuery("")
      setShown(VISIBLE_LIMIT)
    }
  }

  // Options are already fully in memory; the window only caps how many rows we
  // render, so paging in on scroll is instant and needs no fetch.
  const revealMore = (event: UIEvent<HTMLDivElement>) => {
    if (hidden <= 0) return
    const list = event.currentTarget
    const distanceToEnd = list.scrollHeight - list.scrollTop - list.clientHeight
    if (distanceToEnd <= REVEAL_MARGIN_PX) {
      setShown((current) => current + VISIBLE_LIMIT)
    }
  }

  return (
    <Popover open={open} onOpenChange={close}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          id={id}
          variant="outline"
          role="combobox"
          aria-label={ariaLabel}
          aria-required={required || undefined}
          aria-expanded={open}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span
            className={cn(
              !selectedLabel && "text-muted-foreground",
              "truncate",
            )}
          >
            {selectedLabel ?? placeholder}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      {/* The popover is a bounded flex column so that CommandList — the only
          element with `overflow-y-auto` — is the one that actually scrolls.
          Without `flex flex-col` here, Command's `h-full` resolves against an
          auto-height parent, the list grows to its full content height, and the
          popover silently clips it instead (no wheel scroll, hidden footer). */}
      <PopoverContent
        className="flex w-(--radix-popover-trigger-width) max-h-[var(--radix-popover-content-available-height)] flex-col overflow-hidden p-0"
        align="start"
        collisionPadding={8}
      >
        <Command shouldFilter={false} className="min-h-0">
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(nextQuery: string) => {
              setQuery(nextQuery)
              setShown(VISIBLE_LIMIT)
            }}
          />
          <CommandList
            className="scrollbar-thin min-h-0 flex-1"
            onScroll={revealMore}
          >
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {allowClear && (
                <CommandItem
                  value="__clear__"
                  onSelect={() => {
                    onChange(undefined)
                    close(false)
                  }}
                >
                  <span className="text-muted-foreground flex-1 truncate text-left">
                    All
                  </span>
                  <Check
                    className={cn(
                      "ml-auto h-4 w-4",
                      value ? "opacity-0" : "opacity-100",
                    )}
                  />
                </CommandItem>
              )}
              {visible.map((item) => {
                const key = getKey(item)
                return (
                  <CommandItem
                    key={key}
                    value={key}
                    onSelect={() => {
                      onChange(key)
                      close(false)
                    }}
                  >
                    <span className="flex-1 truncate text-left">
                      {getLabel(item)}
                    </span>
                    <Check
                      className={cn(
                        "ml-auto h-4 w-4",
                        value === key ? "opacity-100" : "opacity-0",
                      )}
                    />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
          {matches.length > VISIBLE_LIMIT && (
            <div className="shrink-0 border-t px-3 py-2 text-xs text-muted-foreground">
              Showing {visible.length} of {matches.length}
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  )
}
