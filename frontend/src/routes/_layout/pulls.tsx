import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  ProductsService,
  type ProjectPullCreate,
  type ProjectPullFulfill,
  type ProjectPullLinePublic,
  type ProjectPullPublic,
  ProjectPullsService,
  ProjectsService,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import { PullCreatePanel } from "@/components/pos/PullCreatePanel"
import { PullFulfillPanel } from "@/components/pos/PullFulfillPanel"
import { PullQueue, type PullStateFilter } from "@/components/pos/PullQueue"
import type { ScanFieldHandle } from "@/components/ScanField"
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
  const scanRef = useRef<ScanFieldHandle>(null)

  const { data: pulls } = useQuery({
    queryKey: ["project-pulls", stateFilter],
    queryFn: () =>
      ProjectPullsService.readProjectPulls({
        state: stateFilter === "ALL" ? undefined : stateFilter,
      }),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
  // Admin-only: the full projects list feeds the create-pull picker. Staff never
  // open create mode and GET /projects/ is admin-gated, so gating the query keeps
  // staff from triggering a 403. Display labels come from the pull rows below.
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: () => ProjectsService.readProjects(),
    staleTime: 5 * 60 * 1000,
    enabled: isAdmin,
  })
  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })

  // Built from the pull rows (each carries its project/customer labels) so staff,
  // who can't list projects, still render names instead of raw UUIDs.
  const projectLabels = useMemo(
    () =>
      new Map(
        (pulls ?? []).map((p) => [
          p.project_id,
          `${p.project_name} (${p.project_code})`,
        ]),
      ),
    [pulls],
  )
  const customerLabels = useMemo(
    () => new Map((pulls ?? []).map((p) => [p.customer_id, p.customer_name])),
    [pulls],
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

  const createMutation = useMutation<
    ProjectPullPublic,
    Error,
    ProjectPullCreate
  >({
    mutationFn: (payload) =>
      ProjectPullsService.createProjectPull({ requestBody: payload }),
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
    // Draft is seeded once here; a pull's lines are immutable after creation
    // (only fulfilled_qty/line_state change, at fulfill), so the 30s refetch
    // cannot invalidate the draft's line-id mapping.
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
      <PageHeader
        title="Project pulls"
        description="Fulfill pending pulls at the warehouse."
      />

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
          onSubmit={() =>
            createMutation.mutate(
              buildCreatePayload(createLines, projectId, adminNotes),
            )
          }
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
