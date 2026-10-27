# Synthetic Commercial Banking Financial Statement Test Set

All entities and figures are fictional. These documents are for software testing only and are not financial advice or real borrower records.

## Contents
- `digital_pdfs/`: 3 clean, text-selectable canonical financial statements.
- `scanned_pdfs/`: image-only scanned-style versions of the 3 canonical statement types; OCR should be required.
- `ambiguous_pdfs/`: 8 edge cases including abbreviated profit/loss, working-capital snapshot, cash reconciliation, combined packet, A/R aging, mixed dashboard, incomplete page, and nonfinancial KPIs.
- `manifest.csv`: expected labels and test purpose.

## Expected labels
- `INCOME_STATEMENT`
- `BALANCE_SHEET`
- `CASH_FLOW_STATEMENT`
- `UNKNOWN`

## Suggested evaluation
1. Run text extraction first. Digital PDFs should produce embedded text; scanned PDFs should have little or no embedded text before OCR.
2. Run OCR on scanned PDFs.
3. Classify each document independently.
4. Compare predicted labels to `manifest.csv`.
5. Track per-class precision/recall, confusion matrix, UNKNOWN rate, OCR failure rate, and processing latency.
6. For `ambiguous_pdfs/`, consider a confidence threshold and return `UNKNOWN` when evidence is insufficient.

## Important implementation note
For the combined packet, a document-level classifier should return `UNKNOWN` or `MIXED` if you add that label. A section-aware pipeline may split it into statement sections and classify each section separately.
