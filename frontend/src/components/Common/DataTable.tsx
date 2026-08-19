import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"

import { ListShell } from "@/components/Common/ListShell"
import { ListTable } from "@/components/Common/ListTable"
import { PaginationControls } from "@/components/Common/PaginationControls"
import { TableCell, TableHead, TableRow } from "@/components/ui/table"

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  /** Column widths in column order; must sum to 100%. */
  widths: string[]
  /** Floor for the table width — see ListTable. */
  minWidth?: number
  /** 1-based page state, driven by the server. */
  pagination: {
    page: number
    pageSize: number
    total: number
    onPageChange: (page: number) => void
  }
  loading?: boolean
}

export function DataTable<TData, TValue>({
  columns,
  data,
  widths,
  minWidth,
  pagination,
  loading = false,
}: DataTableProps<TData, TValue>) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: Math.max(1, Math.ceil(pagination.total / pagination.pageSize)),
  })
  const rows = table.getRowModel().rows

  return (
    <div className="flex flex-col gap-4">
      <ListShell loading={loading}>
        <ListTable
          widths={widths}
          minWidth={minWidth}
          head={table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent">
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        >
          {rows.length ? (
            rows.map((row) => (
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
                className="text-muted-foreground h-32 overflow-visible! text-center"
              >
                No results found.
              </TableCell>
            </TableRow>
          )}
        </ListTable>
      </ListShell>

      <PaginationControls
        total={pagination.total}
        pageSize={pagination.pageSize}
        page={pagination.page}
        onPageChange={pagination.onPageChange}
      />
    </div>
  )
}
