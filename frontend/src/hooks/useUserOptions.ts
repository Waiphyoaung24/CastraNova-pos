import { useQuery } from "@tanstack/react-query"

import { UsersService } from "@/client"

export function useUserOptions() {
  return useQuery({
    queryKey: ["users", "options"],
    queryFn: () => UsersService.readOptions(),
    staleTime: 5 * 60 * 1000,
  })
}
