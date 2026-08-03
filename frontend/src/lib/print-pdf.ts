import { API_BASE } from "./api-base"

/** Fetches an authed binary PDF and opens it in a new browser tab.
 *
 * Label PDFs are authed binary downloads that the generated SDK types as
 * `unknown`, so this is the app's one sanctioned bare fetch — it attaches the
 * bearer token by hand. Returns a result code the caller maps to a toast;
 * never throws.
 *
 * The tab is opened SYNCHRONOUSLY, before the await: browsers only allow a new
 * tab while a click's transient user activation is live, and the activation is
 * gone by the time the fetch resolves — opening it afterwards is blocked as an
 * unsolicited popup. We then point that already-open tab at the blob URL once
 * the PDF arrives. (We can't pass `noopener`/`noreferrer` here, as those null
 * the window reference we need to navigate; it's safe because the tab only ever
 * loads our own same-origin blob PDF, which cannot script the opener.)
 *
 * `path` is the API path AFTER `/api/v1` (e.g. "/products/<id>/label.pdf?qty=3").
 */
export type PrintPdfResult =
  | "ok"
  | "no-token"
  | "fetch-failed"
  | "popup-blocked"

export async function openAuthedPdf(path: string): Promise<PrintPdfResult> {
  const token = localStorage.getItem("access_token")
  if (!token) return "no-token"
  const win = window.open("", "_blank")
  if (!win) return "popup-blocked"
  let url: string | null = null
  try {
    const res = await fetch(`${API_BASE}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    // A present-but-expired token surfaces as 401; treat it as a session
    // expiry (same message as a missing token) rather than a generic failure.
    if (res.status === 401) {
      win.close()
      return "no-token"
    }
    if (!res.ok) {
      win.close()
      return "fetch-failed"
    }
    url = URL.createObjectURL(await res.blob())
    win.location.href = url
    // The new tab needs the object URL alive while it loads the blob; revoke
    // after a delay so it is not leaked for the page's lifetime.
    const created = url
    setTimeout(() => URL.revokeObjectURL(created), 60_000)
    return "ok"
  } catch {
    win.close()
    if (url) URL.revokeObjectURL(url)
    return "fetch-failed"
  }
}
