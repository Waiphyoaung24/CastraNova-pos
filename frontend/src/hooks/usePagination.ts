import { useCallback, useState } from "react"

const DEFAULT_PAGE_SIZE = 25

export interface PaginationOptions {
  pageSize?: number
}

export function usePagination({
  pageSize = DEFAULT_PAGE_SIZE,
}: PaginationOptions = {}) {
  const [page, setPageRaw] = useState(1)

  const setPage = useCallback((nextPage: number) => {
    setPageRaw(Math.max(1, nextPage))
  }, [])
  const reset = useCallback(() => setPageRaw(1), [])
  const pageCount = useCallback(
    (total: number) => Math.max(1, Math.ceil(total / pageSize)),
    [pageSize],
  )

  return {
    page,
    pageSize,
    skip: (page - 1) * pageSize,
    limit: pageSize,
    setPage,
    reset,
    pageCount,
  }
}
