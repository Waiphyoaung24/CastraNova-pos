import { ChevronsLeft, ChevronsRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination"

interface PaginationControlsProps {
  total: number
  pageSize: number
  page: number
  onPageChange: (page: number) => void
}

export function PaginationControls({
  total,
  pageSize,
  page,
  onPageChange,
}: PaginationControlsProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (pageCount <= 1) return null

  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  const atStart = page <= 1
  const atEnd = page >= pageCount

  return (
    <div className="flex flex-col items-center justify-between gap-3 pt-4 sm:flex-row">
      <p className="text-sm text-muted-foreground">
        Showing <span className="font-medium text-foreground">{first}</span>–
        <span className="font-medium text-foreground">{last}</span> of{" "}
        <span className="font-medium text-foreground">{total}</span>
      </p>
      <Pagination className="mx-0 w-auto justify-end">
        <PaginationContent>
          <PaginationItem>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label="Go to first page"
              disabled={atStart}
              onClick={() => onPageChange(1)}
            >
              <ChevronsLeft className="h-4 w-4" />
            </Button>
          </PaginationItem>
          <PaginationItem>
            <PaginationPrevious
              aria-disabled={atStart}
              className={atStart ? "pointer-events-none opacity-50" : undefined}
              onClick={(event) => {
                event.preventDefault()
                if (!atStart) onPageChange(page - 1)
              }}
            />
          </PaginationItem>
          <PaginationItem>
            <span className="px-3 text-sm text-muted-foreground">
              Page {page} of {pageCount}
            </span>
          </PaginationItem>
          <PaginationItem>
            <PaginationNext
              aria-disabled={atEnd}
              className={atEnd ? "pointer-events-none opacity-50" : undefined}
              onClick={(event) => {
                event.preventDefault()
                if (!atEnd) onPageChange(page + 1)
              }}
            />
          </PaginationItem>
          <PaginationItem>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label="Go to last page"
              disabled={atEnd}
              onClick={() => onPageChange(pageCount)}
            >
              <ChevronsRight className="h-4 w-4" />
            </Button>
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    </div>
  )
}
