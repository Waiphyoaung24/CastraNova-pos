import { Minus, Plus } from "lucide-react"
import { useEffect, useState } from "react"

import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  type ReturnDraft,
  returnDraftTotal,
  setReturnQty,
} from "@/lib/pull-return"

interface PullReturnDialogProps {
  pull: ProjectPullPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (draft: ReturnDraft) => void
  isPending: boolean
}

function lineLabel(line: ProjectPullLinePublic): string {
  if (line.line_kind === "UNIT") return line.unit_serial ?? "(no serial)"
  return `${line.model_name} (${line.product_sku})`
}

export function PullReturnDialog({
  pull,
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: PullReturnDialogProps) {
  const [draft, setDraft] = useState<ReturnDraft>({})
  // Fresh draft each time the dialog opens.
  useEffect(() => {
    if (open) setDraft({})
  }, [open])
  const lines = pull.lines.filter((l) => (l.returnable_qty ?? 0) > 0)
  const total = returnDraftTotal(draft)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Return items to stock</DialogTitle>
          <DialogDescription>
            Items that came back from the project go back on the shelf at their
            original cost.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-2">
          {lines.map((line) => {
            const qty = draft[line.id] ?? 0
            const cap = line.returnable_qty ?? 0
            return (
              <li
                key={line.id}
                className="flex items-center justify-between gap-2"
              >
                <span className="num text-sm font-medium">
                  {lineLabel(line)}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-11"
                    disabled={isPending || qty <= 0}
                    aria-label={`Return fewer ${lineLabel(line)}`}
                    onClick={() =>
                      setDraft((d) => setReturnQty(d, line, qty - 1))
                    }
                  >
                    <Minus />
                  </Button>
                  <span className="num w-16 text-center" aria-live="polite">
                    {qty} / {cap}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-11"
                    disabled={isPending || qty >= cap}
                    aria-label={`Return more ${lineLabel(line)}`}
                    onClick={() =>
                      setDraft((d) => setReturnQty(d, line, qty + 1))
                    }
                  >
                    <Plus />
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
          <Button
            type="button"
            disabled={isPending || total === 0}
            onClick={() => onSubmit(draft)}
          >
            {isPending
              ? "Saving…"
              : `Return ${total} ${total === 1 ? "item" : "items"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
