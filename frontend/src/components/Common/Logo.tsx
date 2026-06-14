import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"
// Square brand mark (used for the collapsed icon + favicon).
import logoMark from "/assets/images/castranova-logo.jpg"
// Padding-trimmed wordmark (~2.5:1) so the brand reads at a compact sidebar height.
import logoWordmark from "/assets/images/castranova-logo-trimmed.png"

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
          src={logoWordmark}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "h-12 w-auto group-data-[collapsible=icon]:hidden",
            className,
          )}
        />
        <img
          src={logoMark}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "size-8 hidden group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : variant === "full" ? (
      <img
        src={logoWordmark}
        alt="CASTRA NOVA"
        className={cn(BLEND, "h-14 w-auto", className)}
      />
    ) : (
      <img
        src={logoMark}
        alt="CASTRA NOVA"
        className={cn(BLEND, "size-8", className)}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
