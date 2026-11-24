import os
import json
import re
import time
import pytesseract
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel
from typing import List

# --- PDF report generator integration ---
from report_generator import ComplianceReportGenerator

report_generator = ComplianceReportGenerator(
    output_dir="compliance_reports/pdf"
)
# -----------------------------------------

# Configure Tesseract OCR path
pytesseract.pytesseract.tesseract_cmd = (
    r'C:\Program Files\Tesseract-OCR\tesseract.exe'
)

# Configure Gemini API
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "AQ.Ab8RN6L3kWobMwZmQnH3lZQ7EyIA5E1LRJlgEwxvey6tUVQL-A"
)

client = genai.Client(api_key="AQ.Ab8RN6L3kWobMwZmQnH3lZQ7EyIA5E1LRJlgEwxvey6tUVQL-A")


# ============================================================
# GEMINI RESPONSE SCHEMA
# ============================================================

class Finding(BaseModel):
    rule: str
    detected: bool
    extracted_value: str
    compliant: bool
    legal_citation: str


class ComplianceReport(BaseModel):
    overall_status: str
    findings: List[Finding]
    summary: str


# ============================================================
# UNIT VALIDATION
# ============================================================

def validate_unit_and_numeration(net_quantity_str):
    """
    Python rule-based engine: Legal Metrology (National Standards) Rules 2011
    & Numeration Rules 2011.
    """

    violations = []

    if not net_quantity_str or net_quantity_str.lower() in [
        "not found",
        "none",
        "n/a"
    ]:
        return violations

    # Rule Check: Pluralized units
    if re.search(
        r'\b(kgs|gms|ltrs|mls)\b',
        net_quantity_str,
        re.IGNORECASE
    ):
        violations.append({
            "rule": (
                "Unit Pluralization "
                "(National Standards Rules 2011, Third Schedule Rule 7(1)(b))"
            ),
            "issue": (
                f"Unit symbol in '{net_quantity_str}' appears pluralized. "
                "Unit symbols must remain singular."
            )
        })

    # Rule Check: Invalid Unit Symbols
    if re.search(
        r'\bgm\b',
        net_quantity_str,
        re.IGNORECASE
    ):
        violations.append({
            "rule": (
                "Invalid Unit Symbol "
                "(National Standards Rules 2011, Second/Fourth Schedule)"
            ),
            "issue": (
                f"Declared unit symbol 'gm' in '{net_quantity_str}' "
                "is non-standard. Legal symbol is 'g'."
            )
        })

    # Rule Check: Missing space between quantity and unit
    if re.search(
        r'\d+[a-zA-Z]+',
        net_quantity_str
    ):
        violations.append({
            "rule": (
                "Missing Symbol Space Separation "
                "(National Standards Rules 2011, Third Schedule Rule 7)"
            ),
            "issue": (
                f"No space between numeric value and unit in "
                f"'{net_quantity_str}'. Standard space is required."
            )
        })

    return violations


# ============================================================
# OCR
# ============================================================

def extract_text_with_ocr(image_path):
    """
    Extract text from the product label using Tesseract OCR.
    """

    try:
        with Image.open(image_path) as img:
            text = pytesseract.image_to_string(img)

        return text

    except Exception as e:
        return f"Error reading image: {e}"


# ============================================================
# GEMINI COMPLIANCE INSPECTION
# ============================================================

def inspect_label_text(ocr_text, max_retries=3):

    if not ocr_text.strip():
        return {
            "error": "OCR could not find any text on this image."
        }

    prompt = f"""
You are an automated Legal Metrology (Packaged Commodities)
Compliance Inspector for India.

Analyze the following OCR text extracted from a product label.

--- START OF LABEL TEXT ---

{ocr_text}

--- END OF LABEL TEXT ---

Perform compliance checks for the following mandatory declarations:

1. Name and address of the Manufacturer / Packer / Importer
2. Common or generic name of the commodity
3. Net quantity
4. Month and Year of manufacture / packing / import
5. Maximum Retail Price (MRP) inclusive of all taxes
6. Consumer care contact details
7. Country of Origin for imported goods

For every declaration:

- Determine whether it was detected.
- Extract the value exactly or approximately from the OCR text.
- Determine whether it is compliant.
- Provide the relevant legal citation when there is a violation.
- If the information is not present, use "Not Found".

For the overall status:

COMPLIANT = all applicable mandatory declarations are compliant.

NON_COMPLIANT = one or more mandatory declarations are missing or non-compliant.

Return ONLY the structured JSON response.
"""


    # ========================================================
    # RETRY LOGIC
    # ========================================================

    for attempt in range(max_retries):

        try:

            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ComplianceReport
                )
            )

            report = json.loads(response.text)

            # =================================================
            # PYTHON UNIT CROSS-VALIDATION
            # =================================================

            for item in report.get("findings", []):

                if "net quantity" in item.get(
                    "rule",
                    ""
                ).lower():

                    extracted_val = item.get(
                        "extracted_value",
                        ""
                    )

                    unit_violations = (
                        validate_unit_and_numeration(
                            extracted_val
                        )
                    )

                    if unit_violations:

                        item["compliant"] = False

                        report["overall_status"] = (
                            "NON_COMPLIANT"
                        )

                        additional_notes = " | ".join(
                            [
                                v["issue"]
                                for v in unit_violations
                            ]
                        )

                        citations = " | ".join(
                            [
                                v["rule"]
                                for v in unit_violations
                            ]
                        )

                        item["legal_citation"] = citations

                        report["summary"] += (
                            f" Unit Formatting Error: "
                            f"{additional_notes}"
                        )

            return report

        except Exception as e:

            error_message = str(e)

            # -----------------------------------------------
            # 429 RATE LIMIT
            # -----------------------------------------------

            if (
                "429" in error_message
                or "ResourceExhausted" in error_message
            ):

                wait_time = (2 ** attempt) + 1

                print(
                    f"[!] Gemini rate limit reached. "
                    f"Retrying in {wait_time} seconds..."
                )

                time.sleep(wait_time)

            # -----------------------------------------------
            # 503 TEMPORARY UNAVAILABLE
            # -----------------------------------------------

            elif (
                "503" in error_message
                or "UNAVAILABLE" in error_message
            ):

                wait_time = (2 ** attempt) + 2

                print(
                    f"[!] Gemini temporarily unavailable. "
                    f"Retrying in {wait_time} seconds..."
                )

                time.sleep(wait_time)

            else:

                return {
                    "error": f"API Error: {error_message}"
                }

    return {
        "error": (
            "Exceeded maximum retry attempts due to "
            "Gemini rate limits or temporary service "
            "unavailability."
        )
    }


# ============================================================
# CONVERT GEMINI RESULT TO PDF SCHEMA
# ============================================================

def convert_gemini_report_to_pdf_schema(
    report,
    image_filename
):

    if "error" in report:
        return None

    findings = report.get(
        "findings",
        []
    )

    total = len(findings)

    compliant_count = sum(
        1
        for f in findings
        if f.get("compliant") is True
    )

    score = (
        compliant_count / total * 100
        if total > 0
        else 0
    )

    rules = []

    for f in findings:

        rules.append({
            "field": f.get(
                "rule",
                "Unknown Rule"
            ),

            "status": (
                "PASS"
                if f.get("compliant")
                else "FAIL"
            ),

            "detected_text": f.get(
                "extracted_value",
                "Not Found"
            ),

            "remarks": (
                f.get(
                    "legal_citation",
                    "N/A"
                )
                if not f.get("compliant")
                else "Compliant"
            )
        })

    scan_id = os.path.splitext(
        image_filename
    )[0]

    return {

        "product_name": image_filename,

        "scan_id": scan_id,

        "timestamp": __import__(
            "datetime"
        ).datetime.now(),

        "overall_status": (
            "PASS"
            if report.get(
                "overall_status"
            ) == "COMPLIANT"
            else "FAIL"
        ),

        "compliance_score": score,

        "rules": rules,

        "extracted_fields": {
            "Gemini Summary": report.get(
                "summary",
                "N/A"
            )
        }
    }


# ============================================================
# PROCESS ONE IMAGE
# ============================================================

def process_single_image(image_path):

    filename = os.path.basename(
        image_path
    )

    print(
        f"\n[+] Processing image: {filename}"
    )

    # --------------------------------------------------------
    # 1. OCR
    # --------------------------------------------------------

    print("[1/4] Running OCR...")

    scraped_text = extract_text_with_ocr(
        image_path
    )

    if scraped_text.startswith(
        "Error reading image:"
    ):

        return {
            "filename": filename,
            "status": "OCR_FAILED",
            "error": scraped_text
        }

    if not scraped_text.strip():

        return {
            "filename": filename,
            "status": "OCR_FAILED",
            "error": (
                "No text detected in the image."
            )
        }

    print("[+] OCR completed.")

    # --------------------------------------------------------
    # 2. GEMINI COMPLIANCE
    # --------------------------------------------------------

    print("[2/4] Sending OCR text to Gemini...")

    report = inspect_label_text(
        scraped_text
    )

    if "error" in report:

        return {
            "filename": filename,
            "status": "GEMINI_FAILED",
            "error": report["error"]
        }

    print("[+] Gemini compliance analysis completed.")

    # --------------------------------------------------------
    # 3. SAVE JSON
    # --------------------------------------------------------

    os.makedirs(
        "compliance_reports",
        exist_ok=True
    )

    json_filename = (
        os.path.splitext(filename)[0]
        + "_report.json"
    )

    json_path = os.path.join(
        "compliance_reports",
        json_filename
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(
        f"[+] JSON report saved to: {json_path}"
    )

    # --------------------------------------------------------
    # 4. GENERATE PDF
    # --------------------------------------------------------

    print("[3/4] Generating compliance PDF...")

    pdf_schema = (
        convert_gemini_report_to_pdf_schema(
            report,
            filename
        )
    )

    if pdf_schema is None:

        return {
            "filename": filename,
            "status": "PDF_FAILED",
            "report_path": json_path
        }

    pdf_path = report_generator.generate(
        pdf_schema
    )

    print(
        f"[+] PDF generated: {pdf_path}"
    )

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    print("[4/4] Processing completed.")

    return {
        "filename": filename,
        "status": "SUCCESS",
        "report_path": json_path,
        "pdf_path": pdf_path
    }


# ============================================================
# MAIN - SINGLE IMAGE ONLY
# ============================================================

if __name__ == "__main__":

    # Put ONE product image inside this folder
    IMAGE_DIRECTORY = "input_labels"

    # Find image files
    valid_extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff"
    )

    image_files = [
        f
        for f in os.listdir(
            IMAGE_DIRECTORY
        )
        if f.lower().endswith(
            valid_extensions
        )
    ]

    # --------------------------------------------------------
    # Require exactly ONE image
    # --------------------------------------------------------

    if len(image_files) == 0:

        print(
            "[ERROR] No image found in "
            "'input_labels'."
        )

        print(
            "Put one JPG/PNG/BMP/TIFF product "
            "label image inside the input_labels folder."
        )

        exit()

    if len(image_files) > 1:

        print(
            "[ERROR] More than one image found "
            "in 'input_labels'."
        )

        print(
            "For this test version, keep ONLY ONE "
            "image inside the folder."
        )

        print(
            "Images found:"
        )

        for image in image_files:
            print(
                f" - {image}"
            )

        exit()

    # --------------------------------------------------------
    # Process the single image
    # --------------------------------------------------------

    image_path = os.path.join(
        IMAGE_DIRECTORY,
        image_files[0]
    )

    result = process_single_image(
        image_path
    )

    print("\n====================================")
    print("FINAL RESULT")
    print("====================================")

    print(
        json.dumps(
            result,
            indent=2
        )
    )