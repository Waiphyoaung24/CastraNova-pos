import { Home, PackagePlus, Users } from "lucide-react"

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

const baseItems: Item[] = [{ icon: Home, title: "Dashboard", path: "/" }]

// Admin-only (admin = is_superuser || BKK_ADMIN, per the role matrix). Receive
// enters purchase cost, so it is admin-only; backend get_admin is the real gate.
const adminItems: Item[] = [
  { icon: PackagePlus, title: "Receive", path: "/receive" },
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
