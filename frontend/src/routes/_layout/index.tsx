import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import {
  AlertTriangle,
  ArrowRight,
  BadgePercent,
  Bell,
  ClipboardList,
  Package,
  PackagePlus,
  PieChart,
  ScrollText,
  Search,
  ShoppingCart,
  SlidersHorizontal,
  Warehouse,
  Wrench,
} from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { useRole } from "@/hooks/useRole"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard · CASTRA NOVA" }],
  }),
})

type Action = { icon: LucideIcon; title: string; desc: string; path: string }

// Shared quick actions — both roles. "New Sale" is featured separately below.
// Receive is intentionally absent here: it is admin-only Operations (gated
// 2026-06-17) and lives in the admin section, mirroring the sidebar.
const quickActions: Action[] = [
  {
    icon: Search,
    title: "Search",
    desc: "Find products & serials",
    path: "/search",
  },
  {
    icon: Warehouse,
    title: "Stock",
    desc: "On-hand by location",
    path: "/stock",
  },
  {
    icon: AlertTriangle,
    title: "Low Stock",
    desc: "Items below reorder",
    path: "/low-stock",
  },
  {
    icon: Wrench,
    title: "Tickets",
    desc: "Service & repair",
    path: "/tickets",
  },
  {
    icon: ClipboardList,
    title: "Pulls",
    desc: "Fulfil pull requests",
    path: "/pulls",
  },
  {
    icon: Bell,
    title: "Notifications",
    desc: "Alerts & opt-in",
    path: "/notifications",
  },
]

// Admin-only operations — surfaced only when roleFlags().isAdmin is true.
// Backend get_admin remains the real gate; this just hides what staff can't use.
const adminActions: Action[] = [
  {
    icon: PackagePlus,
    title: "Receive",
    desc: "Log incoming inventory",
    path: "/receive",
  },
  {
    icon: SlidersHorizontal,
    title: "Adjust",
    desc: "Correct stock counts",
    path: "/stock-adjustment",
  },
  {
    icon: BadgePercent,
    title: "Overrides",
    desc: "Approve price deviations",
    path: "/pricing-overrides",
  },
  {
    icon: Package,
    title: "Products",
    desc: "Manage the catalog",
    path: "/products",
  },
  {
    icon: PieChart,
    title: "Reports",
    desc: "Channel margin & COGS",
    path: "/channel-margin",
  },
  {
    icon: ScrollText,
    title: "Audit",
    desc: "Append-only ledger",
    path: "/audit",
  },
]

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <h2 className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
        {children}
      </h2>
      <div className="h-px flex-1 bg-border" />
    </div>
  )
}

function ActionCard({ icon: Icon, title, desc, path }: Action) {
  return (
    <Link to={path} className="group block h-full">
      <Card className="h-full gap-0 py-0 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50">
        <CardContent className="flex h-full flex-col gap-3 p-5">
          <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
            <Icon className="size-5" />
          </span>
          <div>
            <div className="font-medium">{title}</div>
            <div className="text-muted-foreground text-sm">{desc}</div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function Dashboard() {
  const { user: currentUser } = useAuth()
  const { isAdmin } = useRole()
  const name = currentUser?.full_name || currentUser?.email

  return (
    <div className="flex flex-col gap-6 sm:gap-8">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight break-words sm:text-2xl">
            Welcome back, {name}
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Jump straight into a task.
          </p>
        </div>
        <span className="inline-flex shrink-0 items-center rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
          {isAdmin ? "Admin" : "Staff"}
        </span>
      </div>

      {/* Featured: New Sale — the primary POS action, in the gold CTA tone. */}
      <Link to="/sale" className="group block">
        <Card className="relative gap-0 overflow-hidden border-primary/25 py-0 transition-all duration-300 hover:border-primary/60">
          <div className="pointer-events-none absolute -right-16 -top-20 size-56 rounded-full bg-primary/15 blur-3xl transition-opacity duration-300 group-hover:bg-primary/25" />
          <CardContent className="relative flex items-center justify-between gap-3 p-5 sm:gap-4 sm:p-6">
            <div className="flex min-w-0 items-center gap-3 sm:gap-4">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/20 sm:size-14">
                <ShoppingCart className="size-6 sm:size-7" />
              </span>
              <div className="min-w-0">
                <div className="font-display text-lg font-semibold tracking-tight sm:text-xl">
                  New Sale
                </div>
                <div className="text-muted-foreground text-sm">
                  Scan items and check out a customer
                </div>
              </div>
            </div>
            <ArrowRight className="size-5 shrink-0 text-primary transition-transform duration-300 group-hover:translate-x-1" />
          </CardContent>
        </Card>
      </Link>

      <div className="flex flex-col gap-4">
        <SectionLabel>Quick actions</SectionLabel>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
          {quickActions.map((a) => (
            <ActionCard key={a.path} {...a} />
          ))}
        </div>
      </div>

      {isAdmin ? (
        <div className="flex flex-col gap-4">
          <SectionLabel>Admin operations</SectionLabel>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
            {adminActions.map((a) => (
              <ActionCard key={a.path} {...a} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
