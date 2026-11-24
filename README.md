# Food-Detector-
web app that scans packaged product labels (including food &amp; beverages) to verify compliance with India's Legal Metrology (Packaged Commodities) Rules, 2011, complete with automated PDF/JSON/CSV reporting.

# ⚖️ Legal Metrology Compliance Checker

An AI-powered web application built for **Smart India Hackathon 2026 (Problem Statement: SIH26034 — Ministry of Consumer Affairs, Food & Public Distribution)**. Upload photos of packaged food or consumer product labels to automatically verify mandatory declarations against **Rule 6 of the Legal Metrology (Packaged Commodities) Rules, 2011**.

## ✨ Key Features

- **Multi-Panel Label Upload:** Supports uploading one or multiple label images (front, back, or declaration panels) in `JPG`, `PNG`, or `WEBP` formats.
- **Hybrid AI + Local OCR Analysis:** Uses Google's **Gemini 2.5 Flash** (configurable via the sidebar) with an optional **Local OCR** toggle to extract supporting text context for higher accuracy.
- **Product & Import Context:** Supports product categorization (e.g., *Food & Beverage*, *General / Other*) and an imported product toggle that automatically enforces mandatory Country of Origin checks.
- **Automated Verdict & Confidence Scoring:** Returns a clear `COMPLIANT` or `NON-COMPLIANT` verdict, a confidence rating, an AI-generated summary, and a rule-by-rule breakdown table.
- **Rich Exportable Reports:**
  - **Individual PDF Report:** Includes Scan ID, compliance score (%), Pass/Fail donut and bar charts, a detailed declaration check table, and extracted summary fields.
  - **JSON Export:** Structured compliance output for downstream integrations.
- **Session Scan History & Batch Exports:** Tracks all products scanned in the current session, lets you inspect past scans, and supports exporting a **Batch Summary PDF** or full **Session History CSV**.

## 📋 Mandatory Declarations Checked (Rule 6)

The checker evaluates every uploaded label against the 7 core declarations:
1. Name and complete address of the manufacturer / packer / importer
2. Common or generic name of the commodity
3. Net quantity in standard (metric) units
4. Month and year of manufacture / packing / import
5. Maximum Retail Price (MRP) inclusive of all taxes
6. Consumer care name, address, and contact details
7. Country of origin *(mandatory for imported products)*

## 🛠️ Tech Stack

- **Frontend / UI:** Streamlit
- **Vision & Compliance Engine:** Google Gemini API (`gemini-2.5-flash`)
- **OCR Support:** Local OCR engine (optional supporting context)
- **Reporting & Visualization:** Automated PDF report generation with charts, JSON, and CSV exports

## 🚀 How It Works

1. Enter your **Gemini API Key** and select the model in the sidebar (optionally enable local OCR).
2. Enter the **Product Name**, select the **Category**, and check the box if it is an imported product.
3. Upload one or more clear photos of the product label and click **Analyze Compliance**.
4. Review the rule-by-rule compliance table and download the **PDF** or **JSON** report, or export your entire session history as a **Batch PDF** or **CSV**.

> *Disclaimer: This tool reflects automated OCR extraction and AI-assisted verification against the Legal Metrology (Packaged Commodities) Rules, 2011, and is intended to assist—not replace—manual verification.*
