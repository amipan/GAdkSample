"""A minimal six-node LangGraph workflow you can run locally."""

from datetime import datetime
import json
import os
import random
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from workflow_run_registry import initialize_registry, mysql_checkpointer, save_rejection, save_run

CLASSIFIER_API_URL = os.getenv("CLASSIFIER_API_URL", "http://127.0.0.1:8001")
ATTRIBUTION_API_URL = os.getenv("ATTRIBUTION_API_URL", "http://127.0.0.1:8002")


class WorkflowState(TypedDict):
    steps: list[str]
    pdf_path: str
    processed_pdf_path: NotRequired[str | None]
    classification: NotRequired[dict[str, Any]]
    borrower_name: NotRequired[str | None]
    loan_number: NotRequired[str | None]
    field_extraction_result: NotRequired[dict[str, Any] | None]
    random_number: NotRequired[int]
    approved: NotRequired[bool]


def resolve_pdf_path(pdf_path: str, processed_pdf_path: str | None = None) -> Path:
    for candidate in (processed_pdf_path, pdf_path):
        if candidate:
            path = Path(candidate).expanduser().resolve()
            if path.is_file() and path.suffix.lower() == ".pdf":
                return path
    raise FileNotFoundError("The workflow PDF was not found at its incoming or processed path.")


def first_node(state: WorkflowState) -> dict[str, Any]:
    path = resolve_pdf_path(state["pdf_path"], state.get("processed_pdf_path"))

    with path.open("rb") as pdf_file:
        response = httpx.post(
            f"{CLASSIFIER_API_URL}/classify",
            files={"file": (path.name, pdf_file, "application/pdf")},
            timeout=180,
        )
    response.raise_for_status()
    classification = response.json()
    print(f"Uploaded PDF: {path.name}")
    print(f"Classifier API response:\n{json.dumps(classification, indent=2)}")
    return {
        "steps": [
            *state["steps"],
            f"Node 1: Classified {path.name} as {classification['category']}",
        ],
        "classification": classification,
    }


@tool
def second_node(
    steps: list[str], pdf_path: str, processed_pdf_path: str | None = None
) -> dict[str, Any]:
    """Add borrower and loan-number extraction results to workflow state."""
    path = resolve_pdf_path(pdf_path, processed_pdf_path)

    with path.open("rb") as pdf_file:
        response = httpx.post(
            f"{ATTRIBUTION_API_URL}/extract-borrower-name",
            files={"file": (path.name, pdf_file, "application/pdf")},
            timeout=180,
        )
    response.raise_for_status()
    attribution = response.json()
    print(f"Borrower attribution API response:\n{json.dumps(attribution, indent=2)}")
    borrower_name = attribution.get("borrower_name")
    loan_number = attribution.get("loan_number")

    return {
        "steps": [
            *steps,
            f"Node 2: Extracted borrower and loan number from {path.name}",
        ],
        "borrower_name": borrower_name,
        "loan_number": loan_number,
        "field_extraction_result": attribution,
    }


def human_review(state: WorkflowState) -> dict[str, Any]:
    field_extraction_result = state.get("field_extraction_result")
    decision = interrupt(
        {
            "message": "Review the extracted borrower and choose whether to continue.",
            "borrower_name": state.get("borrower_name"),
            "loan_number": state.get("loan_number"),
            "field_extraction_result": field_extraction_result,
        }
    )
    approved = bool(decision.get("approved", False)) if isinstance(decision, dict) else bool(decision)
    borrower_name = (decision or {}).get("borrower_name") if isinstance(decision, dict) else state.get("borrower_name")
    updated_name = borrower_name or state.get("borrower_name")
    loan_number = (decision or {}).get("loan_number") if isinstance(decision, dict) else state.get("loan_number")
    updated_loan_number = loan_number or state.get("loan_number")
    return {
        "steps": [
            *state["steps"],
            "Node 2.5: Human review complete. "
            + ("Approved; continuing to the random-number stage." if approved else "Rejected; recording the rejection."),
        ],
        "borrower_name": updated_name,
        "loan_number": updated_loan_number,
        "field_extraction_result": field_extraction_result,
        "approved": approved,
    }


@tool
def third_node(steps: list[str]) -> dict[str, list[str] | int]:
    """Generate a random number for the workflow's conditional branch."""
    number = random.randint(1, 100)
    return {
        "steps": [*steps, f"Node 3: Generated random number {number}"],
        "random_number": number,
    }


def route_after_third(
    state: WorkflowState,
) -> Literal["random number below 50", "random number 50 or higher"]:
    if state["random_number"] < 50:
        return "random number below 50"
    return "random number 50 or higher"


def fifth_node(state: WorkflowState) -> dict[str, list[str]]:
    return {"steps": [*state["steps"], "Node 5: The number was less than 50"]}


def sixth_node(state: WorkflowState) -> dict[str, list[str]]:
    return {
        "steps": [*state["steps"], "Node 6: Random number is high enough. Continuing to completion."],
        "approved": True,
    }


def route_after_human_review(
    state: WorkflowState,
) -> Literal["approved, continue to node 3", "rejected, record rejection"]:
    return "approved, continue to node 3" if state.get("approved", False) else "rejected, record rejection"


def record_rejection(state: WorkflowState, config: RunnableConfig) -> dict[str, list[str]]:
    thread_id = str(config["configurable"]["thread_id"])
    file_name = Path(state["pdf_path"]).name
    save_rejection(thread_id, file_name)
    return {"steps": [*state["steps"], "Rejection recorded; workflow ended."]}


def fourth_node(state: WorkflowState) -> dict[str, list[str]]:
    return {"steps": [*state["steps"], "Node 4: Finish the workflow"]}


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(WorkflowState)
    graph.add_node("pdf_classifier", first_node)
    graph.add_node("field_attribution", second_node)
    graph.add_node("human_review", human_review)
    graph.add_node("record_rejection", record_rejection)
    graph.add_node("third", third_node)
    graph.add_node("fourth", fourth_node)
    graph.add_node("fifth", fifth_node)
    graph.add_node("sixth", sixth_node)

    graph.add_edge(START, "pdf_classifier")
    graph.add_edge("pdf_classifier", "field_attribution")
    graph.add_conditional_edges(
        "field_attribution",
        lambda state: "pending human review",
        {"pending human review": "human_review"},
    )
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "approved, continue to node 3": "third",
            "rejected, record rejection": "record_rejection",
        },
    )
    graph.add_conditional_edges(
        "third",
        route_after_third,
        {
            "random number below 50": "fifth",
            "random number 50 or higher": "sixth",
        },
    )
    graph.add_edge("fifth", "fourth")
    graph.add_edge("sixth", "fourth")
    graph.add_edge("record_rejection", END)
    graph.add_edge("fourth", END)

    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    import argparse
    from uuid import uuid4

    parser = argparse.ArgumentParser(description="Run the workflow for a PDF file.")
    parser.add_argument("pdf_path", help="Path to the PDF to process")
    args = parser.parse_args()
    pdf_path = resolve_pdf_path(args.pdf_path)
    initialize_registry()
    with mysql_checkpointer() as checkpointer:
        checkpointer.setup()
        workflow = build_graph(checkpointer=checkpointer)
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        result = workflow.invoke({"steps": [], "pdf_path": str(pdf_path)}, config)

        if result.get("__interrupt__"):
            save_run(thread_id, result, "waiting_for_approval")
            print("Workflow paused for approval.")
            print(f"Thread ID: {thread_id}")
            print("Open the Gradio page and click Refresh pending runs to review it.")
        else:
            save_run(thread_id, result, "completed")

            print("LangGraph workflow completed:")
            for step in result["steps"]:
                print(f"- {step}")
