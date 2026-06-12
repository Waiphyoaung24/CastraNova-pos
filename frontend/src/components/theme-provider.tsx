import { createContext, useContext, useEffect } from "react"

// The app is dark-only. This provider exists so `useTheme()` consumers
// (sonner toaster, etc.) keep a stable API; it always forces the `dark` class.
type ThemeProviderState = {
  theme: "dark"
  resolvedTheme: "dark"
  setTheme: () => void
}

const initialState: ThemeProviderState = {
  theme: "dark",
  resolvedTheme: "dark",
  setTheme: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

export function ThemeProvider({
  children,
}: {
  children: React.ReactNode
  // Accepted for call-site compatibility (main.tsx passes these); ignored.
  defaultTheme?: string
  storageKey?: string
}) {
  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove("light")
    root.classList.add("dark")
  }, [])

  return (
    <ThemeProviderContext.Provider value={initialState}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeProviderContext)
