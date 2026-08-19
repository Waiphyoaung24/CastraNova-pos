import { expect, test } from "@playwright/test"
import {
  addPartToCreateCart,
  addUnitsToCreateCart,
  buildCreatePayload,
  removeCreateLine,
  setCreateQty,
} from "../src/lib/pull-create"

// Pure-logic coverage of the project-pull create cart (dropdown adds).

const PROD_PART = {
  productId: "prod-cable",
  sku: "SKU-CABLE",
  modelName: "HDMI Cable",
}
const PROD_UNIT = {
  productId: "prod-laptop",
  sku: "SKU-LAPTOP",
  modelName: "Laptop 14",
}

test("addPartToCreateCart appends then merges qty by sku", () => {
  let lines = addPartToCreateCart([], PROD_PART, 3)
  expect(lines).toEqual([
    {
      key: "SKU-CABLE",
      lineKind: "PART",
      productId: "prod-cable",
      sku: "SKU-CABLE",
      modelName: "HDMI Cable",
      requestedQty: 3,
    },
  ])
  lines = addPartToCreateCart(lines, PROD_PART, 2)
  expect(lines).toHaveLength(1)
  expect(lines[0].requestedQty).toBe(5)
})

test("addPartToCreateCart floors qty at 1", () => {
  expect(addPartToCreateCart([], PROD_PART, 0)[0].requestedQty).toBe(1)
  expect(addPartToCreateCart([], PROD_PART, 4.9)[0].requestedQty).toBe(4)
})

test("addUnitsToCreateCart appends one UNIT line per serial", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(lines).toHaveLength(2)
  expect(lines.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
  expect(
    lines.every((l) => l.lineKind === "UNIT" && l.requestedQty === 1),
  ).toBe(true)
  expect(lines[0].unitSerial).toBe("CN-A1")
})

test("addUnitsToCreateCart skips serials already in the cart", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1"])
  expect(addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])).toBe(lines)
  const merged = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(merged.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
})

test("setCreateQty floors PART at 1; leaves UNIT untouched", () => {
  let lines = addPartToCreateCart([], PROD_PART, 1)
  lines = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])
  expect(setCreateQty(lines, "SKU-CABLE", 0)[0].requestedQty).toBe(1)
  expect(setCreateQty(lines, "SKU-CABLE", 4.9)[0].requestedQty).toBe(4)
  // UNIT line (second) is unaffected by a qty change targeting it
  expect(setCreateQty(lines, "CN-A1", 9)[1].requestedQty).toBe(1)
})

test("removeCreateLine drops the matching line", () => {
  let lines = addPartToCreateCart([], PROD_PART, 1)
  lines = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])
  expect(removeCreateLine(lines, "SKU-CABLE")).toEqual([
    expect.objectContaining({ key: "CN-A1" }),
  ])
})

test("buildCreatePayload shapes UNIT and PART lines; blank notes -> null", () => {
  let lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1"])
  lines = addPartToCreateCart(lines, PROD_PART, 5)
  expect(buildCreatePayload(lines, "proj-1", "  ")).toEqual({
    project_id: "proj-1",
    admin_notes: null,
    lines: [
      { line_kind: "UNIT", product_id: "prod-laptop", unit_serial: "CN-A1" },
      { line_kind: "PART", product_id: "prod-cable", requested_qty: 5 },
    ],
  })
})
