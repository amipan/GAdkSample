"""A minimal six-node LangGraph workflow you can run locally."""

from datetime import datetime
import random
from typing import Literal, NotRequired, TypedDict

from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from workflow_run_registry import CHECKPOINT_DB_PATH, initialize_registry, save_run


class WorkflowState(TypedDict):
    steps: list[str]
    random_number: NotRequired[int]
    approved: NotRequired[bool]


def first_node(state: WorkflowState) -> dict[str, list[str]]:
    return {"steps": [*state["steps"], "Node 1: Start the workflow"]}


@tool
def second_node(steps: list[str]) -> dict[str, list[str]]:
    """Add the current local system time to the workflow state."""
    current_time = datetime.now().astimezone().isoformat(timespec="seconds")
    return {"steps": [*steps, f"Node 2: Current system time is {current_time}"]}


@tool
def third_node(steps: list[str]) -> dict[str, list[str] | int]:
    """Generate a random number for the workflow's conditional branch."""
    number = random.randint(1, 100)
    return {
        "steps": [*steps, f"Node 3: Generated random number {number}"],
        "random_number": number,
    }


def route_after_third(state: WorkflowState) -> Literal["fifth", "sixth"]:
    if state["random_number"] < 50:
        return "fifth"
    return "sixth"


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


def route_after_sixth(state: WorkflowState) -> Literal["fourth", "second"]:
    return "fourth" if state.get("approved", False) else "second"


def fourth_node(state: WorkflowState) -> dict[str, list[str]]:
    return {"steps": [*state["steps"], "Node 4: Finish the workflow"]}


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(WorkflowState)
    graph.add_node("first", first_node)
    graph.add_node("second", second_node)
    graph.add_node("third", third_node)
    graph.add_node("fourth", fourth_node)
    graph.add_node("fifth", fifth_node)
    graph.add_node("sixth", sixth_node)

    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", "third")
    graph.add_conditional_edges(
        "third",
        route_after_third,
        {"fifth": "fifth", "sixth": "sixth"},
    )
    graph.add_edge("fifth", "fourth")
    graph.add_conditional_edges(
        "sixth",
        route_after_sixth,
        {"fourth": "fourth", "second": "second"},
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
