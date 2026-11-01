"""Standalone Gradio page for starting and approving LangGraph runs."""

import os

import gradio as gr
import httpx

API_BASE_URL = os.getenv("LANGGRAPH_API_URL", "http://127.0.0.1:8000")


def format_result(result: dict) -> str:
    return "\n".join(f"- {step}" for step in result.get("steps", []))


def call_api(method: str, path: str) -> dict:
    response = httpx.request(
        method,
        f"{API_BASE_URL}{path}",
        timeout=60,
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
            f"{run['thread_id'][:8]} | number {run['random_number']} | {run['created_at']}",
            run["thread_id"],
        )
        for run in runs
    ]


def refresh_pending():
    try:
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not refresh pending runs: {error}"

    choices = dropdown_choices(runs)
    value = choices[0][1] if choices else None
    return gr.update(choices=choices, value=value), f"{len(runs)} pending run(s)."


def start_workflow():
    try:
        result = call_api("POST", "/workflows")
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not start workflow: {error}"

    choices = dropdown_choices(runs)
    if result["status"] == "waiting_for_approval":
        message = (
            f"Approval required for random number {result['random_number']}. "
            f"Thread ID: {result['thread_id']}\n\n{format_result(result)}"
        )
        return gr.update(choices=choices, value=result["thread_id"]), message
    return gr.update(choices=choices, value=None), format_result(result)


def resume_workflow(thread_id: str | None, decision: str):
    if not thread_id:
        update, status = refresh_pending()
        return update, f"Select a pending run first. {status}"

    try:
        result = call_api("POST", f"/workflows/{thread_id}/{decision}")
        runs = call_api("GET", "/workflows/pending")["runs"]
    except (httpx.HTTPError, RuntimeError) as error:
        return gr.update(), f"Could not {decision} workflow: {error}"

    choices = dropdown_choices(runs)
    message = "Approved. Workflow completed." if decision == "approve" else "Rejected. Workflow ended."
    return gr.update(choices=choices, value=None), f"{message}\n\n{format_result(result)}"


def create_page():
    with gr.Blocks(title="LangGraph Human Approval") as page:
        gr.Markdown("# LangGraph workflow approval")
        gr.Markdown("Start a run, then approve or reject it if node six is reached.")

        start_button = gr.Button("Start workflow", variant="primary")
        pending_run = gr.Dropdown(
            label="Pending approval",
            choices=[],
            value=None,
            interactive=True,
        )
        with gr.Row():
            approve_button = gr.Button("Approve")
            reject_button = gr.Button("Reject", variant="stop")
            refresh_button = gr.Button("Refresh pending runs")
        output = gr.Textbox(label="Workflow status", lines=8, interactive=False)

        start_button.click(
            start_workflow,
            outputs=[pending_run, output],
        )
        approve_button.click(
            lambda thread_id: resume_workflow(thread_id, "approve"),
            inputs=pending_run,
            outputs=[pending_run, output],
        )
        reject_button.click(
            lambda thread_id: resume_workflow(thread_id, "reject"),
            inputs=pending_run,
            outputs=[pending_run, output],
        )
        refresh_button.click(
            refresh_pending, outputs=[pending_run, output]
        )
        page.load(refresh_pending, outputs=[pending_run, output])

    return page


def main() -> None:
    create_page().queue().launch()


if __name__ == "__main__":
    main()
