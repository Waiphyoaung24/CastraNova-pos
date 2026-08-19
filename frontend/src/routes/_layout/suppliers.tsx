import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Pencil } from "lucide-react"
import { useId, useState } from "react"

import { type SupplierPublic, SuppliersService } from "@/client"
import { EntityCombobox } from "@/components/Common/EntityCombobox"
import { ListFilters } from "@/components/Common/ListFilters"
import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { SupplierCreateDialog } from "@/components/suppliers/SupplierCreateDialog"
import { SupplierEditDialog } from "@/components/suppliers/SupplierEditDialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { useIsMobile } from "@/hooks/useMobile"
import { usePagination } from "@/hooks/usePagination"
import { requireAdmin } from "@/lib/route-guards"

// Column widths in header order (Name, Country, Contact, edit); sum to 100%.
const SUPPLIER_WIDTHS = ["34%", "18%", "34%", "14%"]

// Admin-only supplier management (FR-003). Create + list, mirroring the
// Projects screen.
export const Route = createFileRoute("/_layout/suppliers")({
  component: Suppliers,
  beforeLoad: () => requireAdmin(),
  head: () => ({
    meta: [{ title: "Suppliers - CastraNova POS" }],
  }),
})

function Suppliers() {
  const isMobile = useIsMobile()
  const countryFilterId = useId()
  const [editing, setEditing] = useState<SupplierPublic | null>(null)
  const [search, setSearch] = useState("")
  const [country, setCountry] = useState("")
  const debouncedSearch = useDebouncedValue(search)
  const pagination = usePagination()

  const { data: countryOptions } = useQuery({
    queryKey: ["supplier-countries"],
    queryFn: () => SuppliersService.listCountries(),
  })

  const {
    data: suppliersResponse,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: [
      "suppliers",
      { page: pagination.page, q: debouncedSearch, country },
    ],
    queryFn: () =>
      SuppliersService.readSuppliers({
        skip: pagination.skip,
        limit: pagination.limit,
        q: debouncedSearch || undefined,
        country: country || undefined,
      }),
    placeholderData: keepPreviousData,
  })
  const suppliers = suppliersResponse?.data ?? []
  const listLoading = isPlaceholderData || isFetching
  const activeCount = [debouncedSearch, country].filter(Boolean).length
  const hasFilters = activeCount > 0
  const clearFilters = () => {
    setSearch("")
    setCountry("")
    pagination.reset()
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Suppliers"
        description="Create and review supplier records used when receiving stock."
        actions={<SupplierCreateDialog />}
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
      </ListFilters>

      <div className="space-y-2">
        <ListShell loading={listLoading}>
          {suppliers.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {!suppliersResponse
                ? "Loading…"
                : hasFilters
                  ? "No suppliers match the current filters."
                  : "No suppliers yet."}
            </p>
          ) : isMobile ? (
            <div className="space-y-3">
              {suppliers.map((s) => (
                <div key={s.id} className="bg-card rounded-lg border p-4">
                  <p className="font-medium">{s.name}</p>
                  <div className="mt-2 flex flex-col gap-1 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Country</span>
                      <span>{s.country ?? "—"}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Contact</span>
                      <span>{s.contact ?? "—"}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <ListTable
              widths={SUPPLIER_WIDTHS}
              minWidth={700}
              head={
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Country</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              }
            >
              {suppliers.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.country ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.contact ?? "—"}
                  </TableCell>
                  <TableCell className="overflow-visible! text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing(s)}
                    >
                      <Pencil className="mr-1 size-4" />
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </ListTable>
          )}
        </ListShell>
        <PaginationControls
          total={suppliersResponse?.count ?? 0}
          pageSize={pagination.pageSize}
          page={pagination.page}
          onPageChange={pagination.setPage}
        />
      </div>

      {editing && (
        <SupplierEditDialog
          supplier={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
