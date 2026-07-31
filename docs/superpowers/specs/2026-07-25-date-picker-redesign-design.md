# Date picker redesign — design

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Driver:** Native `<input type="date">` / `type="month"` controls render OS chrome that
ignores the app's theme, so every date field looks foreign to the rest of the system.

---

## Problem

Eight date controls across five files are native browser inputs. Their calendar glyph and
dropdown are drawn by the browser, cannot be themed, and differ between Chrome, Safari and
Firefox. In dark mode the glyph is frequently unreadable. Nothing about them matches the
shadcn/Tailwind design system used everywhere else in the app.

### Full inventory

| Surface | File | Control |
|---|---|---|
| Audit log — From / To filter | `frontend/src/routes/_layout/audit.tsx:192,205` | `<input type="date">` ×2 |
| Receive — Serialized tab | `frontend/src/routes/_layout/receive.tsx:280` | `<input type="date">` |
| Receive — Quantity tab | `frontend/src/routes/_layout/receive.tsx:607` | `<input type="date">` |
| Projects — edit dialog Start / End | `frontend/src/components/projects/ProjectEditDialog.tsx:148,157` | `<input type="date">` ×2 |
| Channel margin report — Month | `frontend/src/routes/_layout/channel-margin.tsx:145` | `<input type="month">` |
| Override exceptions report — Month | `frontend/src/routes/_layout/override-exceptions.tsx:99` | `<input type="month">` |

The two month pickers and the Projects dialog were not previously known to be date
surfaces; they are in scope precisely so the app ends up consistent.

---

## Decisions

| Question | Decision |
|---|---|
| Scope | All 8 controls, one shared component pair |
| Interaction | Click-to-open only. **No typed text entry.** |
| Trigger | The whole field is a button, not an input |
| Mobile | Custom picker everywhere — no native fallback below a breakpoint |
| Display format | `25 Jul 2026` (dates), `Jul 2026` (months); wire format stays ISO |
| Implementation | Hand-rolled. No new dependencies. |
| Backend | None. No migration, no SDK regeneration. |

### Why no typed entry

Typing requires parsing free-form text, which forces a two-digit-year rule (`26` → 2026 or
1926?) and a dd/mm vs mm/dd assumption. Both are silent-wrong-date hazards on a screen that
backdates inventory receipts. Removing typed entry makes invalid input impossible by
construction and deletes the `aria-invalid` / revert-on-blur machinery entirely.

The cost — reaching a distant date is click-only — is small here. Both Receive tabs already
default to `todayISO()` (`receive.tsx:126,469`), so the picker only opens when backdating,
and the caption button drops to a 12-month grid whose `‹ ›` step years, putting any date
within a few years at ≤4 clicks.

### Why hand-rolled rather than `react-day-picker`

The goal is exact design-system match, and a **month** picker is required — which no
calendar library provides. With a library the month grid would be hand-rolled anyway,
leaving two differently-built calendars that must be kept visually in sync. Styling
`react-day-picker` to a token set is roughly as much code as the grid itself. Requirements
are narrow: single date, `min`/`max`, no ranges, no multi-month.

The accepted risk is that keyboard and ARIA correctness is hand-written. It is mitigated by
following the WAI-ARIA APG date-picker-dialog pattern exactly, delegating focus
containment / Escape / outside-click to the already-installed Radix Popover, and covering
keyboard navigation with an E2E test.

---

## Architecture

| File | Purpose | Kind |
|---|---|---|
| `frontend/src/lib/date-field.ts` | Date math and formatting | Pure, vitest-tested |
| `frontend/src/lib/date-field.test.ts` | Unit tests for the above | Test |
| `frontend/src/components/ui/calendar.tsx` | `CalendarGrid` (day view) + `MonthGrid` (12-month view) | Presentational |
| `frontend/src/components/ui/date-picker.tsx` | `DatePicker` + `MonthPicker` | Composed |

`calendar.tsx` knows nothing about popovers or triggers; `date-picker.tsx` owns open/close
state. The grid can be restyled without touching trigger behaviour and vice versa. Each
file stays under the 200-line threshold called out in `.agents/skills/frontend-ui/SKILL.md`.

### `date-field.ts` surface

```ts
formatDisplay(iso: string): string                    // "2026-07-25" → "25 Jul 2026"
formatMonthDisplay(ym: string): string                // "2026-07"    → "Jul 2026"
buildMonthGrid(ym, { min, max, today }): DayCell[]    // 42 cells, Monday-first
buildYearGrid(year, { min, max }): MonthCell[]        // 12 cells
addMonths(ym: string, n: number): string
todayISO(): string
```

`todayISO()` currently lives in `lib/receive-form.ts:37`. A generic date module must not
depend on a receive-form module, so the function moves to `date-field.ts` and
`receive-form.ts` re-exports it. Existing imports in `receive.tsx` and the assertions in
`receive-form.test.ts` continue to work unchanged.

### Component API

```tsx
<DatePicker
  id={...}
  value={iso}                      // "" when unset
  onChange={(iso: string) => ...}  // emits the ISO string, not an event
  min={...} max={...}              // ISO bounds; out-of-range days render disabled
  disabled required
  className="h-11"
/>

<MonthPicker id value={"2026-07"} onChange={(ym: string) => ...} min max />
```

Props mirror the current `<Input type="date">` so call sites change minimally. The one
difference is `onChange` handing over the ISO string rather than `e.target.value`.

---

## Visual design

All colours are semantic tokens already defined in `frontend/src/index.css` — `--primary`,
`--accent`, `--muted-foreground`, `--ring`, `--popover`, and the `--radius` scale
(`0.625rem`). No raw hex, no invented spacing.

### Trigger

```
┌──────────────────────────────┐
│ 25 Jul 2026               📅 │  ← the entire field is the button
└──────────────────────────────┘
```

A `<button>` carrying `aria-haspopup="dialog"` and `aria-expanded`. When unset it shows the
placeholder in `text-muted-foreground`.

To guarantee the trigger is visually indistinguishable from every other field, the class
string is exported from `components/ui/input.tsx` and consumed by both `Input` and the
trigger. This is a three-line change to `input.tsx` with no behaviour change. Duplicating
the string instead would drift the first time either is edited.

### Popover

```
┌────────────────────────────────┐
│  ‹        July 2026         ›  │  caption is a button → year view
│  Mo Tu We Th Fr Sa Su          │  text-xs text-muted-foreground
│                                │
│         1  2  3  4  5          │
│   6  7  8  9 10 11 12          │
│  13 14 15 16 17 18 19          │
│  20 21 22 23 24 ●25● 26        │
│  27 28 29 30 31                │
│                                │
│  [ Today ]            [ Clear ]│  Clear only when the field is optional
└────────────────────────────────┘
```

| State | Styling |
|---|---|
| Selected | `bg-primary text-primary-foreground` |
| Today (unselected) | `ring-1 ring-ring` outline |
| Hover | `bg-accent text-accent-foreground` |
| Outside current month | `text-muted-foreground/50` |
| Disabled (outside `min`/`max`) | `text-muted-foreground/40`, not focusable |
| Focus | `focus-visible:ring-[3px] ring-ring/50` — copied from `input.tsx` |

Cells are `size-11` on touch and `sm:size-9` on desktop, meeting WCAG target-size guidance
where it matters. Cells use `rounded-md`, the popover `rounded-lg`.

Clicking the caption swaps the day grid for the 12-month year view — the same `MonthGrid`
that backs `MonthPicker`, which is what makes both report pages match the date pickers for
free. `MonthPicker` opens straight into that view, with `‹ 2026 ›` stepping years in place
of the month caption.

When the value is unset, the popover opens on the current month (year, for `MonthPicker`),
clamped into `min`/`max` if today falls outside them.

Clear appears only in the popover footer for optional fields. There is no second clear
affordance on the trigger.

---

## Keyboard (WAI-ARIA APG, date-picker-dialog)

| Context | Key | Action |
|---|---|---|
| Trigger | `Enter` `Space` `↓` `Alt+↓` | Open popover, focus the selected day (or today, clamped into range) |
| Trigger / grid | `Esc` | Close popover, return focus to the trigger |
| Grid | `←` `→` | ±1 day, crossing month boundaries and auto-paging the view |
| Grid | `↑` `↓` | ±7 days |
| Grid | `Home` `End` | First / last day of the week |
| Grid | `PgUp` `PgDn` | ±1 month (`Shift` → ±1 year) |
| Grid | `Enter` `Space` | Select, close, return focus to the trigger |

Arrow navigation **skips disabled dates** rather than landing on them. This keeps movement
predictable and means a backdated Receive can never focus a future day.

Exactly one day button carries `tabIndex={0}` (roving tabindex). The grid uses
`role="grid"` / `role="row"` / `role="gridcell"` with `aria-selected` and `aria-disabled`.
The caption is `aria-live="polite"` so month changes are announced.

Focus containment, Escape handling and outside-click dismissal come from Radix Popover and
are not reimplemented.

---

## Timezone rule

All arithmetic operates on local `YYYY-MM-DD` strings and `new Date(y, m, d)`.
`toISOString()` is never used. This is the rule `receive-form.ts:34` already documents, and
it is what stops a receive keyed in at 11pm from recording tomorrow's date.

---

## Call-site migration

| Call site | Change |
|---|---|
| `audit.tsx` From / To | `DatePicker`, optional (Clear shown); `onChange` still calls `resetPage()` |
| `receive.tsx` serialized | `DatePicker required max={todayISO()} className="h-11"`, no Clear |
| `receive.tsx` quantity | Same as serialized |
| `ProjectEditDialog.tsx` ×2 | `DatePicker`, optional |
| `channel-margin.tsx` | `MonthPicker` |
| `override-exceptions.tsx` | `MonthPicker` |

Existing validation is untouched. `isValidReceivedDate()` still guards the Receive submit
and `isValidMonth()` still guards the reports. The picker makes bad input harder to
produce; it does not replace the server-side or submit-time guard.

### Known risk

`ProjectEditDialog` nests a Popover inside a Radix Dialog. Focus return and stacking are
the usual failure mode for that combination. Radix supports it, but it gets an explicit E2E
test rather than an assumption.

---

## Testing

### vitest — `date-field.test.ts`

Pure logic, no stack or DB required. Run with `bun run test:unit`.

- `buildMonthGrid` returns 42 Monday-first cells with correct leading and trailing days
- Grid correctness across a leap February (Feb 2028) and a DST-transition month
- `min`/`max` mark the right cells disabled
- `addMonths` rolls over year boundaries in both directions
- `formatDisplay` and `formatMonthDisplay` output
- `todayISO` uses local calendar date, not UTC

### Playwright

`frontend/tests/receive-date.spec.ts` **requires rewriting**: it currently selects
`input[type="date"]` and calls `.fill()` at lines 29, 36 and 62, all of which break with
this change. No spec may use `.fill()` on a date field afterwards.

New and rewritten coverage:

- Receive: open the picker, select a backdated day from the grid, submit
- Receive: reach and select a date using only the keyboard
- Receive: a future date cannot be selected on either tab
- Audit: set From and To from the grid, confirm results filter and the page resets
- Reports: pick a month via `MonthPicker` on one report page
- Projects: the picker opens, selects, and returns focus correctly **inside the dialog**

All E2E runs use `E2E_SKIP_DB_RESET=1`.

---

## Out of scope

- Backend changes, Alembic migrations, SDK regeneration — this is frontend-only
- Date **range** selection, multi-month views, presets ("Last 7 days")
- Wiring the audit From/To bounds together (From's `max` = To, To's `min` = From). The
  `min`/`max` props make it nearly free, but it is an unrequested behaviour change and is
  deliberately left off
- Localisation of month and weekday names beyond English
- The uncommitted work in `EditProductDialog.tsx`, `products.tsx` and `sync-review.tsx`,
  which is unrelated to this change
