import type { ProductPublic, ProductUpdate } from "@/client/types.gen"

// Pure form logic for the admin product EDIT dialog. Mirrors product-create.ts:
// model name + both prices are required; prices are non-negative numbers sent as
// trimmed strings. Cleared optionals are sent as null so the change persists.

export interface ProductEditDraft {
  modelName: string
  brand: string
  category: string
  minStock: string
  retailPrice: string
  repairPrice: string
}

function isValidPrice(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return false
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function productToDraft(p: ProductPublic): ProductEditDraft {
  return {
    modelName: p.model_name,
    brand: p.brand ?? "",
    category: p.category ?? "",
    minStock:
      p.default_min_stock_level != null ? String(p.default_min_stock_level) : "",
    retailPrice: String(p.retail_price_thb),
    repairPrice: String(p.repair_price_thb),
  }
}

export function canSaveProduct(d: ProductEditDraft): boolean {
  return (
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
    model_name: d.modelName.trim(),
    brand: brand === "" ? null : brand,
    category: category === "" ? null : category,
    retail_price_thb: d.retailPrice.trim(),
    repair_price_thb: d.repairPrice.trim(),
    default_min_stock_level:
      minStock !== "" && Number.isFinite(minStockNum) && minStockNum >= 0
        ? minStockNum
        : null,
  }
}
