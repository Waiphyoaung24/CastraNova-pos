import { useId } from "react"

import { CountryCombobox } from "@/components/Common/CountryCombobox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { SupplierDraft } from "@/lib/supplier-create"

/** Name / Country / Contact fields shared by the create and edit dialogs. */
export function SupplierFieldset({
  draft,
  onChange,
}: {
  draft: SupplierDraft
  onChange: (patch: Partial<SupplierDraft>) => void
}) {
  const nameId = useId()
  const countryId = useId()
  const contactId = useId()

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={nameId}>Name</Label>
        <Input
          id={nameId}
          value={draft.name}
          maxLength={255}
          placeholder="e.g. Acme Trading Co."
          onChange={(e) => onChange({ name: e.target.value })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={countryId}>Country</Label>
        <CountryCombobox
          id={countryId}
          ariaLabel="Country"
          value={draft.country}
          onChange={(country) => onChange({ country })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={contactId}>Contact</Label>
        <Input
          id={contactId}
          value={draft.contact}
          maxLength={255}
          placeholder="Phone, email, or contact person"
          onChange={(e) => onChange({ contact: e.target.value })}
        />
      </div>
    </div>
  )
}
