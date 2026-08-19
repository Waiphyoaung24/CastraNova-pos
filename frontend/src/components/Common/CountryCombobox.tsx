import { useMemo } from "react"

import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { COUNTRIES } from "@/lib/countries"

const identity = (value: string) => value

/** Autocomplete country picker over the static ISO country list. */
export function CountryCombobox({
  value,
  onChange,
  id,
  ariaLabel,
  placeholder = "Select country…",
}: {
  value: string
  onChange: (value: string) => void
  id?: string
  ariaLabel?: string
  placeholder?: string
}) {
  // A supplier's stored country may not be on the current list (legacy free
  // text, or a country renamed since). Keep it selectable so it stays
  // visible instead of silently falling back to the placeholder.
  const items = useMemo(
    () =>
      value && !COUNTRIES.includes(value)
        ? [value, ...COUNTRIES]
        : [...COUNTRIES],
    [value],
  )

  return (
    <EntityCombobox
      id={id}
      items={items}
      value={value || undefined}
      onChange={(next) => onChange(next ?? "")}
      getKey={identity}
      getLabel={identity}
      placeholder={placeholder}
      searchPlaceholder="Search country…"
      emptyText="No country found."
      ariaLabel={ariaLabel}
      allowClear
    />
  )
}
