/** Fetches an authed binary PDF and opens it in a new browser tab.
 *
 * Label PDFs are authed binary downloads that the generated SDK types as
 * `unknown`, so this is the app's one sanctioned bare fetch — it attaches the
 * bearer token by hand. Returns a result code the caller maps to a toast;
 * never throws.
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
  let url: string | null = null
  try {
    const res = await fetch(`${import.meta.env.VITE_API_URL}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    // A present-but-expired token surfaces as 401; treat it as a session
    // expiry (same message as a missing token) rather than a generic failure.
    if (res.status === 401) return "no-token"
    if (!res.ok) return "fetch-failed"
    url = URL.createObjectURL(await res.blob())
    const win = window.open(url, "_blank", "noopener,noreferrer")
    if (!win) {
      URL.revokeObjectURL(url)
      return "popup-blocked"
    }
    // The new tab needs the object URL alive while it loads the blob; revoke
    // after a delay so it is not leaked for the page's lifetime.
    const created = url
    setTimeout(() => URL.revokeObjectURL(created), 60_000)
    return "ok"
  } catch {
    if (url) URL.revokeObjectURL(url)
    return "fetch-failed"
  }
}
