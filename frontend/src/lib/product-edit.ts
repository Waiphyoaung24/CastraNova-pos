import type { ProductPublic, ProductUpdate } from "@/client/types.gen"

// Pure form logic for the admin product EDIT dialog. Mirrors product-create.ts:
// model name + both prices are required; prices are non-negative numbers sent as
// trimmed strings. Cleared optionals are sent as null so the change persists.
// is_active is always sent: retiring/reactivating is an ordinary edit here.

export interface ProductEditDraft {
  // Editable only while the product is fresh (no stock/transactions); the dialog
  // disables the field otherwise. The backend enforces the same rule.
  sku: string
  modelName: string
  brand: string
  category: string
  minStock: string
  retailPrice: string
  repairPrice: string
  isActive: boolean
}

function isValidPrice(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return false
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function productToDraft(p: ProductPublic): ProductEditDraft {
  return {
    sku: p.sku,
    modelName: p.model_name,
    brand: p.brand ?? "",
    category: p.category ?? "",
    minStock:
      p.default_min_stock_level != null
        ? String(p.default_min_stock_level)
        : "",
    retailPrice: String(p.retail_price_thb),
    repairPrice: String(p.repair_price_thb),
    // Optional on ProductPublic (server-side default), so absence means active.
    isActive: p.is_active ?? true,
  }
}

export function canSaveProduct(d: ProductEditDraft): boolean {
  return (
    d.sku.trim() !== "" &&
    d.modelName.trim() !== "" &&
    isValidPrice(d.retailPrice) &&
    isValidPrice(d.repairPrice)
  )
}

export function buildProductUpdate(d: ProductEditDraft): ProductUpdate {
  const minStock = d.minStock.trim()
  const minStockNum = Number(minStock)
  const brand = d.brand.trim()
  const category = d.category.trim()
  return {
    // Always sent; the backend only acts on it when it actually differs, and
    // rejects a change on a non-fresh product. For a used product the field is
    // disabled, so this equals the current SKU and is a no-op.
    sku: d.sku.trim(),
    model_name: d.modelName.trim(),
    brand: brand === "" ? null : brand,
    category: category === "" ? null : category,
    retail_price_thb: d.retailPrice.trim(),
    repair_price_thb: d.repairPrice.trim(),
    default_min_stock_level:
      minStock !== "" && Number.isFinite(minStockNum) && minStockNum >= 0
        ? minStockNum
        : null,
    is_active: d.isActive,
  }
}
