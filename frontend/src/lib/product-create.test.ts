import { describe, expect, it } from "vitest"

import {
  buildAutoSku,
  generateSkuBase,
  randomSkuSuffix,
  slugify,
} from "./product-create"

describe("slugify", () => {
  it("uppercases and hyphenates words", () => {
    expect(slugify("iPhone 15 Pro")).toBe("IPHONE-15-PRO")
  })

  it("collapses runs of symbols/whitespace into a single hyphen", () => {
    expect(slugify("Air  Con / 2.5kW")).toBe("AIR-CON-2-5KW")
  })

  it("strips leading and trailing separators", () => {
    expect(slugify("  --Widget!!  ")).toBe("WIDGET")
  })

  it("drops non-alphanumeric (incl. non-ASCII) characters", () => {
    expect(slugify("Café Ⓡ 100")).toBe("CAF-100")
  })

  it("returns empty string for input with no alphanumerics", () => {
    expect(slugify("  ---  ")).toBe("")
    expect(slugify("")).toBe("")
  })
})

describe("generateSkuBase", () => {
  it("combines brand and model", () => {
    expect(
      generateSkuBase({ brand: "Apple", modelName: "iPhone 15 Pro" }),
    ).toBe("APPLE-IPHONE-15-PRO")
  })

  it("falls back to model only when brand is blank", () => {
    expect(generateSkuBase({ brand: "", modelName: "Widget" })).toBe("WIDGET")
    expect(generateSkuBase({ brand: "   ", modelName: "Widget" })).toBe(
      "WIDGET",
    )
  })

  it("returns empty string when model is blank", () => {
    expect(generateSkuBase({ brand: "Apple", modelName: "" })).toBe("")
    expect(generateSkuBase({ brand: "", modelName: "" })).toBe("")
  })
})

describe("randomSkuSuffix", () => {
  it("is 4 chars from the A-Z0-9 alphabet", () => {
    for (let i = 0; i < 50; i++) {
      expect(randomSkuSuffix()).toMatch(/^[A-Z0-9]{4}$/)
    }
  })
})

describe("buildAutoSku", () => {
  it("joins base and suffix with a hyphen", () => {
    expect(buildAutoSku("APPLE-IPHONE", "7K2A")).toBe("APPLE-IPHONE-7K2A")
  })

  it("returns empty string when base is empty (no bare suffix)", () => {
    expect(buildAutoSku("", "7K2A")).toBe("")
  })
})
