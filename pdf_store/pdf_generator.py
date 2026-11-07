from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


OUTPUT_PATH = Path(__file__).with_name("Northstar_Components_Income_Statement.pdf")


def generate_pdf(output_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    elements = []
    elements.append(Paragraph("<b>Northstar Components LLC</b>", styles["Title"]))
    elements.append(
        Paragraph(
            "<b>Income Statement | Fiscal Year Ended December 31, 2025</b>",
            styles["Heading3"],
        )
    )
    elements.append(Paragraph("<b>Loan Number:</b> 4829104721", styles["Normal"]))
    elements.append(Spacer(1, 14))

    table_data = [
        ["Line Item", "FY 2025", "FY 2024"],
        ["Revenue", "$1,250,000", "$1,100,000"],
        ["Cost of goods sold", "$720,000", "$640,000"],
        ["Gross profit", "$530,000", "$460,000"],
        ["Operating expenses", "$310,000", "$285,000"],
        ["Operating income", "$220,000", "$175,000"],
        ["Interest expense", "$35,000", "$32,000"],
        ["Income before tax", "$185,000", "$143,000"],
        ["Income tax expense", "$46,000", "$35,750"],
        ["Net income", "$139,000", "$107,250"],
    ]

    table = Table(table_data, colWidths=[240, 130, 130])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f3f4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dcdcdc")),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )

    elements.append(table)
    elements.append(Spacer(1, 14))

    notes = (
        "<b>Basis and Notes:</b><br/>"
        "• Accrual basis. Fiscal year ended December 31, 2025.<br/>"
        "• Revenue reflects product sales and service revenue.<br/>"
        "• Depreciation expense included in operating expenses: $42,000.<br/>"
        "• <i>SYNTHETIC TEST DATA - NOT A REAL BORROWER OR FINANCIAL INSTITUTION.</i>"
    )
    elements.append(Paragraph(notes, styles["Normal"]))

    doc.build(elements)


if __name__ == "__main__":
    generate_pdf(OUTPUT_PATH)
    print(f"Generated PDF: {OUTPUT_PATH}")