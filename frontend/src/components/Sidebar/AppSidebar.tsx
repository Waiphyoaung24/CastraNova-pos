import {
  AlertTriangle,
  BadgePercent,
  BarChart3,
  Bell,
  Boxes,
  ClipboardList,
  Clock,
  Contact,
  FileWarning,
  FolderKanban,
  Home,
  Library,
  LifeBuoy,
  Package,
  PackagePlus,
  PieChart,
  RefreshCw,
  ScrollText,
  Search,
  Settings2,
  ShoppingCart,
  SlidersHorizontal,
  Store,
  Truck,
  Users,
  Warehouse,
  Wrench,
} from "lucide-react"

import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useRole } from "@/hooks/useRole"
import { type Entry, Main } from "./Main"
import { User } from "./User"

const baseItems: Entry[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  {
    icon: Store,
    title: "Sell",
    items: [
      { icon: ShoppingCart, title: "Sale", path: "/sale" },
      { icon: Search, title: "Search", path: "/search" },
    ],
  },
  {
    icon: Boxes,
    title: "Inventory",
    items: [
      // Stock-on-hand + serial/SKU lookup: both roles, no cost fields (FR-012/015).
      { icon: Warehouse, title: "Stock", path: "/stock" },
      // Low-stock reorder list: both roles read, admin edits thresholds (FR-016).
      { icon: AlertTriangle, title: "Low stock", path: "/low-stock" },
    ],
  },
  {
    icon: LifeBuoy,
    title: "Service",
    items: [
      // Tickets: staff + admin maintenance flow (FR-008). Online-only, no cost.
      { icon: Wrench, title: "Tickets", path: "/tickets" },
      // Pulls: staff + admin fulfill; admin create/cancel (FR-009). Online-only, no cost.
      { icon: ClipboardList, title: "Pulls", path: "/pulls" },
    ],
  },
  // Notification opt-in (LINE/Viber), per-user, both roles (FR-018).
  { icon: Bell, title: "Notifications", path: "/notifications" },
]

// Admin-only (admin = is_superuser || BKK_ADMIN, per the role matrix); backend
// get_admin is the real gate. Projects list/create are admin-gated, so project
// management lives here rather than in the staff-visible base nav.
const adminItems: Entry[] = [
  {
    icon: Library,
    title: "Catalog",
    items: [
      { icon: Package, title: "Products", path: "/products" },
      { icon: Truck, title: "Suppliers", path: "/suppliers" },
      { icon: Contact, title: "Customers", path: "/customers" },
      { icon: FolderKanban, title: "Projects", path: "/projects" },
    ],
  },
  {
    icon: Settings2,
    title: "Operations",
    items: [
      // Receive: admin-only warehouse intake (FR-005/006; restricted from staff
      // 2026-06-17). Backend get_admin is the real gate.
      { icon: PackagePlus, title: "Receive", path: "/receive" },
      { icon: SlidersHorizontal, title: "Adjust", path: "/stock-adjustment" },
      // Pricing-override approval queue — admin decides PENDING deviations (FR-010).
      { icon: BadgePercent, title: "Overrides", path: "/pricing-overrides" },
      { icon: RefreshCw, title: "Sync review", path: "/sync-review" },
    ],
  },
  {
    icon: BarChart3,
    title: "Reports",
    items: [
      // Reports expose revenue/COGS/margin + holding ageing — admin-only (FR-013/014).
      { icon: PieChart, title: "Channel margin", path: "/channel-margin" },
      { icon: Clock, title: "Holding period", path: "/holding-period" },
      // Monthly pricing-override exceptions audit (FR-010 §8).
      {
        icon: FileWarning,
        title: "Overrides report",
        path: "/override-exceptions",
      },
    ],
  },
  // Append-only audit ledger viewer + offline sync-review queue — admin-only.
  { icon: ScrollText, title: "Audit", path: "/audit" },
]

// User-management page — Superuser-only (Superuser owns user management).
const superuserItems: Entry[] = [
  { icon: Users, title: "Admin", path: "/admin" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { isAdmin, isSuperuser } = useRole()

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main entries={baseItems} label="Workspace" />
        {isAdmin ? <Main entries={adminItems} label="Admin" /> : null}
        {isSuperuser ? <Main entries={superuserItems} label="Users" /> : null}
      </SidebarContent>
      <SidebarFooter>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
