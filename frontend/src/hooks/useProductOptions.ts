import { useQuery } from "@tanstack/react-query"

import { ProductsService } from "@/client"

export function useProductOptions() {
  return useQuery({
    queryKey: ["products", "options"],
    queryFn: () => ProductsService.readOptions(),
    staleTime: 5 * 60 * 1000,
  })
}
