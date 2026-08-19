import type { ProductCreate, TrackingMode } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Products create form (FR-001). sku + model +
// both prices are required; prices must be valid non-negative numbers and are
// sent as trimmed strings (the backend accepts number | string). Blank
// optionals are dropped.
// ---------------------------------------------------------------------------

// --- SKU auto-suggestion --------------------------------------------------
// The create form pre-fills the SKU from brand + model as a convenience; the
// field stays a normal editable input (see ProductCreateDialog). All logic is
// pure so it is unit-testable without the stack.

/** Uppercase, collapse runs of non-alphanumerics into single hyphens, and trim
 * leading/trailing hyphens. Non-ASCII characters are dropped. */
export function slugify(value: string): string {
  return value
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

/** Slug from brand + model. Blank brand falls back to model only; a blank model
 * yields "" — the model is the product, so there is nothing to suggest until it
 * is entered (and it is required to create anyway). */
export function generateSkuBase({
  brand,
  modelName,
}: {
  brand: string
  modelName: string
}): string {
  if (modelName.trim() === "") return ""
  return slugify(
    [brand, modelName]
      .map((s) => s.trim())
      .filter(Boolean)
      .join(" "),
  )
}

const SKU_SUFFIX_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

/** A 4-char A-Z0-9 suffix so auto-suggested SKUs rarely collide. Uses the Web
 * Crypto RNG (browser runtime). */
export function randomSkuSuffix(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  let out = ""
  for (const b of bytes) {
    out += SKU_SUFFIX_ALPHABET[b % SKU_SUFFIX_ALPHABET.length]
  }
  return out
}

/** Join a base slug and suffix, e.g. "APPLE-IPHONE" + "7K2A". An empty base
 * yields "" — never a bare "-SUFFIX". */
export function buildAutoSku(base: string, suffix: string): string {
  return base ? `${base}-${suffix}` : ""
}

export interface ProductDraft {
  sku: string
  modelName: string
  brand: string
  category: string
  trackingMode: TrackingMode
  retailPrice: string
  repairPrice: string
  minStock: string
}

function isValidPrice(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return false
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function canCreateProduct(d: ProductDraft): boolean {
  return (
    d.sku.trim() !== "" &&
    d.modelName.trim() !== "" &&
    isValidPrice(d.retailPrice) &&
    isValidPrice(d.repairPrice)
  )
}

export function buildProductPayload(d: ProductDraft): ProductCreate {
  const payload: ProductCreate = {
    sku: d.sku.trim(),
    model_name: d.modelName.trim(),
    tracking_mode: d.trackingMode,
    retail_price_thb: d.retailPrice.trim(),
    repair_price_thb: d.repairPrice.trim(),
  }
  const brand = d.brand.trim()
  const category = d.category.trim()
  const minStock = d.minStock.trim()
  if (brand) payload.brand = brand
  if (category) payload.category = category
  const minStockNum = Number(minStock)
  if (minStock !== "" && Number.isFinite(minStockNum) && minStockNum >= 0) {
    payload.default_min_stock_level = minStockNum
  }
  return payload
}
