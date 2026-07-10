import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { OpenAPI } from "./client"
import { OfflineIndicator } from "./components/OfflineIndicator"
import { ReloadPrompt } from "./components/ReloadPrompt"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import {
  divertStaleMutations,
  persister,
  queryClient,
} from "./lib/query-client"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}

// Replay offline-queued mutations as soon as the network returns — but first
// hold back anything older than the 7-day cap for admin review.
window.addEventListener("online", () => {
  divertStaleMutations()
  queryClient.resumePausedMutations()
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{ persister }}
        onSuccess={() => {
          // Once the persisted cache is restored, hold back stale mutations,
          // then resume any that were paused while offline before the reload.
          divertStaleMutations()
          queryClient.resumePausedMutations()
        }}
      >
        <RouterProvider router={router} />
        <OfflineIndicator />
        <ReloadPrompt />
        <Toaster richColors closeButton />
      </PersistQueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
