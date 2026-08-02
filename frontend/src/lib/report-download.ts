import { API_BASE } from "./api-base"

// Authed binary download for report exports (PDF/XLSX).
//
// The generated SDK types these `.pdf`/`.xlsx` endpoints' responses as
// `unknown`, so they can't reliably yield a usable blob — this mirrors the
// sanctioned bare-fetch exception in receive.tsx (the label PDF). Triggers a
// browser download via a temporary anchor; works for both PDF and XLSX. Throws
// on a non-OK response so callers can surface a toast.
export async function downloadReport(
  path: string,
  filename: string,
): Promise<void> {
  const token = localStorage.getItem("access_token")
  if (!token) throw new Error("Session expired. Please log in again.")
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error("Export failed.")
  const url = URL.createObjectURL(await res.blob())
  try {
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
