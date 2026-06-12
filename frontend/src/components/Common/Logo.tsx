import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"
import logo from "/assets/images/castranova-logo.jpg"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

// The brand mark is a gold-on-black JPG. `mix-blend-lighten` drops the pure-black
// background against the app's dark surfaces so only the gold mark shows.
const BLEND = "mix-blend-lighten"

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <img
          src={logo}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "h-10 w-auto group-data-[collapsible=icon]:hidden",
            className,
          )}
        />
        <img
          src={logo}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "size-7 hidden group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : (
      <img
        src={logo}
        alt="CASTRA NOVA"
        className={cn(
          BLEND,
          variant === "full" ? "h-12 w-auto" : "size-7",
          className,
        )}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
