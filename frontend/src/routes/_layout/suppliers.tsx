import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Pencil, Truck } from "lucide-react"
import { useId, useState } from "react"

import {
  type SupplierCreate,
  type SupplierPublic,
  SuppliersService,
} from "@/client"
import { LIST_SCROLL, ListShell } from "@/components/Common/ListShell"
import { PageHeader } from "@/components/Common/PageHeader"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { SupplierEditDialog } from "@/components/suppliers/SupplierEditDialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
import { requireAdmin } from "@/lib/route-guards"
import { buildSupplierPayload, canCreateSupplier } from "@/lib/supplier-create"

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
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const isMobile = useIsMobile()
  const nameId = useId()
  const countryId = useId()
  const contactId = useId()

  const [name, setName] = useState("")
  const [country, setCountry] = useState("")
  const [contact, setContact] = useState("")
  const [editing, setEditing] = useState<SupplierPublic | null>(null)
  const pagination = usePagination()

  const {
    data: suppliersResponse,
    isPlaceholderData,
    isFetching,
  } = useQuery({
    queryKey: ["suppliers", pagination.page],
    queryFn: () =>
      SuppliersService.readSuppliers({
        skip: pagination.skip,
        limit: pagination.limit,
      }),
    placeholderData: keepPreviousData,
  })
  const suppliers = suppliersResponse?.data ?? []
  const listLoading = isPlaceholderData || isFetching

  const createMutation = useMutation<SupplierPublic, Error, SupplierCreate>({
    mutationFn: (payload) =>
      SuppliersService.createSupplier({ requestBody: payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] })
      setName("")
      setCountry("")
      setContact("")
      showSuccessToast("Supplier created.")
    },
    onError: () =>
      showErrorToast("Could not create the supplier. Please try again."),
  })

  const draft = { name, country, contact }
  const canCreate = canCreateSupplier(draft) && !createMutation.isPending

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Suppliers"
        description="Create and review supplier records used when receiving stock."
      />

      <Alert>
        <Truck />
        <AlertTitle>Manage your suppliers</AlertTitle>
        <AlertDescription>
          Add a supplier here so you can pick it when receiving stock. Fill in
          the details and Create supplier — saved suppliers appear in the list
          below.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>New supplier</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={name}
              maxLength={255}
              placeholder="e.g. Acme Trading Co."
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={countryId}>Country</Label>
            <Input
              id={countryId}
              value={country}
              maxLength={64}
              placeholder="e.g. Thailand"
              onChange={(e) => setCountry(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={contactId}>Contact</Label>
            <Input
              id={contactId}
              value={contact}
              maxLength={255}
              placeholder="Phone, email, or contact person"
              onChange={(e) => setContact(e.target.value)}
            />
          </div>
          <Button
            type="button"
            disabled={!canCreate}
            onClick={() => createMutation.mutate(buildSupplierPayload(draft))}
          >
            {createMutation.isPending ? "Creating…" : "Create supplier"}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Existing suppliers</h2>
        <ListShell loading={listLoading}>
          {suppliers.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {suppliersResponse ? "No suppliers yet." : "Loading…"}
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
            <Table containerClassName={LIST_SCROLL}>
              <TableHeader className="bg-background sticky top-0 z-10">
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Country</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {suppliers.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {s.country ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {s.contact ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
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
              </TableBody>
            </Table>
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
