import { useQuery } from "@tanstack/react-query"

import { CustomersService } from "@/client"

export function useCustomerOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["customers", "options"],
    queryFn: () => CustomersService.readOptions(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}
