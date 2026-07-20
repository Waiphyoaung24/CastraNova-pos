export function stockDrillQueryKey(
  kind: "batches" | "units",
  productId: string,
  isAdmin: boolean,
) {
  return [`stock-${kind}`, productId, isAdmin ? "admin" : "staff"] as const
}

export function isSensitiveStockQueryKey(
  queryKey: readonly unknown[],
): boolean {
  return queryKey[0] === "stock-batches" || queryKey[0] === "stock-units"
}
