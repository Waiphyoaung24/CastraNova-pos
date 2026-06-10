import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  CustomersService,
  ProductsService,
  type ProjectPullFulfill,
  type ProjectPullLinePublic,
  type ProjectPullPublic,
  ProjectPullsService,
  ProjectsService,
} from "@/client"
import { PullCreatePanel } from "@/components/pos/PullCreatePanel"
import { PullFulfillPanel } from "@/components/pos/PullFulfillPanel"
import { PullQueue, type PullStateFilter } from "@/components/pos/PullQueue"
import type { ScanInputHandle } from "@/components/ScanInput"
import useCustomToast from "@/hooks/useCustomToast"
import { useRole } from "@/hooks/useRole"
import { useScanLookup } from "@/hooks/useScanLookup"
import {
  addScanToCreateCart,
  buildCreatePayload,
  type CreateCatalogEntry,
  type CreateLine,
  removeCreateLine,
  setCreateQty,
} from "@/lib/pull-create"
import {
  applyScanToFulfill,
  buildFulfillPayload,
  type FulfillDraft,
  seedFulfillDraft,
  setLineFulfilledQty,
} from "@/lib/pull-fulfill"
import { requireAuth } from "@/lib/route-guards"

export const Route = createFileRoute("/_layout/pulls")({
  component: Pulls,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Pulls - CastraNova POS" }],
  }),
})

function Pulls() {
  const { isAdmin } = useRole()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const [mode, setMode] = useState<"queue" | "create">("queue")
  const [selectedPullId, setSelectedPullId] = useState<string | null>(null)
  const [stateFilter, setStateFilter] = useState<PullStateFilter>("PENDING")
  const [fulfillDraft, setFulfillDraft] = useState<FulfillDraft>({})
  const [createLines, setCreateLines] = useState<CreateLine[]>([])
  const [projectId, setProjectId] = useState<string>("")
  const [adminNotes, setAdminNotes] = useState<string>("")
  const [scanNotice, setScanNotice] = useState<string>("")
  const scanRef = useRef<ScanInputHandle>(null)

  const { data: pulls } = useQuery({
    queryKey: ["project-pulls", stateFilter],
    queryFn: () =>
      ProjectPullsService.readProjectPulls({
        state: stateFilter === "ALL" ? undefined : stateFilter,
      }),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: () => ProjectsService.readProjects(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })

  const projectLabels = useMemo(
    () => new Map((projects ?? []).map((p) => [p.id, `${p.name} (${p.code})`])),
    [projects],
  )
  const customerLabels = useMemo(
    () => new Map((customers ?? []).map((c) => [c.id, c.name])),
    [customers],
  )
  const productNames = useMemo(
    () => new Map((products ?? []).map((p) => [p.id, p.model_name])),
    [products],
  )
  // sku -> {productId, modelName} for the create cart.
  const createCatalog = useMemo(() => {
    const map = new Map<string, CreateCatalogEntry>()
    for (const p of products ?? []) {
      map.set(p.sku, { productId: p.id, modelName: p.model_name })
    }
    return map
  }, [products])

  const selectedPull = useMemo(
    () => (pulls ?? []).find((p) => p.id === selectedPullId),
    [pulls, selectedPullId],
  )

  const { resolve, result, isSearching, notFound, isError, reset } =
    useScanLookup()

  // Route each scan to the active view. A scan that changes nothing (no matching
  // line / not in catalog) and isn't NOT_FOUND surfaces a context notice.
  useEffect(() => {
    if (!result) return
    if (mode === "create") {
      const next = addScanToCreateCart(createLines, result, createCatalog)
      if (next === createLines && result.kind !== "NOT_FOUND") {
        setScanNotice("That item can't be added as a pull line.")
      } else {
        setCreateLines(next)
        setScanNotice("")
      }
    } else if (selectedPull) {
      const next = applyScanToFulfill(fulfillDraft, selectedPull.lines, result)
      if (next === fulfillDraft && result.kind !== "NOT_FOUND") {
        setScanNotice("Scanned item isn't on this pull.")
      } else {
        setFulfillDraft(next)
        setScanNotice("")
      }
    }
    reset()
  }, [
    result,
    mode,
    selectedPull,
    createLines,
    fulfillDraft,
    createCatalog,
    reset,
  ])

  const fulfillMutation = useMutation<
    ProjectPullPublic,
    Error,
    { pullId: string; body: ProjectPullFulfill }
  >({
    mutationFn: ({ pullId, body }) =>
      ProjectPullsService.fulfillProjectPull({
        pullId,
        requestBody: body,
      }),
    onSuccess: (pull) => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast(`Pull ${pull.state.toLowerCase()}.`)
      setSelectedPullId(null)
      setFulfillDraft({})
      setScanNotice("")
    },
    onError: () =>
      showErrorToast("Could not fulfill the pull. Please try again."),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      ProjectPullsService.createProjectPull({
        requestBody: buildCreatePayload(createLines, projectId, adminNotes),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Pull created.")
      setMode("queue")
      setCreateLines([])
      setProjectId("")
      setAdminNotes("")
      setScanNotice("")
    },
    onError: () =>
      showErrorToast("Could not create the pull. Please try again."),
  })

  const cancelMutation = useMutation({
    mutationFn: (pullId: string) =>
      ProjectPullsService.cancelProjectPull({ pullId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Pull cancelled.")
    },
    onError: () =>
      showErrorToast("Could not cancel the pull. Please try again."),
  })

  const handleSelect = useCallback((pull: ProjectPullPublic) => {
    setSelectedPullId(pull.id)
    setFulfillDraft(seedFulfillDraft(pull.lines))
    setScanNotice("")
  }, [])

  const handleBackToQueue = useCallback(() => {
    setMode("queue")
    setSelectedPullId(null)
    setFulfillDraft({})
    setScanNotice("")
  }, [])

  const handleNew = useCallback(() => {
    setMode("create")
    setCreateLines([])
    setProjectId("")
    setAdminNotes("")
    setScanNotice("")
  }, [])

  const handleFulfill = useCallback(() => {
    if (!selectedPull) return
    fulfillMutation.mutate({
      pullId: selectedPull.id,
      body: buildFulfillPayload(fulfillDraft),
    })
  }, [selectedPull, fulfillDraft, fulfillMutation])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Project pulls</h1>
        <p className="text-muted-foreground">
          Fulfill pending pulls at the warehouse.
        </p>
      </div>

      {mode === "create" ? (
        <PullCreatePanel
          projects={projects ?? []}
          projectId={projectId}
          onProjectChange={setProjectId}
          adminNotes={adminNotes}
          onNotesChange={setAdminNotes}
          lines={createLines}
          scanRef={scanRef}
          onScan={resolve}
          isSearching={isSearching}
          notFound={notFound}
          isError={isError}
          scanNotice={scanNotice}
          onQtyChange={(key, qty) =>
            setCreateLines((prev) => setCreateQty(prev, key, qty))
          }
          onRemove={(key) =>
            setCreateLines((prev) => removeCreateLine(prev, key))
          }
          onSubmit={() => createMutation.mutate()}
          onBack={handleBackToQueue}
          isPending={createMutation.isPending}
        />
      ) : selectedPull ? (
        <PullFulfillPanel
          pull={selectedPull}
          projectLabel={
            projectLabels.get(selectedPull.project_id) ??
            selectedPull.project_id
          }
          customerLabel={
            customerLabels.get(selectedPull.customer_id) ??
            selectedPull.customer_id
          }
          productNames={productNames}
          draft={fulfillDraft}
          scanRef={scanRef}
          onScan={resolve}
          isSearching={isSearching}
          notFound={notFound}
          isError={isError}
          scanNotice={scanNotice}
          onQtyChange={(line: ProjectPullLinePublic, qty: number) =>
            setFulfillDraft((prev) => setLineFulfilledQty(prev, line, qty))
          }
          onSubmit={handleFulfill}
          onBack={handleBackToQueue}
          isPending={fulfillMutation.isPending}
        />
      ) : (
        <PullQueue
          pulls={pulls ?? []}
          projectLabels={projectLabels}
          customerLabels={customerLabels}
          stateFilter={stateFilter}
          isAdmin={isAdmin}
          onStateFilterChange={setStateFilter}
          onSelect={handleSelect}
          onCancel={(pullId) => cancelMutation.mutate(pullId)}
          onNew={handleNew}
          isCancelling={cancelMutation.isPending}
        />
      )}
    </div>
  )
}
