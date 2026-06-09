import { Home, PackagePlus, ShoppingCart, Users, Wrench } from "lucide-react"

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
  { icon: ShoppingCart, title: "Sale", path: "/sale" },
  // Receive: staff + admin (YGN warehouse intake, FR-005/006). Staff enter the
  // supplier purchase cost off the delivery invoice; sales COGS/margin stay
  // redacted. Backend authorizes both roles.
  { icon: PackagePlus, title: "Receive", path: "/receive" },
  // Tickets: staff + admin maintenance flow (FR-008). Online-only, no cost.
  { icon: Wrench, title: "Tickets", path: "/tickets" },
]

// Admin-only (admin = is_superuser || BKK_ADMIN, per the role matrix); backend
// get_admin is the real gate.
const adminItems: Item[] = [{ icon: Users, title: "Admin", path: "/admin" }]

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
