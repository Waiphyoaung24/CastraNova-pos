import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus } from "lucide-react"
import { useId, useState } from "react"

import {
  type CustomerPublic,
  CustomersService,
  type CustomerType,
} from "@/client"
import { CountryCombobox } from "@/components/Common/CountryCombobox"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { ListFilters } from "@/components/Common/ListFilters"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { Badge } from "@/components/ui/badge"
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
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
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

// Column widths in header order (Name, Type, Contact, Country, edit); sum to 100%.
const CUSTOMER_WIDTHS = ["32%", "13%", "26%", "17%", "12%"]

// Radix Select forbids an empty-string item value, so "all types" needs a sentinel.
const ALL_TYPES = "__all__"

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
        <CountryCombobox
          id={countryId}
          ariaLabel="Country"
          value={draft.country}
          onChange={(country) => onChange({ country })}
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

/** "New customer" — the register form behind a dialog, off the page header.
 * Distinct from `components/pos/CustomerCreateDialog.tsx`, the lean inline
 * quick-create used by the Sale/Tickets pickers — this is the full admin form. */
function CustomerCreateDialog() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<CustomerDraft>(EMPTY_DRAFT)

  const mutation = useMutation<CustomerPublic, Error, void>({
    mutationFn: () =>
      CustomersService.createCustomer({
        requestBody: buildCustomerPayload(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["customers"] })
      queryClient.invalidateQueries({ queryKey: ["customer-countries"] })
      showSuccessToast("Customer created.")
      setOpen(false)
      setDraft(EMPTY_DRAFT)
    },
    onError: () =>
      showErrorToast("Could not create the customer. Please try again."),
  })

  const canSubmit = canCreateCustomer(draft) && !mutation.isPending

  return (
    <Dialog
      open={open}
      // The Country field's popover combobox is portalled outside this
      // Dialog's DOM subtree; a modal Dialog's focus trap fights that
      // portal for focus (Radix issue: nested modal FocusScopes). Non-modal
      // keeps the overlay/close-on-outside-click behavior but drops the
      // trap, letting the combobox actually receive focus and keystrokes.
      modal={false}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setDraft(EMPTY_DRAFT)
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">
          <Plus className="mr-2 size-4" aria-hidden="true" />
          New customer
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New customer</DialogTitle>
        </DialogHeader>
        <CustomerFieldset
          draft={draft}
          onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        />
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
      queryClient.invalidateQueries({ queryKey: ["customer-countries"] })
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
      // The Country field's popover combobox is portalled outside this
      // Dialog's DOM subtree; a modal Dialog's focus trap fights that
      // portal for focus (Radix issue: nested modal FocusScopes). Non-modal
      // keeps the overlay/close-on-outside-click behavior but drops the
      // trap, letting the combobox actually receive focus and keystrokes.
      modal={false}
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
  const isMobile = useIsMobile()
  const countryFilterId = useId()
  const [editing, setEditing] = useState<CustomerPublic | null>(null)
  const [search, setSearch] = useState("")
  const [country, setCountry] = useState("")
  const [type, setType] = useState("")
  const debouncedSearch = useDebouncedValue(search)
  const pagination = usePagination()

  const { data: countryOptions } = useQuery({
    queryKey: ["customer-countries"],
    queryFn: () => CustomersService.listCountries(),
  })

  const {
    data: customersResponse,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: [
      "customers",
      { page: pagination.page, q: debouncedSearch, country, type },
    ],
    queryFn: () =>
      CustomersService.readCustomers({
        skip: pagination.skip,
        limit: pagination.limit,
        q: debouncedSearch || undefined,
        country: country || undefined,
        type: (type || undefined) as CustomerType | undefined,
      }),
    placeholderData: keepPreviousData,
  })
  const customers = customersResponse?.data ?? []
  const listLoading = isPlaceholderData || isFetching
  const activeCount = [debouncedSearch, country, type].filter(Boolean).length
  const hasFilters = activeCount > 0
  const clearFilters = () => {
    setSearch("")
    setCountry("")
    setType("")
    pagination.reset()
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Customers"
        description="Create and review customer records used by sales, tickets, and projects."
        actions={<CustomerCreateDialog />}
      />

      <ListFilters activeCount={activeCount} onClear={clearFilters}>
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            pagination.reset()
          }}
          placeholder="Search name…"
          className="w-full sm:w-64"
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={countryFilterId}>Country</Label>
          <div className="w-full sm:w-56">
            <EntityCombobox
              id={countryFilterId}
              items={countryOptions ?? []}
              value={country || undefined}
              onChange={(next) => {
                setCountry(next ?? "")
                pagination.reset()
              }}
              getKey={(c) => c}
              getLabel={(c) => c}
              placeholder="All countries"
              searchPlaceholder="Search country…"
              emptyText="No countries in use."
              ariaLabel="Country filter"
              allowClear
            />
          </div>
        </div>
        <Select
          value={type === "" ? ALL_TYPES : type}
          onValueChange={(v) => {
            setType(v === ALL_TYPES ? "" : v)
            pagination.reset()
          }}
        >
          <SelectTrigger className="w-full sm:w-40" aria-label="Type filter">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES}>All types</SelectItem>
            <SelectItem value="END_CUSTOMER">
              {TYPE_LABEL.END_CUSTOMER}
            </SelectItem>
            <SelectItem value="DEALER">{TYPE_LABEL.DEALER}</SelectItem>
          </SelectContent>
        </Select>
      </ListFilters>

      <div className="space-y-2">
        <ListShell loading={listLoading}>
          {customers.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {!customersResponse
                ? "Loading…"
                : hasFilters
                  ? "No customers match the current filters."
                  : "No customers yet."}
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
            <ListTable
              widths={CUSTOMER_WIDTHS}
              minWidth={760}
              head={
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead>Country</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              }
            >
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
                  <TableCell className="overflow-visible! text-right">
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
            </ListTable>
          )}
        </ListShell>
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
