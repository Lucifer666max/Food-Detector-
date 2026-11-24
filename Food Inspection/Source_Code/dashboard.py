"""
SIH26034 — Legal Metrology (Packaged Commodities) Rules, 2011 Compliance Checker
==================================================================================
Scans product label images and checks them against the mandatory declarations
required under Rule 6 of the Legal Metrology (Packaged Commodities) Rules, 2011
(Ministry of Consumer Affairs, Food & Public Distribution, Govt. of India).

Backend notes / changes made vs. the original scraper.py prototype:
  1. Migrated google-generativeai (deprecated Aug-2025) -> google-genai, the
     current unified SDK (`from google import genai`).
  2. Model bumped to gemini-3.5-flash (current GA flash model). gemini-2.5-flash
     is offered as a fallback in the sidebar; gemini-1.5-flash is retired.
  3. Removed the hard-coded Windows Tesseract path — OCR is now optional and
     best-effort. The primary read is done by sending the image itself to
     Gemini's multimodal vision, which is far more robust than OCR-then-text
     for photographed labels (skew, glare, small print, multiple languages).
     OCR text, when available, is passed in only as *supporting* context.
  4. Structured output is enforced with a Pydantic response_schema instead of
     hoping the model returns clean JSON — this removes the raw-text fallback
     failure mode from the original script.
  5. Added an "imported product" toggle so Country of Origin is graded N/A
     (not a violation) for domestically made goods, per Rule 6(g)/10.
  6. Supports multiple photos (e.g. front + back of the same pack) analyzed
     together as one product, plus a running session history with CSV export.
"""

import io
import os
import re
import json
from datetime import datetime
from typing import List, Optional

import streamlit as st
import pandas as pd
from PIL import Image
from pydantic import BaseModel

from google import genai
from google.genai import types

# --- PDF report generator integration (from report_generator.py) ---
from report_generator import ComplianceReportGenerator

# Optional OCR - never required for the app to work.
try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False


@st.cache_resource
def get_pdf_generator() -> ComplianceReportGenerator:
    """One shared PDF generator instance for the whole app session."""
    return ComplianceReportGenerator(output_dir="generated_reports/pdf")


# --------------------------------------------------------------------------- #
# Unit / numeration cross-validation (ported from main.py's rule engine)
# Legal Metrology (National Standards) Rules 2011 & Numeration Rules 2011.
# --------------------------------------------------------------------------- #
def validate_unit_and_numeration(net_quantity_str: str) -> list:
    violations = []

    if not net_quantity_str or net_quantity_str.lower() in ["not found", "none", "n/a", ""]:
        return violations

    if re.search(r'\b(kgs|gms|ltrs|mls)\b', net_quantity_str, re.IGNORECASE):
        violations.append({
            "rule": "Unit Pluralization (National Standards Rules 2011, Third Schedule Rule 7(1)(b))",
            "issue": f"Unit symbol in '{net_quantity_str}' appears pluralized. Unit symbols must remain singular.",
        })

    if re.search(r'\bgm\b', net_quantity_str, re.IGNORECASE):
        violations.append({
            "rule": "Invalid Unit Symbol (National Standards Rules 2011, Second/Fourth Schedule)",
            "issue": f"Declared unit symbol 'gm' in '{net_quantity_str}' is non-standard. Legal symbol is 'g'.",
        })

    if re.search(r'\d+[a-zA-Z]+', net_quantity_str):
        violations.append({
            "rule": "Missing Symbol Space Separation (National Standards Rules 2011, Third Schedule Rule 7)",
            "issue": f"No space between numeric value and unit in '{net_quantity_str}'. Standard space is required.",
        })

    return violations


def apply_unit_cross_validation(report: "ComplianceReport") -> "ComplianceReport":
    """Runs the regex-based rule engine over the net_quantity finding and
    downgrades compliance/overall_status if it finds a formatting violation
    that the Gemini pass missed."""
    for f in report.findings:
        if f.rule_key == "net_quantity":
            violations = validate_unit_and_numeration(f.extracted_value)
            if violations:
                f.compliant = False
                report.overall_status = "NON_COMPLIANT"
                notes = " | ".join(v["issue"] for v in violations)
                f.remarks = (f.remarks + " " if f.remarks else "") + f"[Rule-engine] {notes}"
    return report


def build_pdf_schema(product_name: str, scan_id: str, timestamp: datetime,
                      report: "ComplianceReport") -> dict:
    """Converts a dashboard ComplianceReport into the dict shape that
    ComplianceReportGenerator.generate() expects."""
    findings = report.findings
    total = len(findings)
    compliant_count = sum(1 for f in findings if f.compliant)
    score = (compliant_count / total * 100) if total else 0

    rules = []
    for f in findings:
        rules.append({
            "field": f.rule,
            "status": "PASS" if f.compliant else "FAIL",
            "detected_text": f.extracted_value or "Not Found",
            "remarks": f.remarks if f.remarks else ("Compliant" if f.compliant else "Non-compliant"),
        })

    return {
        "product_name": product_name,
        "scan_id": scan_id,
        "timestamp": timestamp,
        "overall_status": "PASS" if report.overall_status == "COMPLIANT" else "FAIL",
        "compliance_score": score,
        "rules": rules,
        "extracted_fields": {
            "Gemini Summary": report.summary,
            "Confidence": report.confidence.title(),
        },
    }


# --------------------------------------------------------------------------- #
# Domain model: the 7 mandatory declarations under Rule 6, LMPC Rules 2011
# --------------------------------------------------------------------------- #
RULES = [
    ("manufacturer_address",
     "Name and complete address of the manufacturer / packer / importer"),
    ("common_name",
     "Common or generic name of the commodity (and count, if multi-piece pack)"),
    ("net_quantity",
     "Net quantity in standard (metric) units of weight, measure, or number"),
    ("mfg_date",
     "Month and year of manufacture / packing / import"),
    ("mrp",
     "Maximum Retail Price (MRP) inclusive of all taxes"),
    ("consumer_care",
     "Consumer/customer care name, address, and contact (phone/email)"),
    ("country_of_origin",
     "Country of origin (mandatory only for imported goods)"),
]


class Finding(BaseModel):
    rule_key: str
    rule: str
    detected: bool
    extracted_value: str
    compliant: bool
    remarks: str = ""


class ComplianceReport(BaseModel):
    overall_status: str  # COMPLIANT | NON_COMPLIANT | NEEDS_REVIEW
    confidence: str      # high | medium | low
    findings: List[Finding]
    summary: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def try_ocr(images: List[Image.Image]) -> Optional[str]:
    """Best-effort OCR pass. Returns None quietly if tesseract isn't installed
    or fails - the app never depends on this succeeding."""
    if not _TESSERACT_AVAILABLE:
        return None
    try:
        chunks = []
        for img in images:
            chunks.append(pytesseract.image_to_string(img))
        text = "\n".join(c.strip() for c in chunks if c.strip())
        return text or None
    except Exception:
        return None


def build_prompt(is_imported: bool, product_category: str, ocr_text: Optional[str]) -> str:
    coo_instruction = (
        "This product has been declared as IMPORTED, so Country of Origin is "
        "mandatory — mark it non-compliant if missing."
        if is_imported else
        "This product has been declared as DOMESTIC (made in India), so Country "
        "of Origin is not legally required here. Set detected=false, "
        "extracted_value='Not applicable (domestic product)', and compliant=true "
        "for that rule — do NOT count it against the product."
    )

    ocr_block = (
        f"\n\nOCR text extracted separately from the same image(s), for reference "
        f"only (it may be noisy or incomplete — always trust what you can read "
        f"in the image itself over this text):\n---\n{ocr_text}\n---"
        if ocr_text else
        "\n\n(No OCR text is available — rely entirely on the image(s).)"
    )

    rules_block = "\n".join(f"{i+1}. [{key}] {desc}" for i, (key, desc) in enumerate(RULES))

    return f"""You are an automated Legal Metrology (Packaged Commodities) Rules, 2011
compliance inspector for India, working for the Ministry of Consumer Affairs,
Food & Public Distribution. You are given one or more photographs of a single
product's label (e.g. front of pack and back of pack).

Product category (as declared by the user): {product_category}
{coo_instruction}

Carefully read every photograph provided and check for the presence and
correctness of these mandatory declarations required under Rule 6:

{rules_block}

For EACH of the 7 rules above, return a finding with:
- rule_key: the bracketed key shown above (e.g. "mrp")
- rule: a short human-readable label for the rule
- detected: whether this declaration appears anywhere on the label(s)
- extracted_value: the exact text/value you found, or "Not Found" (or the N/A
  wording specified above for country_of_origin on domestic goods)
- compliant: whether that specific declaration satisfies the rule (e.g. MRP
  must explicitly say it is inclusive of all taxes; net quantity must be in
  standard metric units; date must be month AND year)
- remarks: one short sentence noting anything ambiguous, illegible, or a
  reason for non-compliance. Empty string if nothing to note.

Then give:
- overall_status: "COMPLIANT" only if all 7 findings are compliant,
  "NON_COMPLIANT" if any mandatory declaration is missing or defective,
  "NEEDS_REVIEW" if image quality/glare/cropping makes you unable to confidently
  judge one or more declarations.
- confidence: "high", "medium", or "low" — how confident you are in this
  overall reading given image quality.
- summary: 1-3 sentences in plain English summarizing the violations (or
  confirming compliance).
{ocr_block}"""


def analyze_label(
    client: "genai.Client",
    model_name: str,
    images: List[Image.Image],
    is_imported: bool,
    product_category: str,
    ocr_text: Optional[str],
) -> ComplianceReport:
    prompt = build_prompt(is_imported, product_category, ocr_text)
    contents = list(images) + [prompt]

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ComplianceReport,
            temperature=0.1,
        ),
    )

    # response.parsed is a validated ComplianceReport when parsing succeeds.
    if getattr(response, "parsed", None) is not None:
        return response.parsed

    # Fallback: manual parse in case the SDK couldn't auto-parse for some reason.
    data = json.loads(response.text)
    return ComplianceReport(**data)


def status_badge(status: str) -> str:
    return {
        "COMPLIANT": "🟢 COMPLIANT",
        "NON_COMPLIANT": "🔴 NON-COMPLIANT",
        "NEEDS_REVIEW": "🟡 NEEDS REVIEW",
    }.get(status, f"⚪ {status}")


def report_to_dataframe(report: ComplianceReport) -> pd.DataFrame:
    return pd.DataFrame([{
        "Rule": f.rule,
        "Detected": "Yes" if f.detected else "No",
        "Extracted Value": f.extracted_value,
        "Compliant": "✅" if f.compliant else "❌",
        "Remarks": f.remarks,
    } for f in report.findings])


# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="SIH26034 — Legal Metrology Compliance Checker",
    page_icon="⚖️",
    layout="wide",
)

if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts: {product_name, category, report, timestamp}

with st.sidebar:
    st.header("⚙️ Settings")

    api_key = st.text_input(
        "Gemini API Key",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Get a key from Google AI Studio. Also picked up from the "
             "GEMINI_API_KEY environment variable or st.secrets.",
    )
    if not api_key:
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            pass

    model_name = st.selectbox(
        "Gemini model",
        options=["gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"],
        index=0,
        help="gemini-3.5-flash is the current GA flash model (recommended). "
             "gemini-2.5-flash is offered as a fallback.",
    )

    use_ocr = st.checkbox(
        "Run local OCR as extra supporting context",
        value=_TESSERACT_AVAILABLE,
        disabled=not _TESSERACT_AVAILABLE,
        help="Optional. Requires the Tesseract binary installed on this machine. "
             + ("Tesseract was detected." if _TESSERACT_AVAILABLE
                else "Tesseract was NOT found — this app works fine without it "
                     "since Gemini reads the image directly."),
    )

    st.divider()
    st.caption(
        "SIH26034 · Ministry of Consumer Affairs, Food & Public Distribution\n\n"
        "Checks against Rule 6 of the Legal Metrology (Packaged Commodities) "
        "Rules, 2011."
    )

st.title("⚖️ Legal Metrology Compliance Checker")
st.caption(
    "Upload photo(s) of a single product's label (front / back / any panel with "
    "printed declarations) to check compliance with the Legal Metrology "
    "(Packaged Commodities) Rules, 2011."
)

col1, col2 = st.columns([2, 1])
with col1:
    product_name = st.text_input("Product name (for your records)", placeholder="e.g. XYZ Face Wash 100ml")
with col2:
    product_category = st.selectbox(
        "Category", ["General / Other", "Food & Beverage", "Cosmetics & Personal Care",
                      "Electronics", "Pharma / OTC", "Household / FMCG"],
    )

is_imported = st.checkbox("This is an imported product (Country of Origin is mandatory)")

uploaded_files = st.file_uploader(
    "Label image(s) for this product",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)

analyze_clicked = st.button("🔍 Analyze Compliance", type="primary", disabled=not uploaded_files)

if uploaded_files:
    preview_cols = st.columns(min(len(uploaded_files), 4))
    for i, f in enumerate(uploaded_files):
        with preview_cols[i % len(preview_cols)]:
            st.image(f, caption=f.name, use_container_width=True)

if analyze_clicked:
    if not api_key:
        st.error("Please enter a Gemini API key in the sidebar first.")
    else:
        try:
            images = [Image.open(io.BytesIO(f.getvalue())).convert("RGB") for f in uploaded_files]
        except Exception as e:
            st.error(f"Could not read one of the uploaded images: {e}")
            images = []

        if images:
            ocr_text = try_ocr(images) if use_ocr else None

            with st.spinner("Reading label and checking compliance…"):
                try:
                    client = genai.Client(api_key=api_key)
                    report = analyze_label(
                        client=client,
                        model_name=model_name,
                        images=images,
                        is_imported=is_imported,
                        product_category=product_category,
                        ocr_text=ocr_text,
                    )
                except Exception as e:
                    report = None
                    st.error(f"Analysis failed: {e}")

            if report:
                # Rule-engine cross-check (from main.py) on top of Gemini's read
                report = apply_unit_cross_validation(report)

                final_product_name = product_name or f"Product {len(st.session_state.history) + 1}"
                scan_timestamp = datetime.now()
                scan_id = f"SCAN-{scan_timestamp.strftime('%Y%m%d%H%M%S')}"

                # Build the PDF (report_generator.py) right alongside the on-screen results
                pdf_bytes = None
                pdf_error = None
                try:
                    pdf_schema = build_pdf_schema(final_product_name, scan_id, scan_timestamp, report)
                    pdf_generator = get_pdf_generator()
                    pdf_path = pdf_generator.generate(pdf_schema)
                    with open(pdf_path, "rb") as fh:
                        pdf_bytes = fh.read()
                except Exception as e:
                    pdf_error = str(e)

                st.session_state.history.append({
                    "product_name": final_product_name,
                    "category": product_category,
                    "imported": is_imported,
                    "report": report,
                    "timestamp": scan_timestamp.strftime("%Y-%m-%d %H:%M"),
                    "scan_id": scan_id,
                    "pdf_bytes": pdf_bytes,
                })

                st.subheader(status_badge(report.overall_status))
                st.write(f"**Confidence:** {report.confidence.title()}")
                st.write(report.summary)
                st.dataframe(report_to_dataframe(report), use_container_width=True, hide_index=True)

                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    st.download_button(
                        "⬇️ Download this report (JSON)",
                        data=report.model_dump_json(indent=2),
                        file_name=f"compliance_report_{scan_timestamp.strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                    )
                with dl_col2:
                    if pdf_bytes:
                        st.download_button(
                            "📄 Download this report (PDF)",
                            data=pdf_bytes,
                            file_name=f"compliance_report_{scan_id}.pdf",
                            mime="application/pdf",
                        )
                    else:
                        st.warning(f"PDF generation failed: {pdf_error}")

st.divider()

# --------------------------------------------------------------------------- #
# Session history / batch dashboard
# --------------------------------------------------------------------------- #
if st.session_state.history:
    st.header("📋 Scan history (this session)")

    summary_rows = []
    for entry in st.session_state.history:
        r: ComplianceReport = entry["report"]
        n_compliant = sum(1 for f in r.findings if f.compliant)
        summary_rows.append({
            "Time": entry["timestamp"],
            "Product": entry["product_name"],
            "Category": entry["category"],
            "Status": status_badge(r.overall_status),
            "Rules Passed": f"{n_compliant}/{len(r.findings)}",
            "Confidence": r.confidence,
        })

    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    with st.expander("View / re-check details for a past scan"):
        options = [f"{i+1}. {e['product_name']} ({e['timestamp']})"
                   for i, e in enumerate(st.session_state.history)]
        choice = st.selectbox("Pick a scan", options, index=len(options) - 1)
        idx = options.index(choice)
        st.dataframe(report_to_dataframe(st.session_state.history[idx]["report"]),
                     use_container_width=True, hide_index=True)

        picked_pdf = st.session_state.history[idx].get("pdf_bytes")
        if picked_pdf:
            st.download_button(
                "📄 Download PDF for this scan",
                data=picked_pdf,
                file_name=f"compliance_report_{st.session_state.history[idx].get('scan_id', idx)}.pdf",
                mime="application/pdf",
                key=f"pdf_dl_{idx}",
            )

    # One consolidated PDF covering every scan this session (report_generator.py)
    try:
        batch_schemas = [
            build_pdf_schema(e["product_name"], e.get("scan_id", f"SCAN-{i}"), e["timestamp"], e["report"])
            for i, e in enumerate(st.session_state.history)
        ]
        batch_pdf_path = get_pdf_generator().generate_batch_summary(batch_schemas)
        with open(batch_pdf_path, "rb") as fh:
            batch_pdf_bytes = fh.read()
        st.download_button(
            "📄 Download batch summary (PDF, all scans)",
            data=batch_pdf_bytes,
            file_name=f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.caption(f"Batch PDF summary unavailable: {e}")

    # Flat export of every finding across every scanned product.
    export_rows = []
    for entry in st.session_state.history:
        for f in entry["report"].findings:
            export_rows.append({
                "Product": entry["product_name"],
                "Category": entry["category"],
                "Timestamp": entry["timestamp"],
                "Overall Status": entry["report"].overall_status,
                "Rule": f.rule,
                "Detected": f.detected,
                "Extracted Value": f.extracted_value,
                "Compliant": f.compliant,
                "Remarks": f.remarks,
            })
    export_df = pd.DataFrame(export_rows)
    st.download_button(
        "⬇️ Export full session history (CSV)",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name=f"lmpc_session_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    if st.button("🗑️ Clear history"):
        st.session_state.history = []
        st.rerun()
else:
    st.info("No products scanned yet in this session.")
