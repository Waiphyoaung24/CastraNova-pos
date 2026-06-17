import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useId, useState } from "react"

import {
  type SupplierCreate,
  type SupplierPublic,
  SuppliersService,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
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
  const nameId = useId()
  const countryId = useId()
  const contactId = useId()

  const [name, setName] = useState("")
  const [country, setCountry] = useState("")
  const [contact, setContact] = useState("")

  const { data: suppliers } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => SuppliersService.readSuppliers(),
  })

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
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={countryId}>Country</Label>
            <Input
              id={countryId}
              value={country}
              maxLength={255}
              onChange={(e) => setCountry(e.target.value)}
            />
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
        {(suppliers ?? []).length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">
            No suppliers yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Country</TableHead>
                <TableHead>Contact</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(suppliers ?? []).map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.country ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.contact ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
