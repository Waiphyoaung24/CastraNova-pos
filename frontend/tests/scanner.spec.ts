import { expect, test } from "@playwright/test"
import {
  feedScanKey,
  initialScanState,
  type ScanBufferState,
} from "../src/hooks/useScanner"

// Pure-logic coverage of the keyboard-wedge buffer (spec §3 / §6.11). The full
// in-browser ScanInput E2E (focus input, dispatch keystrokes) runs in the Part 5
// E2E pass once the scan-bearing receive/sale screens exist.

const OPTS = { minLength: 3, interKeyTimeoutMs: 50 }

function feedSequence(keys: Array<[string, number]>): string[] {
  let state: ScanBufferState = initialScanState
  const emits: string[] = []
  for (const [key, now] of keys) {
    const result = feedScanKey(state, key, now, OPTS)
    state = result.state
    if (result.emit !== undefined) emits.push(result.emit)
  }
  return emits
}

test("a fast wedge burst terminated by CR commits the code exactly once", () => {
  const code = "CN-AB12"
  const keys: Array<[string, number]> = code
    .split("")
    .map((c, i) => [c, i * 10])
  keys.push(["Enter", code.length * 10])
  expect(feedSequence(keys)).toEqual([code])
})

test("keystrokes without a CR terminator never commit", () => {
  const keys: Array<[string, number]> = "CN-AB12"
    .split("")
    .map((c, i) => [c, i * 10])
  expect(feedSequence(keys)).toEqual([])
})

test("slow (human) keystrokes reset the buffer so CR commits nothing", () => {
  const keys: Array<[string, number]> = [
    ["A", 0],
    ["B", 100],
    ["C", 200],
    ["Enter", 300],
  ]
  expect(feedSequence(keys)).toEqual([])
})

test("modifier keys are ignored, not buffered", () => {
  const keys: Array<[string, number]> = [
    ["Shift", 0],
    ["C", 5],
    ["N", 10],
    ["X", 15],
    ["Enter", 20],
  ]
  expect(feedSequence(keys)).toEqual(["CNX"])
})
