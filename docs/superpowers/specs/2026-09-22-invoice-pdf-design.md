# Sale invoice PDF — black & gold redesign + staff download (2026-09-22)

## Problem
`GET /sales/{id}/receipt.pdf` exists but no screen calls it, so staff cannot
hand a customer an invoice. The PDF itself is a plain grey table with a
centred logo. The owner wants the paper form's look (gold header band, gold
boxes for Sold To / Invoice No, gold-and-black wave foot) under **CastraNova**
branding — not the Aquamarine Moon letterhead the sample was drawn on.

## Decisions
| Question | Answer |
|---|---|
| Approach | Keep reportlab; redraw the page furniture and table styling in place (option 1). No new dependency. |
| Branding | CastraNova logo (`assets/castranova-logo-header.png`), title "INVOICE". No address/bank lines yet — add them (with the owner's details) as a follow-up. |
| Footer art | The gold-and-black wave cropped from the sample's foot (`assets/invoice-footer-wave.jpg`, 1130×192). Aquamarine Moon's logo/name/address are never used. |
| Invoice number | The sale's short id (first 8 hex, upper-case), as today. Sequential numbering is a separate feature (needs a column + migration). |
| Currency | THB, as everywhere else. |
| Tax / discount row | Dropped — sales carry no tax or discount (overrides are already in the line price). Sub Total and Total Amount only. |
| Download | "Download invoice" on the sale-complete card (Sell → Sale) and on each SALE row of the customer page's Transactions table. Opens the PDF in a new tab via `openAuthedPdf` (the app's sanctioned authed-PDF path, used by labels). |

## Page (A4 portrait)
- Top: CastraNova logo left (52 mm wide), a thin gold rule under the header
  band; "INVOICE" in a gold pill centred under the rule.
- Two rounded gold boxes (fill `#C9A200`-ish gold, black text): left **Sold To**
  with the customer name; right **Invoice No** and **Date** (+ **Sold by**).
- Line table: header row gold fill / black bold text, columns No · Description
  · Qty · Price per Unit · Amount; thin gold grid; body black on white.
- Sub Total row (white, bold label right-aligned) and **Total Amount** row
  (gold fill, bold) — the total spans the label cells like the sample.
- Foot: the wave image full-width at the bottom edge; the story's bottom margin
  clears it. Multi-page sales repeat the header/footer on every page.
- Colours: gold `#C9A227`, dark gold rule `#8A6D1F`, black `#111111`.

## Not changed
- `render_sale_receipt` keeps its exact signature (the cost-leak guard test
  pins it) and `get_sale_receipt_data` is untouched — the invoice carries no
  cost. Staff and admin both download (route unchanged, `get_current_user`).

## Tests
- Existing `tests/services/test_receipt_pdf.py` stays green (signature, A4,
  logo embedded, empty lines).
- New: wave image embedded; multi-line sale still one page for ≤ 20 lines.
- Frontend E2E: on the customer page a SALE row's "Download invoice" opens a
  tab and the authed fetch of `/receipt.pdf` returns 200 `application/pdf`.

## Known behaviour / follow-ups
- The invoice is a historical document: a reprint after a partial sale return
  still shows the original Sub Total and Total Amount. The return is its own
  record; a credit note is a separate feature.
- Dates print in shop time (`SHOP_TZ = Asia/Bangkok`), matching what screens
  show in the browser; the DB stores UTC.
- The saved-file name of the PDF is the blob id (shared `openAuthedPdf`
  behaviour with label printing). A `Content-Disposition` filename would need a
  different download path.
- The logo PNG is ~490 KB and dominates the ~770 KB download; pre-scaling the
  asset to ~700 px wide would cut it by two thirds.
