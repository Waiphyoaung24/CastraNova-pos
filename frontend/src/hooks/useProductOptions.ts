import { useQuery } from "@tanstack/react-query"

import { ProductsService } from "@/client"

export function useProductOptions({ activeOnly = false } = {}) {
  return useQuery({
    queryKey: ["products", "options", { activeOnly }],
    queryFn: () => ProductsService.readOptions({ activeOnly }),
    staleTime: 5 * 60 * 1000,
  })
}
