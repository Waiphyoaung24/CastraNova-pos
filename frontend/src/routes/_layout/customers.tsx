import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Contact } from "lucide-react"
import { useId, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  type CustomerType,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { buildCustomerPayload, canCreateCustomer } from "@/lib/customer-create"
import { requireAdmin } from "@/lib/route-guards"

// Admin-only customer management (FR-003 + FR-007). Create / list / edit,
// mirroring the Suppliers screen. Staff create customers inline during a sale
// (CustomerCreateDialog); this screen is the admin surface for the full record.
export const Route = createFileRoute("/_layout/customers")({
  component: Customers,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Customers - CastraNova POS" }],
  }),
})

interface CustomerDraft {
  name: string
  type: CustomerType
  contact: string
  country: string
  notes: string
}

const EMPTY_DRAFT: CustomerDraft = {
  name: "",
  type: "END_CUSTOMER",
  contact: "",
  country: "",
  notes: "",
}

const TYPE_LABEL: Record<CustomerType, string> = {
  END_CUSTOMER: "End customer",
  DEALER: "Dealer",
}

/** The full customer field set, shared by the create card and the edit dialog. */
function CustomerFieldset({
  draft,
  onChange,
}: {
  draft: CustomerDraft
  onChange: (patch: Partial<CustomerDraft>) => void
}) {
  const nameId = useId()
  const typeId = useId()
  const contactId = useId()
  const countryId = useId()
  const notesId = useId()

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={nameId}>Name</Label>
        <Input
          id={nameId}
          value={draft.name}
          maxLength={255}
          placeholder="e.g. John Doe"
          onChange={(e) => onChange({ name: e.target.value })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={typeId}>Type</Label>
        <Select
          value={draft.type}
          onValueChange={(v) => onChange({ type: v as CustomerType })}
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
          value={draft.contact}
          maxLength={255}
          placeholder="Phone or email"
          onChange={(e) => onChange({ contact: e.target.value })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={countryId}>Country</Label>
        <Input
          id={countryId}
          value={draft.country}
          maxLength={64}
          placeholder="e.g. Thailand"
          onChange={(e) => onChange({ country: e.target.value })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={notesId}>Notes</Label>
        <Input
          id={notesId}
          value={draft.notes}
          maxLength={1024}
          placeholder="Any extra details (optional)"
          onChange={(e) => onChange({ notes: e.target.value })}
        />
      </div>
    </div>
  )
}

function CustomerEditDialog({
  customer,
  onClose,
}: {
  customer: CustomerPublic
  onClose: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<CustomerDraft>({
    name: customer.name,
    type: customer.type ?? "END_CUSTOMER",
    contact: customer.contact ?? "",
    country: customer.country ?? "",
    notes: customer.notes ?? "",
  })

  const mutation = useMutation<CustomerPublic, Error, void>({
    mutationFn: () =>
      CustomersService.updateCustomer({
        customerId: customer.id,
        requestBody: buildCustomerPayload(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] })
      showSuccessToast("Customer updated.")
      onClose()
    },
    onError: () =>
      showErrorToast("Could not update the customer. Please try again."),
  })

  const canSave = canCreateCustomer(draft) && !mutation.isPending

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit customer</DialogTitle>
        </DialogHeader>
        <CustomerFieldset
          draft={draft}
          onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        />
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSave}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Customers() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const [draft, setDraft] = useState<CustomerDraft>(EMPTY_DRAFT)
  const [editing, setEditing] = useState<CustomerPublic | null>(null)
  const pagination = usePagination()

  const { data: customersResponse } = useQuery({
    queryKey: ["customers", pagination.page],
    queryFn: () =>
      CustomersService.readCustomers({
        skip: pagination.skip,
        limit: pagination.limit,
      }),
  })
  const customers = customersResponse?.data ?? []

  const createMutation = useMutation<CustomerPublic, Error, void>({
    mutationFn: () =>
      CustomersService.createCustomer({
        requestBody: buildCustomerPayload(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] })
      setDraft(EMPTY_DRAFT)
      showSuccessToast("Customer created.")
    },
    onError: () =>
      showErrorToast("Could not create the customer. Please try again."),
  })

  const canCreate = canCreateCustomer(draft) && !createMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Customers"
        description="Create and review customer records used by sales, tickets, and projects."
      />

      <Alert>
        <Contact />
        <AlertTitle>Manage your customers</AlertTitle>
        <AlertDescription>
          Add customers here so they're ready to pick during sales, tickets, and
          projects. Create a record below, then Edit any entry in the list to
          keep its details current.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New customer</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <CustomerFieldset
            draft={draft}
            onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
          />
          <Button
            type="button"
            disabled={!canCreate}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? "Creating…" : "Create customer"}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Existing customers</h2>
        {customers.length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No customers yet.
          </p>
        ) : isMobile ? (
          <div className="space-y-3">
            {customers.map((c) => (
              <div key={c.id} className="bg-card rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{c.name}</p>
                    <Badge variant="secondary" className="mt-1">
                      {TYPE_LABEL[c.type ?? "END_CUSTOMER"]}
                    </Badge>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setEditing(c)}
                  >
                    Edit
                  </Button>
                </div>
                <div className="mt-3 flex flex-col gap-1 border-t pt-3 text-sm">
                  <div className="flex justify-between gap-3">
                    <span className="text-muted-foreground">Contact</span>
                    <span>{c.contact ?? "—"}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-muted-foreground">Country</span>
                    <span>{c.country ?? "—"}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Country</TableHead>
                <TableHead className="w-0" />
              </TableRow>
            </TableHeader>
            <TableBody>
            {customers.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{c.name}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {TYPE_LABEL[c.type ?? "END_CUSTOMER"]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {c.contact ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {c.country ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing(c)}
                    >
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <PaginationControls
          total={customersResponse?.count ?? 0}
          pageSize={pagination.pageSize}
          page={pagination.page}
          onPageChange={pagination.setPage}
        />
      </div>

      {editing && (
        <CustomerEditDialog
          customer={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
