"""A minimal six-node LangGraph workflow you can run locally."""

from datetime import datetime
import json
import os
import random
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

import httpx
from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from workflow_run_registry import CHECKPOINT_DB_PATH, initialize_registry, save_run

CLASSIFIER_API_URL = os.getenv("CLASSIFIER_API_URL", "http://127.0.0.1:8001")
ATTRIBUTION_API_URL = os.getenv("ATTRIBUTION_API_URL", "http://127.0.0.1:8002")
PDF_PATH = Path(
    r"C:\Users\amipa\AVidhyaCourse\GAdkSample\borrower_agent\financial_statement_test_set\ambiguous_pdfs\ambiguous_profit_loss.pdf"
)


class WorkflowState(TypedDict):
    steps: list[str]
    classification: NotRequired[dict[str, Any]]
    borrower_name: NotRequired[str | None]
    random_number: NotRequired[int]
    approved: NotRequired[bool]


def first_node(state: WorkflowState) -> dict[str, Any]:
    path = PDF_PATH.expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file at {PDF_PATH}")

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
def second_node(steps: list[str]) -> dict[str, Any]:
    """Add borrower attribution results and the current time to workflow state."""
    path = PDF_PATH.expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file at {PDF_PATH}")

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

    #current_time = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "steps": [
            *steps,
            f"Node 2: Borrower attribution for {path.name}: "
            f"{json.dumps(attribution, ensure_ascii=False)}",
            #f"Node 2: Current system time is {current_time}",
        ],
        "borrower_name": borrower_name,
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
    approved = interrupt(
        {
            "message": "Node 6 needs human approval before continuing.",
            "random_number": state["random_number"],
        }
    )
    if approved:
        return {
            "steps": [*state["steps"], "Node 6: Approved. Continuing the workflow."],
            "approved": True,
        }
    return {
        "steps": [*state["steps"], "Node 6: Rejected. Returning to Node 2."],
        "approved": False,
    }


def route_after_sixth(
    state: WorkflowState,
) -> Literal["approved, finish", "rejected, retry from node 2"]:
    return "approved, finish" if state.get("approved", False) else "rejected, retry from node 2"


def fourth_node(state: WorkflowState) -> dict[str, list[str]]:
    return {"steps": [*state["steps"], "Node 4: Finish the workflow"]}


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(WorkflowState)
    graph.add_node("pdf_classifier", first_node)
    graph.add_node("borrower_attribution", second_node)
    graph.add_node("third", third_node)
    graph.add_node("fourth", fourth_node)
    graph.add_node("fifth", fifth_node)
    graph.add_node("sixth", sixth_node)

    graph.add_edge(START, "pdf_classifier")
    graph.add_edge("pdf_classifier", "borrower_attribution")
    graph.add_edge("borrower_attribution", "third")
    graph.add_conditional_edges(
        "third",
        route_after_third,
        {
            "random number below 50": "fifth",
            "random number 50 or higher": "sixth",
        },
    )
    graph.add_edge("fifth", "fourth")
    graph.add_conditional_edges(
        "sixth",
        route_after_sixth,
        {
            "approved, finish": "fourth",
            "rejected, retry from node 2": "borrower_attribution",
        },
    )
    graph.add_edge("fourth", END)

    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    from uuid import uuid4

    initialize_registry()
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        checkpointer.setup()
        workflow = build_graph(checkpointer=checkpointer)
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        result = workflow.invoke({"steps": []}, config)

        if result.get("__interrupt__"):
            save_run(thread_id, result, "waiting_for_approval")
            prompt = result["__interrupt__"][0].value
            print(f"Workflow paused for approval (random number {prompt['random_number']}).")
            print(f"Thread ID: {thread_id}")
            print("Open the Gradio page and click Refresh pending runs to review it.")
        else:
            save_run(thread_id, result, "completed")

            print("LangGraph workflow completed:")
            for step in result["steps"]:
                print(f"- {step}")
