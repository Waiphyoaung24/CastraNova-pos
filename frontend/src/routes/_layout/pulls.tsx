import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  DashboardsService,
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
import { useProductOptions } from "@/hooks/useProductOptions"
import { useRole } from "@/hooks/useRole"
import { useScanLookup } from "@/hooks/useScanLookup"
import {
  addPartToCreateCart,
  addUnitsToCreateCart,
  buildCreatePayload,
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
import { queued } from "@/lib/query-client"
import { requireAuth } from "@/lib/route-guards"
import type { Queued } from "@/lib/sync-producer"

export const Route = createFileRoute("/_layout/pulls")({
  component: Pulls,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Stock requests - CastraNova POS" }],
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
  const [isAddingItem, setIsAddingItem] = useState(false)
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
  const { data: products } = useProductOptions()

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
  const selectedPull = useMemo(
    () => (pulls ?? []).find((p) => p.id === selectedPullId),
    [pulls, selectedPullId],
  )

  const { resolve, result, isSearching, notFound, isError, reset } =
    useScanLookup()

  // Route each fulfill scan to the selected pull. A scan that matches no line
  // (and isn't NOT_FOUND) surfaces a context notice. Create mode no longer scans.
  useEffect(() => {
    if (!result) return
    if (selectedPull) {
      const next = applyScanToFulfill(fulfillDraft, selectedPull.lines, result)
      if (next === fulfillDraft && result.kind !== "NOT_FOUND") {
        setScanNotice("That part isn't on this request — scan a different one.")
      } else {
        setFulfillDraft(next)
        setScanNotice("")
      }
    }
    reset()
  }, [result, selectedPull, fulfillDraft, reset])

  const fulfillMutation = useMutation<
    ProjectPullPublic,
    Error,
    Queued<{ pullId: string; requestBody: ProjectPullFulfill }>
  >({
    // No mutationFn: inherit the persisted ["pull-fulfill"] default from
    // query-client.ts so an offline fulfill is queued and replayed by key.
    mutationKey: ["pull-fulfill"],
    onSuccess: (pull) => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast(
        pull.state === "FULFILLED"
          ? "Parts given out."
          : "Parts given out — some items still short.",
      )
      setSelectedPullId(null)
      setFulfillDraft({})
      setScanNotice("")
    },
    onError: () =>
      showErrorToast("Could not give out the parts. Please try again."),
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
      showSuccessToast("Request created.")
      setMode("queue")
      setCreateLines([])
      setProjectId("")
      setAdminNotes("")
      setScanNotice("")
    },
    onError: () =>
      showErrorToast("Could not create the request. Please try again."),
  })

  const cancelMutation = useMutation({
    mutationFn: (pullId: string) =>
      ProjectPullsService.cancelProjectPull({ pullId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Request cancelled.")
    },
    onError: () =>
      showErrorToast("Could not cancel the request. Please try again."),
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

  const handleAddItem = useCallback(
    async (productId: string, qty: number) => {
      const product = (products ?? []).find((p) => p.id === productId)
      if (!product) return
      const meta = {
        productId: product.id,
        sku: product.sku,
        modelName: product.model_name,
      }
      if (product.tracking_mode === "SERIALIZED") {
        setIsAddingItem(true)
        try {
          // ponytail: auto-claim oldest N serials at create time. A concurrent
          // create can grab the same serial → one line settles SHORT at
          // fulfillment. Upgrade path: claim serials at fulfill time instead.
          const units = await DashboardsService.getStockOnHandUnits({
            productId,
          })
          const present = new Set(
            createLines.filter((l) => l.lineKind === "UNIT").map((l) => l.key),
          )
          const available = units
            .map((u) => u.castranova_barcode)
            .filter((s) => !present.has(s))
          const take = available.slice(0, qty)
          if (take.length === 0) {
            setScanNotice("No units in stock for that item.")
          } else {
            setCreateLines((prev) => addUnitsToCreateCart(prev, meta, take))
            setScanNotice(
              take.length < qty
                ? `Only ${take.length} in stock — added what's available.`
                : "",
            )
          }
        } catch {
          setScanNotice("Couldn't load stock for that item. Try again.")
        } finally {
          setIsAddingItem(false)
        }
      } else {
        setScanNotice("")
        setCreateLines((prev) => addPartToCreateCart(prev, meta, qty))
      }
    },
    [products, createLines],
  )

  const handleFulfill = useCallback(() => {
    if (!selectedPull) return
    fulfillMutation.mutate(
      queued(
        {
          pullId: selectedPull.id,
          requestBody: buildFulfillPayload(fulfillDraft),
        },
        crypto.randomUUID(),
      ),
    )
  }, [selectedPull, fulfillDraft, fulfillMutation])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Stock requests"
        description="Give out parts for project requests."
      />

      {mode === "create" ? (
        <PullCreatePanel
          projects={projects ?? []}
          projectId={projectId}
          onProjectChange={setProjectId}
          adminNotes={adminNotes}
          onNotesChange={setAdminNotes}
          lines={createLines}
          products={products ?? []}
          onAddItem={handleAddItem}
          addNotice={scanNotice}
          isAdding={isAddingItem}
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
