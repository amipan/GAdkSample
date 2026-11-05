"""FastAPI endpoints for the SQLite-backed LangGraph workflow."""

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from langgraph_four_node_workflow import build_graph
from workflow_run_registry import (
    CHECKPOINT_DB_PATH,
    completed_runs,
    initialize_registry,
    pending_runs,
    registry_connection,
    save_run,
)


def sync_interrupted_checkpoints(workflow) -> None:
    with registry_connection() as connection:
        thread_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT checkpoints.thread_id
                FROM checkpoints
                LEFT JOIN workflow_runs USING (thread_id)
                WHERE workflow_runs.thread_id IS NULL
                """
            )
        ]

    for thread_id in thread_ids:
        snapshot = workflow.get_state({"configurable": {"thread_id": thread_id}})
        if any(task.interrupts for task in snapshot.tasks):
            save_run(thread_id, snapshot.values, "waiting_for_approval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_registry()
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        checkpointer.setup()
        app.state.workflow = build_graph(checkpointer=checkpointer)
        yield


app = FastAPI(title="LangGraph Workflow API", lifespan=lifespan)


def workflow_response(thread_id: str, result: dict, status: str) -> dict:
    interrupt_payload = None
    if result.get("__interrupt__"):
        interrupt_payload = result["__interrupt__"][0].value

    return {
        "thread_id": thread_id,
        "status": status,
        "random_number": result.get("random_number"),
        "borrower_name": result.get("borrower_name"),
        "classified_file": (result.get("classification") or {}).get("category"),
        "steps": result.get("steps", []),
        "interrupt": interrupt_payload,
    }


@app.post("/workflows")
def start_workflow(request: Request) -> dict:
    thread_id = str(uuid4())
    result = request.app.state.workflow.invoke(
        {"steps": []},
        {"configurable": {"thread_id": thread_id}},
    )
    status = "waiting_for_approval" if result.get("__interrupt__") else "completed"
    save_run(thread_id, result, status)
    return workflow_response(thread_id, result, status)


def resume_workflow(request: Request, thread_id: str, approved: bool) -> dict:
    with registry_connection() as connection:
        row = connection.execute(
            "SELECT status FROM workflow_runs WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if row["status"] != "waiting_for_approval":
        raise HTTPException(status_code=409, detail="Workflow run is not waiting for approval")

    result = request.app.state.workflow.invoke(
        Command(resume=approved),
        {"configurable": {"thread_id": thread_id}},
    )
    if result.get("__interrupt__"):
        status = "waiting_for_approval"
    elif approved:
        status = "approved"
    else:
        status = "completed"
    save_run(thread_id, result, status)
    return workflow_response(thread_id, result, status)


@app.post("/workflows/{thread_id}/approve")
def approve_workflow(thread_id: str, request: Request) -> dict:
    return resume_workflow(request, thread_id, approved=True)


@app.post("/workflows/{thread_id}/reject")
def reject_workflow(thread_id: str, request: Request) -> dict:
    return resume_workflow(request, thread_id, approved=False)


@app.get("/workflows/pending")
def list_pending_workflows(request: Request) -> dict:
    workflow = request.app.state.workflow
    sync_interrupted_checkpoints(workflow)
    return {"runs": pending_runs()}


@app.get("/workflows/completed")
def list_completed_workflows() -> dict:
    return {"runs": completed_runs()}
