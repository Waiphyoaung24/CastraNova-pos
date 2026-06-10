import type { ProductCreate, TrackingMode } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Products create form (FR-001). sku + model +
// both prices are required; prices must be valid non-negative numbers and are
// sent as trimmed strings (the backend accepts number | string). Blank
// optionals are dropped.
// ---------------------------------------------------------------------------

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
  if (minStock !== "") payload.default_min_stock_level = Number(minStock)
  return payload
}
