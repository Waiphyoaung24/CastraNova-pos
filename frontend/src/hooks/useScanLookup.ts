import { useMutation } from "@tanstack/react-query"
import { ApiError } from "@/client/core/ApiError"
import { SearchService } from "@/client/sdk.gen"
import type { SerialSearchResult, SkuSearchResult } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Outcome types
// ---------------------------------------------------------------------------

export type ScanLookupResult =
  | { kind: "UNIT"; data: SerialSearchResult }
  | { kind: "PART"; data: SkuSearchResult }
  | { kind: "NOT_FOUND" }

// ---------------------------------------------------------------------------
// Pure resolver — testable without React
// ---------------------------------------------------------------------------

/**
 * Given the raw outcomes of a serial search and a sku search, return the
 * typed lookup result. Each arg is either the successful response data or the
 * thrown ApiError (or null if the step was never attempted because a previous
 * step succeeded).
 *
 * Resolution order: serial hit → UNIT; serial 404 + sku hit → PART; both 404
 * → NOT_FOUND. Any non-404 error is re-thrown so callers see real failures.
 */
export function resolveScanResult(
  serialOutcome: SerialSearchResult | ApiError,
  skuOutcome: SkuSearchResult | ApiError | null,
): ScanLookupResult {
  if (!(serialOutcome instanceof ApiError)) {
    return { kind: "UNIT", data: serialOutcome }
  }
  // serial was an error — only accept 404 as "not found"; anything else is a
  // real failure that should bubble up
  if (serialOutcome.status !== 404) throw serialOutcome

  // sku step
  if (skuOutcome === null) {
    // shouldn't happen in normal flow, treat as not-found
    return { kind: "NOT_FOUND" }
  }
  if (!(skuOutcome instanceof ApiError)) {
    return { kind: "PART", data: skuOutcome }
  }
  if (skuOutcome.status !== 404) throw skuOutcome
  return { kind: "NOT_FOUND" }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseScanLookupReturn {
  /**
   * Fire-and-forget trigger for the given scanned code (`mutate`, not
   * awaitable). Non-404 API errors do NOT throw to the caller — they surface
   * via `error` / `isError` instead.
   */
  resolve: (code: string) => void
  /** The resolved result once a lookup completes, or undefined while idle. */
  result: ScanLookupResult | undefined
  /** True while a lookup is in flight. */
  isSearching: boolean
  /** True when the last lookup ended with NOT_FOUND. */
  notFound: boolean
  /** The ApiError from the last failed lookup, or null when idle/succeeded. */
  error: ApiError | null
  /** True when the last lookup ended with a non-404 API error. */
  isError: boolean
  /** Reset result and error state back to idle. */
  reset: () => void
}

/**
 * Resolves a scanned barcode (from useScanner or CameraScanFallback) to a
 * typed inventory entity.
 *
 * Usage:
 *   const { resolve, result, isSearching, notFound } = useScanLookup()
 *   // wire into ScanInput: <ScanInput onScan={resolve} />
 */
export function useScanLookup(): UseScanLookupReturn {
  const mutation = useMutation<ScanLookupResult, ApiError, string>({
    mutationFn: async (code: string): Promise<ScanLookupResult> => {
      let serialOutcome: SerialSearchResult | ApiError
      try {
        serialOutcome = await SearchService.searchSerial({ barcode: code })
      } catch (err) {
        if (err instanceof ApiError) {
          serialOutcome = err
        } else {
          throw err
        }
      }

      // Short-circuit: if we already have a unit, no need to try sku
      if (!(serialOutcome instanceof ApiError)) {
        return resolveScanResult(serialOutcome, null)
      }
      // serial was 404 — re-throw non-404 immediately
      if (serialOutcome.status !== 404) throw serialOutcome

      let skuOutcome: SkuSearchResult | ApiError
      try {
        skuOutcome = await SearchService.searchSku({ sku: code })
      } catch (err) {
        if (err instanceof ApiError) {
          skuOutcome = err
        } else {
          throw err
        }
      }

      return resolveScanResult(serialOutcome, skuOutcome)
    },
  })

  return {
    resolve: mutation.mutate,
    result: mutation.data,
    isSearching: mutation.isPending,
    notFound: mutation.data?.kind === "NOT_FOUND",
    error: mutation.error,
    isError: mutation.isError,
    reset: mutation.reset,
  }
}
