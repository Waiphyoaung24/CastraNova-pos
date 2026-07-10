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
  endSession,
  ensureValidSession,
  installAuthInterceptor,
} from "./lib/auth-session"
import { persister, queryClient } from "./lib/query-client"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}
// Refresh-then-retry on 401: an active user's short access token is renewed
// transparently; only a dead refresh cookie (12h idle) reaches endSession.
installAuthInterceptor()

// On load, proactively verify the session. A dead/idle token otherwise stays
// invisible when the first view is served from the persisted query cache (no
// request fires to trip the 401 interceptor). Skip on /login and while offline
// (offline mode must keep working; the online listener re-checks on reconnect).
if (navigator.onLine && !window.location.pathname.startsWith("/login")) {
  void ensureValidSession()
    .then((ok) => {
      if (!ok) endSession()
    })
    .catch(() => {
      // Network/unknown error — do not force logout; the interceptor handles a
      // real 401 on the next request.
    })
}

// Replay offline-queued mutations as soon as the network returns — but only
// once we hold a valid session, so a replay never fires with a dead token
// (which would error the mutation out of the queue and lose the sale).
window.addEventListener("online", async () => {
  if (await ensureValidSession()) queryClient.resumePausedMutations()
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
          // Once the persisted cache is restored, resume any mutations that
          // were paused while offline before the last reload.
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
