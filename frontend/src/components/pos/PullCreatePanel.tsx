import { ArrowLeft, Minus, Plus, Trash2 } from "lucide-react"
import { type Ref, useId } from "react"
import type { ProjectPublic } from "@/client/types.gen"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import { ScanInput, type ScanInputHandle } from "@/components/ScanInput"
import { Button } from "@/components/ui/button"
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
import type { CreateLine } from "@/lib/pull-create"

interface PullCreatePanelProps {
  projects: ProjectPublic[]
  projectId: string
  onProjectChange: (value: string) => void
  adminNotes: string
  onNotesChange: (value: string) => void
  lines: CreateLine[]
  scanRef: Ref<ScanInputHandle>
  onScan: (code: string) => void
  isSearching: boolean
  notFound: boolean
  isError: boolean
  scanNotice: string
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
  lines,
  scanRef,
  onScan,
  isSearching,
  notFound,
  isError,
  scanNotice,
  onQtyChange,
  onRemove,
  onSubmit,
  onBack,
  isPending,
}: PullCreatePanelProps) {
  const projectSelectId = useId()
  const notesId = useId()
  const canCreate = projectId !== "" && lines.length > 0 && !isPending

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to queue
      </Button>

      <h2 className="text-lg font-semibold">New project pull</h2>

      <div className="space-y-2">
        <Label htmlFor={projectSelectId}>Project</Label>
        <Select value={projectId} onValueChange={onProjectChange}>
          <SelectTrigger id={projectSelectId} className="w-full">
            <SelectValue placeholder="Select a project" />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name} ({p.code})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor={notesId}>Admin notes (optional)</Label>
        <Input
          id={notesId}
          value={adminNotes}
          onChange={(e) => onNotesChange(e.target.value)}
          maxLength={512}
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">Scan item to request</p>
        <ScanInput ref={scanRef} onScan={onScan} />
        <CameraScanFallback onScan={onScan} />
        <p
          aria-live="assertive"
          className="text-muted-foreground min-h-5 text-sm"
        >
          {isError
            ? "Scan lookup failed. Try again."
            : notFound
              ? "No item found for that code."
              : scanNotice}
        </p>
        <p aria-live="polite" className="text-muted-foreground min-h-5 text-sm">
          {isSearching ? "Searching…" : ""}
        </p>
      </div>

      {lines.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Scan items to build the pull request.
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
                        aria-label={`Decrease ${line.sku}`}
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
                        aria-label={`Increase ${line.sku}`}
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
                      aria-label={`Remove ${line.sku}`}
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
        {isPending ? "Creating…" : "Create pull"}
      </button>
    </div>
  )
}
