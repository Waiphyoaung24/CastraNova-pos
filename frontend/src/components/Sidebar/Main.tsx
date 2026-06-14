import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import { ChevronRight, type LucideIcon } from "lucide-react"
import { useEffect, useState } from "react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

// A nav entry is either a direct link (Item) or a collapsible group of links.
export type Group = {
  icon: LucideIcon
  title: string
  items: Item[]
}

export type Entry = Item | Group

const isGroup = (entry: Entry): entry is Group => "items" in entry

interface MainProps {
  entries: Entry[]
  label?: string
}

export function Main({ entries, label }: MainProps) {
  const { isMobile, setOpenMobile, state } = useSidebar()
  const currentPath = useRouterState().location.pathname

  // When collapsed to icons, labels and submenus are hidden — flatten groups
  // back to plain icons so every destination stays one click away.
  const iconMode = state === "collapsed" && !isMobile

  const handleNavigate = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  const flat = entries.flatMap((e) => (isGroup(e) ? e.items : [e]))

  return (
    <SidebarGroup>
      {label ? <SidebarGroupLabel>{label}</SidebarGroupLabel> : null}
      <SidebarGroupContent>
        <SidebarMenu>
          {iconMode
            ? flat.map((item) => (
                <NavLink
                  key={item.path}
                  item={item}
                  active={currentPath === item.path}
                  onNavigate={handleNavigate}
                />
              ))
            : entries.map((entry) =>
                isGroup(entry) ? (
                  <NavGroup
                    key={entry.title}
                    group={entry}
                    currentPath={currentPath}
                    onNavigate={handleNavigate}
                  />
                ) : (
                  <NavLink
                    key={entry.path}
                    item={entry}
                    active={currentPath === entry.path}
                    onNavigate={handleNavigate}
                  />
                ),
              )}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

interface NavLinkProps {
  item: Item
  active: boolean
  onNavigate: () => void
}

function NavLink({ item, active, onNavigate }: NavLinkProps) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton tooltip={item.title} isActive={active} asChild>
        <RouterLink to={item.path} onClick={onNavigate}>
          <item.icon />
          <span>{item.title}</span>
        </RouterLink>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

interface NavGroupProps {
  group: Group
  currentPath: string
  onNavigate: () => void
}

function NavGroup({ group, currentPath, onNavigate }: NavGroupProps) {
  const containsActive = group.items.some((i) => i.path === currentPath)
  const [open, setOpen] = useState(containsActive)

  // Reveal the group when the user navigates into one of its items.
  useEffect(() => {
    if (containsActive) {
      setOpen(true)
    }
  }, [containsActive])

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        type="button"
        tooltip={group.title}
        data-state={open ? "open" : "closed"}
        onClick={() => setOpen((v) => !v)}
      >
        <group.icon />
        <span>{group.title}</span>
        <ChevronRight
          className={cn(
            "ml-auto transition-transform duration-200",
            open && "rotate-90",
          )}
        />
      </SidebarMenuButton>
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-in-out",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <SidebarMenuSub>
            {group.items.map((item) => (
              <SidebarMenuSubItem key={item.path}>
                <SidebarMenuSubButton
                  isActive={currentPath === item.path}
                  asChild
                >
                  <RouterLink to={item.path} onClick={onNavigate}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </div>
      </div>
    </SidebarMenuItem>
  )
}
