import { useQuery } from "@tanstack/react-query"

import { ProjectsService } from "@/client"

export function useProjectOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["projects", "options"],
    queryFn: () => ProjectsService.readOptions(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}
