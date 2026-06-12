import {
  AlertTriangle,
  BadgePercent,
  Bell,
  ClipboardList,
  Clock,
  FileWarning,
  FolderKanban,
  Home,
  Package,
  PackagePlus,
  PieChart,
  RefreshCw,
  ScrollText,
  Search,
  ShoppingCart,
  SlidersHorizontal,
  Truck,
  Users,
  Warehouse,
  Wrench,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useRole } from "@/hooks/useRole"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  // Stock-on-hand + serial/SKU lookup: both roles, no cost fields (FR-012/015).
  { icon: Warehouse, title: "Stock", path: "/stock" },
  // Low-stock reorder list: both roles read, admin edits thresholds (FR-016).
  { icon: AlertTriangle, title: "Low stock", path: "/low-stock" },
  { icon: Search, title: "Search", path: "/search" },
  { icon: ShoppingCart, title: "Sale", path: "/sale" },
  // Receive: staff + admin (YGN warehouse intake, FR-005/006). Staff enter the
  // supplier purchase cost off the delivery invoice; sales COGS/margin stay
  // redacted. Backend authorizes both roles.
  { icon: PackagePlus, title: "Receive", path: "/receive" },
  // Tickets: staff + admin maintenance flow (FR-008). Online-only, no cost.
  { icon: Wrench, title: "Tickets", path: "/tickets" },
  // Pulls: staff + admin fulfill; admin create/cancel (FR-009). Online-only, no cost.
  { icon: ClipboardList, title: "Pulls", path: "/pulls" },
  // Notification opt-in (LINE/Viber), per-user, both roles (FR-018).
  { icon: Bell, title: "Notifications", path: "/notifications" },
]

// Admin-only (admin = is_superuser || BKK_ADMIN, per the role matrix); backend
// get_admin is the real gate. Projects list/create are admin-gated, so project
// management lives here rather than in the staff-visible base nav.
const adminItems: Item[] = [
  { icon: Package, title: "Products", path: "/products" },
  { icon: Truck, title: "Suppliers", path: "/suppliers" },
  { icon: FolderKanban, title: "Projects", path: "/projects" },
  { icon: SlidersHorizontal, title: "Adjust", path: "/stock-adjustment" },
  // Pricing-override approval queue — admin decides PENDING deviations (FR-010).
  { icon: BadgePercent, title: "Overrides", path: "/pricing-overrides" },
  // Append-only audit ledger viewer + offline sync-review queue — admin-only.
  { icon: ScrollText, title: "Audit", path: "/audit" },
  { icon: RefreshCw, title: "Sync review", path: "/sync-review" },
  // Reports expose revenue/COGS/margin + holding ageing — admin-only (FR-013/014).
  { icon: PieChart, title: "Channel margin", path: "/channel-margin" },
  { icon: Clock, title: "Holding period", path: "/holding-period" },
  // Monthly pricing-override exceptions audit (FR-010 §8).
  {
    icon: FileWarning,
    title: "Overrides report",
    path: "/override-exceptions",
  },
  { icon: Users, title: "Admin", path: "/admin" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { isAdmin } = useRole()

  const items = isAdmin ? [...baseItems, ...adminItems] : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
