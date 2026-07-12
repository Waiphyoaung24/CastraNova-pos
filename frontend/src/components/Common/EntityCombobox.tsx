import { Check, ChevronsUpDown } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

const VISIBLE_LIMIT = 50

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
  disabled = false,
}: EntityComboboxProps<T>) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [shown, setShown] = useState(VISIBLE_LIMIT)

  const matches = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return normalized
      ? items.filter((item) => getLabel(item).toLowerCase().includes(normalized))
      : items
  }, [items, query, getLabel])
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

  return (
    <Popover open={open} onOpenChange={close}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span className={cn(!selectedLabel && "text-muted-foreground", "truncate")}>
            {selectedLabel ?? placeholder}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(nextQuery: string) => {
              setQuery(nextQuery)
              setShown(VISIBLE_LIMIT)
            }}
          />
          <CommandList>
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
                  <Check className={cn("mr-2 h-4 w-4", value ? "opacity-0" : "opacity-100")} />
                  <span className="text-muted-foreground">All</span>
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
                    <Check className={cn("mr-2 h-4 w-4", value === key ? "opacity-100" : "opacity-0")} />
                    <span className="truncate">{getLabel(item)}</span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
          <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
            <span className="text-xs text-muted-foreground">
              Showing {visible.length} of {matches.length}
            </span>
            {hidden > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setShown((current) => current + VISIBLE_LIMIT)}
              >
                Show {Math.min(VISIBLE_LIMIT, hidden)} more
              </Button>
            )}
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
