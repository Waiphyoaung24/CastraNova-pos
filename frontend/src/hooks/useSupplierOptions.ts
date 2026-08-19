import { useQuery } from "@tanstack/react-query"

import { SuppliersService } from "@/client"

export function useSupplierOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["suppliers", "options"],
    queryFn: () => SuppliersService.readOptions(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}
