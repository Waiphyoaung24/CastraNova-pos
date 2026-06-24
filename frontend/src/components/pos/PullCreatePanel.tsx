import { ArrowLeft, Minus, Plus, Trash2 } from "lucide-react"
import { useId, useState } from "react"
import type { ProductPublic, ProjectPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectEmpty,
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
import type { CreateLine } from "@/lib/pull-create"

interface PullCreatePanelProps {
  projects: ProjectPublic[]
  projectId: string
  onProjectChange: (value: string) => void
  adminNotes: string
  onNotesChange: (value: string) => void
  products: ProductPublic[]
  onAddItem: (productId: string, qty: number) => void
  addNotice: string
  isAdding: boolean
  lines: CreateLine[]
  onQtyChange: (key: string, qty: number) => void
  onRemove: (key: string) => void
  onSubmit: () => void
  onBack: () => void
  isPending: boolean
}

export function PullCreatePanel({
  projects,
  projectId,
  onProjectChange,
  adminNotes,
  onNotesChange,
  products,
  onAddItem,
  addNotice,
  isAdding,
  lines,
  onQtyChange,
  onRemove,
  onSubmit,
  onBack,
  isPending,
}: PullCreatePanelProps) {
  const projectSelectId = useId()
  const notesId = useId()
  const itemSelectId = useId()
  const [selectedProductId, setSelectedProductId] = useState("")
  const [qty, setQty] = useState(1)
  const canCreate = projectId !== "" && lines.length > 0 && !isPending

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to requests
      </Button>

      <h2 className="text-lg font-semibold">New stock request</h2>

      <div className="space-y-2">
        <Label htmlFor={projectSelectId}>Project</Label>
        <Select value={projectId} onValueChange={onProjectChange}>
          <SelectTrigger id={projectSelectId} className="w-full">
            <SelectValue placeholder="Select a project" />
          </SelectTrigger>
          <SelectContent>
            {projects.length ? (
              projects.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name} ({p.code})
                </SelectItem>
              ))
            ) : (
              <SelectEmpty>No projects available</SelectEmpty>
            )}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor={notesId}>Notes for the warehouse (optional)</Label>
        <Input
          id={notesId}
          value={adminNotes}
          onChange={(e) => onNotesChange(e.target.value)}
          maxLength={512}
          placeholder="Any special handling notes (optional)"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={itemSelectId}>Add item to request</Label>
        <div className="flex items-end gap-2">
          <Select
            value={selectedProductId}
            onValueChange={setSelectedProductId}
          >
            <SelectTrigger id={itemSelectId} className="w-full">
              <SelectValue placeholder="Select an item" />
            </SelectTrigger>
            <SelectContent>
              {products.length ? (
                products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.model_name} ({p.sku})
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No items available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              disabled={qty <= 1}
              aria-label="Decrease quantity"
              onClick={() => setQty((q) => Math.max(1, q - 1))}
            >
              <Minus />
            </Button>
            <span className="num w-8 text-center" aria-hidden="true">
              {qty}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              aria-label="Increase quantity"
              onClick={() => setQty((q) => q + 1)}
            >
              <Plus />
            </Button>
          </div>
          <Button
            type="button"
            className="h-11"
            disabled={selectedProductId === "" || isAdding}
            onClick={() => {
              onAddItem(selectedProductId, qty)
              setSelectedProductId("")
              setQty(1)
            }}
          >
            {isAdding ? "Adding…" : "Add"}
          </Button>
        </div>
        <p aria-live="polite" className="text-muted-foreground min-h-5 text-sm">
          {addNotice}
        </p>
      </div>

      {lines.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Scan items to add to this request.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-muted-foreground">Type</TableHead>
              <TableHead className="text-center">Qty</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((line) => {
              const isUnit = line.lineKind === "UNIT"
              const label = isUnit ? (line.unitSerial ?? line.sku) : line.sku
              return (
                <TableRow key={line.key}>
                  <TableCell>
                    <div className="font-medium">{line.modelName}</div>
                    <div className="text-muted-foreground num text-xs">
                      {isUnit ? line.unitSerial : line.sku}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {line.lineKind}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-11"
                        disabled={isUnit || line.requestedQty <= 1}
                        aria-label={`Decrease ${label}`}
                        onClick={() =>
                          onQtyChange(line.key, line.requestedQty - 1)
                        }
                      >
                        <Minus />
                      </Button>
                      <span className="num w-8 text-center" aria-hidden="true">
                        {line.requestedQty}
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-11"
                        disabled={isUnit}
                        aria-label={`Increase ${label}`}
                        onClick={() =>
                          onQtyChange(line.key, line.requestedQty + 1)
                        }
                      >
                        <Plus />
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-destructive size-11"
                      aria-label={`Remove ${label}`}
                      onClick={() => onRemove(line.key)}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canCreate}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPending ? "Creating…" : "Create request"}
      </button>
    </div>
  )
}
