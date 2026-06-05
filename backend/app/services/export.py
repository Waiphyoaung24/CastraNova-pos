"""Generic tabular export to PDF (reportlab) and Excel (openpyxl) — FR-017.

Reports/lists flatten to (title, headers, rows of strings); these two renderers
turn that into downloadable bytes. Kept content-agnostic so every admin report
reuses the same path.
"""

import io

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Font  # type: ignore[import-untyped]
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4, landscape  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PDF_MEDIA_TYPE = "application/pdf"
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def render_table_pdf(
    *, title: str, headers: list[str], rows: list[list[str]]
) -> bytes:
    """Render a landscape-A4 PDF with a title and a header+rows table."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    data = [headers] + (rows or [["(no rows)"] + [""] * (len(headers) - 1)])
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    doc.build(
        [Paragraph(title, styles["Title"]), Spacer(1, 12), table]
    )
    return buf.getvalue()


def render_table_xlsx(
    *, title: str, headers: list[str], rows: list[list[str]]
) -> bytes:
    """Render an .xlsx workbook with a bold header row and the data rows."""
    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel sheet-name limit
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    wb.save(buf)
    return buf.getvalue()
