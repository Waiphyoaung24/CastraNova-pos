import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react"

import { Button } from "@/components/ui/button"
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

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  manualPagination?: {
    pageCount: number
    pageIndex: number
    pageSize: number
    total: number
    onPageChange: (pageIndex: number) => void
  }
}

export function DataTable<TData, TValue>({
  columns,
  data,
  manualPagination,
}: DataTableProps<TData, TValue>) {
  const mp = manualPagination
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    ...(mp
      ? {
          manualPagination: true as const,
          pageCount: mp.pageCount,
          state: { pagination: { pageIndex: mp.pageIndex, pageSize: mp.pageSize } },
          onPaginationChange: (updater: unknown) => {
            const previous = { pageIndex: mp.pageIndex, pageSize: mp.pageSize }
            const next = typeof updater === "function"
              ? (updater as (state: typeof previous) => typeof previous)(previous)
              : (updater as typeof previous)
            mp.onPageChange(next.pageIndex)
          },
        }
      : { getPaginationRowModel: getPaginationRowModel() }),
  })
  const total = mp ? mp.total : data.length
  const pageSize = mp ? mp.pageSize : table.getState().pagination.pageSize
  const pageIndex = mp ? mp.pageIndex : table.getState().pagination.pageIndex
  const first = total === 0 ? 0 : pageIndex * pageSize + 1
  const last = Math.min((pageIndex + 1) * pageSize, total)

  return (
    <div className="flex flex-col gap-4">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent">
              {headerGroup.headers.map((header) => {
                return (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={columns.length}
                className="h-32 text-center text-muted-foreground"
              >
                No results found.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {(mp ? mp.pageCount : table.getPageCount()) > 1 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 border-t bg-muted/20">
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="text-sm text-muted-foreground">
              Showing {first} to {last} of{" "}
              <span className="font-medium text-foreground">{total}</span>{" "}
              entries
            </div>
            {!mp && <div className="flex items-center gap-x-2">
              <p className="text-sm text-muted-foreground">Rows per page</p>
              <Select
                value={`${table.getState().pagination.pageSize}`}
                onValueChange={(value) => {
                  table.setPageSize(Number(value))
                }}
              >
                <SelectTrigger className="h-8 w-[70px]">
                  <SelectValue
                    placeholder={table.getState().pagination.pageSize}
                  />
                </SelectTrigger>
                <SelectContent side="top">
                  {[5, 10, 25, 50].map((pageSize) => (
                    <SelectItem key={pageSize} value={`${pageSize}`}>
                      {pageSize}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>}
          </div>

          <div className="flex items-center gap-x-6">
            <div className="flex items-center gap-x-1 text-sm text-muted-foreground">
              <span>Page</span>
              <span className="font-medium text-foreground">
                {pageIndex + 1}
              </span>
              <span>of</span>
              <span className="font-medium text-foreground">
                {mp ? mp.pageCount : table.getPageCount()}
              </span>
            </div>

            <div className="flex items-center gap-x-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => (mp ? mp.onPageChange(0) : table.setPageIndex(0))}
                disabled={mp ? pageIndex === 0 : !table.getCanPreviousPage()}
              >
                <span className="sr-only">Go to first page</span>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => (mp ? mp.onPageChange(pageIndex - 1) : table.previousPage())}
                disabled={mp ? pageIndex === 0 : !table.getCanPreviousPage()}
              >
                <span className="sr-only">Go to previous page</span>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => (mp ? mp.onPageChange(pageIndex + 1) : table.nextPage())}
                disabled={mp ? pageIndex >= mp.pageCount - 1 : !table.getCanNextPage()}
              >
                <span className="sr-only">Go to next page</span>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => (mp
                  ? mp.onPageChange(mp.pageCount - 1)
                  : table.setPageIndex(table.getPageCount() - 1))}
                disabled={mp ? pageIndex >= mp.pageCount - 1 : !table.getCanNextPage()}
              >
                <span className="sr-only">Go to last page</span>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
