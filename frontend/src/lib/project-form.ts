// ---------------------------------------------------------------------------
// Validation rules shared by the project CREATE and EDIT forms (FR-003).
//
// Both dialogs must agree on what a valid project is — otherwise a project the
// create form accepts is rejected by the edit form (or worse, the reverse).
// Keeping the rules here rather than duplicating them in project-create.ts and
// project-edit.ts is what stops the two drifting apart.
// ---------------------------------------------------------------------------

/** Optional budget: blank passes; otherwise a finite, non-negative number. */
export function isValidBudget(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return true // optional
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

/**
 * Optional dates: valid unless BOTH are set and the end falls before the start.
 * Either date alone is fine (an open-ended project is legitimate), and an equal
 * pair is fine (a one-day project).
 *
 * Both values come from <input type="date">, so they are ISO `yyyy-mm-dd` and
 * compare correctly as strings — no Date parsing, no timezone shift.
 */
export function isValidDateRange(startDate: string, endDate: string): boolean {
  const start = startDate.trim()
  const end = endDate.trim()
  if (start === "" || end === "") return true
  return end >= start
}
