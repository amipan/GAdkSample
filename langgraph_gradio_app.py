"""Standalone Gradio page for starting and approving LangGraph runs."""

import json
import os
from pathlib import Path
from typing import Literal

import gradio as gr
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
API_BASE_URL = os.getenv("LANGGRAPH_API_URL") or "http://127.0.0.1:8000"


def format_result(result: dict) -> str:
    return "\n".join(f"- {step}" for step in result.get("steps", []))


def call_api(method: str, path: str, json_body: dict | None = None) -> dict:
    response = httpx.request(
        method,
        f"{API_BASE_URL}{path}",
        json=json_body,
        timeout=420 if method == "POST" else 60,
    )
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"API returned {response.status_code}: {detail}")
    return response.json()


def dropdown_choices(runs: list[dict]) -> list[tuple[str, str]]:
    return [
        (
            f"{run['thread_id'][:8]} | {run.get('classified_file') or 'unclassified'} | "
            f"number {run['random_number']} | {run['created_at']}",
            run["thread_id"],
        )
        for run in runs
    ]


def format_field_extraction_result(result: dict | None) -> str:
    if not result:
        return "No field extraction result available."
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_field_attribution_details(
    extraction_json: str | None,
    field: Literal["borrower_name", "loan_number"],
) -> str:
    if not extraction_json:
        return "No attribution result available for this workflow."
    try:
        result = json.loads(extraction_json)
    except ValueError:
        return "Could not read the attribution result for this workflow."
    if not isinstance(result, dict):
        return "Could not read the attribution result for this workflow."

    label = "Borrower" if field == "borrower_name" else "Loan number"
    value = result.get(field)
    confidence = result.get(f"{field}_confidence")
    rationale = result.get(f"{field}_rationale")
    evidence_quote = result.get(f"{field}_evidence_quote")
    page_number = result.get(f"{field}_page_number")

    if field == "borrower_name":
        evidence_quote = evidence_quote or result.get("evidence_quote")
        page_number = page_number or result.get("page_number")

    confidence_text = (
        f"{confidence:.0%}"
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else "Not available"
    )
    return "\n".join(
        [
            f"Field: {label}",
            f"Result: {value if value is not None else 'Not found'}",
            f"Confidence: {confidence_text}",
            f"Rationale: {rationale or 'Field-specific rationale is not available for this older result.'}",
            f"Evidence: {evidence_quote or 'Not available'}",
            f"Page: {page_number if page_number is not None else 'Not available'}",
        ]
    )


def selected_pending_run_details(thread_id: str | None) -> tuple[str, str, str, str]:
    if not thread_id:
        return "", "", "No pending workflow selected.", ""
    try:
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError):
        return "", "", "Could not load borrower details for the selected run.", ""

    run = next((entry for entry in runs if entry["thread_id"] == thread_id), None)
    if run is None:
        return "", "", "Selected run not found.", ""
    borrower_name = run.get("borrower_name") or ""
    loan_number = run.get("loan_number") or ""
    extraction_result = format_field_extraction_result(run.get("field_extraction_result"))
    return borrower_name, loan_number, extraction_result, ""


def completed_table_rows() -> list[list[str | int | None]]:
    runs = call_api("GET", "/workflows/completed")["runs"]
    return [
        [
            run["updated_at"],
            run["thread_id"][:10],
            run["status"],
            run["classified_file"],
            run["borrower_name"],
            run["loan_number"],
            run["random_number"],
            " | ".join(run["steps"]),
        ]
        for run in runs
    ]


def refresh_completed():
    try:
        rows = completed_table_rows()
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not load completed workflows: {error}"
    return rows, f"Showing {len(rows)} completed workflow(s), newest first."


def refresh_pending():
    try:
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not refresh pending runs: {error}", "", "", "No pending workflow selected.", ""

    choices = dropdown_choices(runs)
    value = choices[0][1] if choices else None
    borrower_name = ""
    loan_number = ""
    extraction_result = "No pending workflow selected."
    if value:
        selected_run = next((entry for entry in runs if entry["thread_id"] == value), None)
        if selected_run is not None:
            borrower_name = selected_run.get("borrower_name") or ""
            loan_number = selected_run.get("loan_number") or ""
            extraction_result = format_field_extraction_result(selected_run.get("field_extraction_result"))
    return gr.update(choices=choices, value=value), f"{len(runs)} pending run(s).", borrower_name, loan_number, extraction_result, ""


def start_workflow(pdf_path: str | None):
    if not pdf_path or not pdf_path.strip():
        return gr.update(), "Enter the path to a PDF in IncomingFile.", gr.update(), "", "", "No pending workflow selected.", ""
    try:
        result = call_api("POST", "/workflows", {"pdf_path": pdf_path.strip()})
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not start workflow: {error}", gr.update(), "", "", "No borrower extraction result available.", ""

    choices = dropdown_choices(runs)
    borrower_name = result.get("borrower_name") or ""
    loan_number = result.get("loan_number") or ""
    extraction_result = format_field_extraction_result(result.get("field_extraction_result"))
    if result["status"] == "waiting_for_approval":
        message = (
            f"Approval required for borrower {borrower_name or 'unknown'} and loan number {loan_number or 'unknown'}. "
            f"Thread ID: {result['thread_id']}\n\n{format_result(result)}"
        )
        return gr.update(choices=choices, value=result["thread_id"]), message, gr.update(), borrower_name, loan_number, extraction_result, ""
    completed_update, _ = refresh_completed()
    return gr.update(choices=choices, value=None), format_result(result), completed_update, "", "", "No pending workflow selected.", ""


def resume_workflow(
    thread_id: str | None,
    decision: str,
    borrower_name: str | None = None,
    loan_number: str | None = None,
):
    if not thread_id:
        update, status, _, _, _, _ = refresh_pending()
        return update, f"Select a pending run first. {status}", gr.update(), "", "", "No pending workflow selected.", ""

    try:
        result = call_api(
            "POST",
            f"/workflows/{thread_id}/{decision}",
            json_body={"borrower_name": borrower_name, "loan_number": loan_number} if decision == "approve" else None,
        )
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not {decision} workflow: {error}", gr.update(), "", "", "No pending workflow selected.", ""

    choices = dropdown_choices(runs)
    borrower_value = result.get("borrower_name") or borrower_name or ""
    loan_value = result.get("loan_number") or loan_number or ""
    extraction_value = format_field_extraction_result(result.get("field_extraction_result"))
    if result["status"] == "waiting_for_approval":
        message = (
            "Rejected. Workflow returned to the borrower-attribution step and needs another review "
            f"for borrower: {result['borrower_name']}."
        )
        return (
            gr.update(choices=choices, value=thread_id),
            f"{message}\n\n{format_result(result)}",
            gr.update(),
            borrower_value,
            loan_value,
            extraction_value,
            "",
        )

    if decision == "approve":
        message = "Approved. Workflow completed."
    else:
        message = "Rejected. Workflow returned to borrower attribution and completed."
    completed_update, _ = refresh_completed()
    return (
        gr.update(choices=choices, value=None),
        f"{message}\n\n{format_result(result)}",
        completed_update,
        "",
        "",
        "No pending workflow selected.",
        "",
    )


def create_page():
    with gr.Blocks(title="LangGraph Human Approval") as page:
        gr.Markdown("# FullCircle Workflow")
        gr.Markdown("Review workflows waiting for borrower and loan-number approval.")

        with gr.Tabs():
            with gr.Tab("Pending approvals"):
                incoming_pdf_path = gr.Textbox(label="Incoming PDF path", lines=1)
                start_button = gr.Button("Start workflow", variant="primary")
                pending_run = gr.Dropdown(
                    label="Pending approval",
                    choices=[],
                    value=None,
                    interactive=True,
                )
                with gr.Row():
                    pending_borrower = gr.Textbox(
                        label="Borrower",
                        lines=1,
                        interactive=True,
                        scale=5,
                    )
                    borrower_info_button = gr.Button("ⓘ", size="sm", scale=0, min_width=42)
                    pending_loan_number = gr.Textbox(
                        label="Loan number",
                        lines=1,
                        interactive=True,
                        scale=5,
                    )
                    loan_number_info_button = gr.Button("ⓘ", size="sm", scale=0, min_width=42)
                pending_extraction = gr.State()
                attribution_details = gr.Textbox(
                    label="Field attribution details",
                    lines=5,
                    interactive=False,
                )
                with gr.Row():
                    approve_button = gr.Button("Approve")
                    reject_button = gr.Button("Reject", variant="stop")
                    refresh_button = gr.Button("Refresh pending runs")
                output = gr.Textbox(label="Workflow status", lines=8, interactive=False)

            with gr.Tab("Completed workflows"):
                completed_refresh_button = gr.Button("Refresh completed workflows")
                completed_table = gr.Dataframe(
                    value=[],
                    headers=["Finished (UTC)", "Thread ID", "Status", "Classification", "Borrower", "Loan number", "Random number", "Steps"],
                    datatype=["str", "str", "str", "str", "str", "str", "number", "str"],
                    column_count=8,
                    max_height=420,
                    interactive=False,
                    wrap=True,
                    show_search="search",
                )
                completed_status = gr.Textbox(
                    label="History status",
                    lines=1,
                    interactive=False,
                )

        pending_run.change(
            selected_pending_run_details,
            inputs=pending_run,
            outputs=[pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        borrower_info_button.click(
            lambda extraction_json: format_field_attribution_details(extraction_json, "borrower_name"),
            inputs=pending_extraction,
            outputs=attribution_details,
        )
        loan_number_info_button.click(
            lambda extraction_json: format_field_attribution_details(extraction_json, "loan_number"),
            inputs=pending_extraction,
            outputs=attribution_details,
        )
        start_button.click(
            start_workflow,
            inputs=incoming_pdf_path,
            outputs=[pending_run, output, completed_table, pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        approve_button.click(
            lambda thread_id, borrower_name, loan_number: resume_workflow(
                thread_id, "approve", borrower_name, loan_number
            ),
            inputs=[pending_run, pending_borrower, pending_loan_number],
            outputs=[pending_run, output, completed_table, pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        reject_button.click(
            lambda thread_id: resume_workflow(thread_id, "reject"),
            inputs=pending_run,
            outputs=[pending_run, output, completed_table, pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        refresh_button.click(
            refresh_pending,
            outputs=[pending_run, output, pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        completed_refresh_button.click(
            refresh_completed,
            outputs=[completed_table, completed_status],
        )
        page.load(
            refresh_pending,
            outputs=[pending_run, output, pending_borrower, pending_loan_number, pending_extraction, attribution_details],
        )
        page.load(refresh_completed, outputs=[completed_table, completed_status])

    return page


def main() -> None:
    create_page().queue().launch()


if __name__ == "__main__":
    main()
