import { createFileRoute, Link } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import {
  AlertTriangle,
  Bell,
  ClipboardList,
  PackagePlus,
  Search,
  ShoppingCart,
  Warehouse,
  Wrench,
} from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard · CASTRA NOVA" }],
  }),
})

type Action = { icon: LucideIcon; title: string; desc: string; path: string }

const actions: Action[] = [
  {
    icon: ShoppingCart,
    title: "New Sale",
    desc: "Scan and check out",
    path: "/sale",
  },
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
    icon: PackagePlus,
    title: "Receive",
    desc: "Log incoming inventory",
    path: "/receive",
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

function Dashboard() {
  const { user: currentUser } = useAuth()
  const name = currentUser?.full_name || currentUser?.email

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Welcome back, {name}
        </h1>
        <p className="text-muted-foreground">Jump straight into a task.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {actions.map((a) => (
          <Link key={a.path} to={a.path} className="group">
            <Card className="h-full transition-colors hover:border-primary/60">
              <CardContent className="flex flex-col gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <a.icon className="size-5" />
                </span>
                <div>
                  <div className="font-medium">{a.title}</div>
                  <div className="text-muted-foreground text-sm">{a.desc}</div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
