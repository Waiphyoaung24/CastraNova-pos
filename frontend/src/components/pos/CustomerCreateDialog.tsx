import { useMutation, useQueryClient } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useId, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  type CustomerType,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { buildCustomerPayload, canCreateCustomer } from "@/lib/customer-create"

interface CustomerCreateDialogProps {
  /** Called with the created customer so the caller can select it. */
  onCreated: (customer: CustomerPublic) => void
}

/**
 * Inline "+ New customer" affordance for the Sale and Tickets customer pickers
 * (FR-007 + D25: staff create a customer at the point of need). Kept lean —
 * Name (required), Type, Contact — so the counter flow stays fast; Country and
 * Notes live on the admin Customers screen. The trigger sits beside the
 * customer <Select> (not inside it — Radix Select/Dialog focus traps conflict).
 */
export function CustomerCreateDialog({ onCreated }: CustomerCreateDialogProps) {
  const { showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const nameId = useId()
  const typeId = useId()
  const contactId = useId()

  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [type, setType] = useState<CustomerType>("END_CUSTOMER")
  const [contact, setContact] = useState("")

  const reset = () => {
    setName("")
    setType("END_CUSTOMER")
    setContact("")
  }

  const mutation = useMutation<CustomerPublic, Error, void>({
    mutationFn: () =>
      CustomersService.createCustomer({
        requestBody: buildCustomerPayload({ name, type, contact }),
      }),
    onSuccess: (customer) => {
      queryClient.invalidateQueries({ queryKey: ["customers"] })
      onCreated(customer)
      setOpen(false)
      reset()
    },
    onError: () =>
      showErrorToast("Could not create the customer. Please try again."),
  })

  const canSubmit =
    canCreateCustomer({ name, type, contact }) && !mutation.isPending

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="w-full">
          <UserPlus className="size-4" aria-hidden="true" />
          New customer
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New customer</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={typeId}>Type</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as CustomerType)}
            >
              <SelectTrigger id={typeId} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="END_CUSTOMER">End customer</SelectItem>
                <SelectItem value="DEALER">Dealer</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor={contactId}>Contact</Label>
            <Input
              id={contactId}
              value={contact}
              maxLength={255}
              onChange={(e) => setContact(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Creating…" : "Create customer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default CustomerCreateDialog
