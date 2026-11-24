import io
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # no GUI backend needed on a server
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    HRFlowable,
)


# ---------------------------------------------------------------------------
# Visual constants — change these once, they apply to every report generated
# ---------------------------------------------------------------------------
PASS_COLOR = "#1E8449"   # green
FAIL_COLOR = "#C0392B"   # red
BRAND_COLOR = "#1A5276"  # header/accent blue
LIGHT_GREY = "#F2F3F4"


class ComplianceReportGenerator:
    """Builds one PDF per scan result. Stateless — safe to reuse across requests."""

    def __init__(self, output_dir="generated_reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.styles = self._build_styles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate(self, scan_result: dict, output_path: str = None) -> str:
        """
        Build the PDF for a single scan and return the path to the saved file.

        scan_result keys expected (see EXAMPLE_SCAN_RESULT below):
            product_name, scan_id, timestamp, overall_status,
            compliance_score, rules (list of dicts), extracted_fields (dict)
        """
        if output_path is None:
            safe_id = str(scan_result.get("scan_id", "scan")).replace(" ", "_")
            output_path = os.path.join(self.output_dir, f"compliance_report_{safe_id}.pdf")

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            title=f"Compliance Report - {scan_result.get('product_name', 'Unknown Product')}",
        )

        story = []
        story += self._build_header(scan_result)
        story += self._build_summary_block(scan_result)
        story += self._build_charts(scan_result)
        story += self._build_rules_table(scan_result)
        story += self._build_extracted_fields_table(scan_result)
        story += self._build_footer_note()

        doc.build(story)
        return output_path

    def generate_batch_summary(self, scan_results: list, output_path: str = None) -> str:
        """
        Optional: one consolidated PDF summarising many scans (e.g. an entire
        day's batch run). Useful for a judge who wants the "big picture" view
        rather than one report per product.
        """
        if output_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.output_dir, f"batch_summary_{stamp}.pdf")

        doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=18 * mm,
                                 bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm)
        story = []
        story.append(Paragraph("Packaged Label Compliance — Batch Summary", self.styles["TitleBrand"]))
        story.append(Paragraph(datetime.now().strftime("Generated on %d %b %Y, %H:%M"), self.styles["Meta"]))
        story.append(Spacer(1, 10))

        total = len(scan_results)
        passed = sum(1 for r in scan_results if r.get("overall_status") == "PASS")
        failed = total - passed

        rows = [["Scan ID", "Product", "Score (%)", "Verdict"]]
        for r in scan_results:
            rows.append([
                str(r.get("scan_id", "-")),
                str(r.get("product_name", "-")),
                f"{r.get('compliance_score', 0):.1f}",
                r.get("overall_status", "-"),
            ])

        table = Table(rows, colWidths=[70, 210, 90, 90])
        table.setStyle(self._standard_table_style(header_color=BRAND_COLOR))
        # Colour the verdict cells red/green per row
        for i, r in enumerate(scan_results, start=1):
            colour = colors.HexColor(PASS_COLOR) if r.get("overall_status") == "PASS" else colors.HexColor(FAIL_COLOR)
            table.setStyle(TableStyle([("TEXTCOLOR", (3, i), (3, i), colour), ("FONTNAME", (3, i), (3, i), "Helvetica-Bold")]))

        story.append(Paragraph(f"Total scanned: {total}   |   Passed: {passed}   |   Failed: {failed}", self.styles["Meta"]))
        story.append(Spacer(1, 8))
        story.append(table)

        doc.build(story)
        return output_path

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _build_styles(self):
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="TitleBrand", fontSize=19, leading=23,
                                   textColor=colors.HexColor(BRAND_COLOR), fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="Meta", fontSize=9.5, leading=13, textColor=colors.grey))
        styles.add(ParagraphStyle(name="SectionHeading", fontSize=13, leading=16, spaceBefore=14, spaceAfter=6,
                                   textColor=colors.HexColor(BRAND_COLOR), fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="VerdictPass", fontSize=15, leading=18, alignment=TA_CENTER,
                                   textColor=colors.HexColor(PASS_COLOR), fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="VerdictFail", fontSize=15, leading=18, alignment=TA_CENTER,
                                   textColor=colors.HexColor(FAIL_COLOR), fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="Body", fontSize=10, leading=14))
        return styles

    def _build_header(self, r):
        story = [
            Paragraph("Legal Metrology Label Compliance Report", self.styles["TitleBrand"]),
            Paragraph("Smart India Hackathon 2026 — Problem Statement SIH26034", self.styles["Meta"]),
            Spacer(1, 6),
            HRFlowable(width="100%", thickness=1, color=colors.HexColor(BRAND_COLOR)),
            Spacer(1, 10),
        ]
        return story

    def _build_summary_block(self, r):
        timestamp = r.get("timestamp", datetime.now())
        if isinstance(timestamp, datetime):
            timestamp = timestamp.strftime("%d %b %Y, %H:%M:%S")

        status = r.get("overall_status", "UNKNOWN")
        verdict_style = "VerdictPass" if status == "PASS" else "VerdictFail"

        info_rows = [
            ["Product Name", r.get("product_name", "-")],
            ["Scan ID", str(r.get("scan_id", "-"))],
            ["Timestamp", timestamp],
            ["Compliance Score", f"{r.get('compliance_score', 0):.1f}%"],
        ]
        info_table = Table(info_rows, colWidths=[130, 300])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(BRAND_COLOR)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(LIGHT_GREY)),
        ]))

        verdict_table = Table([[Paragraph(f"VERDICT<br/><br/>{status}", self.styles[verdict_style])]],
                               colWidths=[140], rowHeights=[70])
        verdict_border = colors.HexColor(PASS_COLOR) if status == "PASS" else colors.HexColor(FAIL_COLOR)
        verdict_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.2, verdict_border),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))

        wrapper = Table([[info_table, verdict_table]], colWidths=[350, 150])
        wrapper.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

        return [wrapper, Spacer(1, 12)]

    def _build_charts(self, r):
        rules = r.get("rules", [])
        passed = sum(1 for x in rules if x.get("status") == "PASS")
        failed = len(rules) - passed

        story = [Paragraph("Result Breakdown", self.styles["SectionHeading"])]

        donut_buf = self._make_donut_chart(passed, failed)
        bar_buf = self._make_rule_bar_chart(rules)

        donut_img = Image(donut_buf, width=190, height=190)
        bar_img = Image(bar_buf, width=280, height=190)

        chart_row = Table([[donut_img, bar_img]], colWidths=[200, 300])
        chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(chart_row)
        story.append(Spacer(1, 8))
        return story

    def _make_donut_chart(self, passed, failed):
        fig, ax = plt.subplots(figsize=(3, 3), dpi=150)
        values = [passed, failed] if (passed + failed) > 0 else [1]
        chart_colors = [PASS_COLOR, FAIL_COLOR] if (passed + failed) > 0 else ["#BDC3C7"]
        labels = [f"Pass ({passed})", f"Fail ({failed})"] if (passed + failed) > 0 else ["No data"]

        wedges, _ = ax.pie(values, colors=chart_colors, startangle=90,
                            wedgeprops=dict(width=0.42, edgecolor="white"))
        ax.legend(wedges, labels, loc="center", fontsize=8, frameon=False)
        ax.set_title("Rules: Pass vs Fail", fontsize=10)
        ax.axis("equal")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        buf.seek(0)
        return buf

    def _make_rule_bar_chart(self, rules):
        fig, ax = plt.subplots(figsize=(4.5, 3), dpi=150)
        if not rules:
            ax.text(0.5, 0.5, "No rule data", ha="center", va="center")
            ax.axis("off")
        else:
            labels = [x.get("field", f"Rule {i+1}") for i, x in enumerate(rules)]
            statuses = [1 if x.get("status") == "PASS" else 0 for x in rules]
            bar_colors = [PASS_COLOR if s == 1 else FAIL_COLOR for s in statuses]

            ax.barh(labels, [1] * len(labels), color=bar_colors)
            ax.set_xlim(0, 1)
            ax.set_xticks([])
            ax.set_title("Rule-wise Status", fontsize=10)
            ax.invert_yaxis()
            ax.tick_params(axis="y", labelsize=7.5)
            for spine in ["top", "right", "bottom"]:
                ax.spines[spine].set_visible(False)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        buf.seek(0)
        return buf

    def _build_rules_table(self, r):
        rules = r.get("rules", [])
        story = [Paragraph("Legal Metrology Declaration Checks", self.styles["SectionHeading"])]

        header = ["#", "Required Field", "Detected Text", "Status", "Remarks"]
        rows = [header]
        for i, rule in enumerate(rules, start=1):
            rows.append([
                str(i),
                Paragraph(str(rule.get("field", "-")), self.styles["Body"]),
                Paragraph(str(rule.get("detected_text", "Not found"))[:120], self.styles["Body"]),
                rule.get("status", "-"),
                Paragraph(str(rule.get("remarks", "-"))[:150], self.styles["Body"]),
            ])

        table = Table(rows, colWidths=[18, 100, 145, 45, 130], repeatRows=1)
        table.setStyle(self._standard_table_style(header_color=BRAND_COLOR))
        for i, rule in enumerate(rules, start=1):
            colour = colors.HexColor(PASS_COLOR) if rule.get("status") == "PASS" else colors.HexColor(FAIL_COLOR)
            table.setStyle(TableStyle([
                ("TEXTCOLOR", (3, i), (3, i), colour),
                ("FONTNAME", (3, i), (3, i), "Helvetica-Bold"),
                ("ALIGN", (3, i), (3, i), "CENTER"),
            ]))

        story.append(table)
        story.append(Spacer(1, 10))
        return story

    def _build_extracted_fields_table(self, r):
        fields = r.get("extracted_fields", {})
        if not fields:
            return []

        story = [Paragraph("Raw OCR-Extracted Fields", self.styles["SectionHeading"])]
        rows = [["Field", "Extracted Value"]]
        for k, v in fields.items():
            rows.append([str(k), Paragraph(str(v)[:200], self.styles["Body"])])

        table = Table(rows, colWidths=[150, 288], repeatRows=1)
        table.setStyle(self._standard_table_style(header_color="#5D6D7E"))
        story.append(table)
        story.append(Spacer(1, 10))
        return story

    def _build_footer_note(self):
        return [
            Spacer(1, 6),
            HRFlowable(width="100%", thickness=0.6, color=colors.HexColor(LIGHT_GREY)),
            Spacer(1, 4),
            Paragraph(
                "Auto-generated by the Packaged Label Compliance Scanner backend "
                "(SIH26034). This report reflects automated OCR extraction and "
                "rule-based verification against the Legal Metrology (Packaged "
                "Commodities) Rules, 2011 and is intended to assist, not replace, "
                "manual verification.",
                self.styles["Meta"],
            ),
        ]

    def _standard_table_style(self, header_color):
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_GREY)]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5D8DC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ])


# ---------------------------------------------------------------------------
# Reference schema — copy/adapt this shape from wherever your OCR + rules
# engine currently produces its output.
# ---------------------------------------------------------------------------
EXAMPLE_SCAN_RESULT = {
    "product_name": "Sunrise Refined Sunflower Oil - 1L Pouch",
    "scan_id": "SCAN-0091",
    "timestamp": datetime.now(),
    "overall_status": "FAIL",          # "PASS" or "FAIL", computed by your rules engine
    "compliance_score": 71.4,          # e.g. passed_rules / total_rules * 100
    "rules": [
        {"field": "Manufacturer Name & Address", "status": "PASS",
         "detected_text": "Sunrise Agro Foods Pvt Ltd, Hubballi, Karnataka",
         "remarks": "Full address present"},
        {"field": "Net Quantity", "status": "PASS",
         "detected_text": "1000 ml", "remarks": "Matches declared standard unit"},
        {"field": "MRP (incl. of all taxes)", "status": "FAIL",
         "detected_text": "Not found", "remarks": "MRP text not detected or illegible"},
        {"field": "Consumer Care Details", "status": "PASS",
         "detected_text": "1800-123-4567, care@sunriseagro.in", "remarks": "Present"},
        {"field": "Date of Manufacture/Import", "status": "PASS",
         "detected_text": "MFG: 03/2026", "remarks": "Present, format acceptable"},
        {"field": "Country of Origin", "status": "FAIL",
         "detected_text": "Not found", "remarks": "Mandatory since import-labelling amendment"},
        {"field": "Common/Generic Name of Commodity", "status": "PASS",
         "detected_text": "Refined Sunflower Oil", "remarks": "Present"},
    ],
    "extracted_fields": {
        "Raw OCR Block 1": "SUNRISE Refined Sunflower Oil Net Qty 1000ml MFG 03/2026",
        "Raw OCR Block 2": "Sunrise Agro Foods Pvt Ltd Hubballi Karnataka Care 1800-123-4567",
    },
}


if __name__ == "__main__":
    # Quick self-test: run this file directly to confirm the module works
    # end-to-end on your machine before wiring it into the backend.
    generator = ComplianceReportGenerator(output_dir="generated_reports")
    path = generator.generate(EXAMPLE_SCAN_RESULT)
    print(f"Sample report generated at: {path}")