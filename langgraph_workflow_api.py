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
        "loan_number": result.get("loan_number"),
        "borrower_extraction_result": result.get("borrower_extraction_result"),
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


async def resume_workflow(
    request: Request,
    thread_id: str,
    approved: bool,
    borrower_name: str | None = None,
    loan_number: str | None = None,
) -> dict:
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
        Command(resume={"approved": approved, "borrower_name": borrower_name, "loan_number": loan_number}),
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
async def approve_workflow(thread_id: str, request: Request) -> dict:
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    borrower_name = payload.get("borrower_name")
    loan_number = payload.get("loan_number")
    return await resume_workflow(
        request,
        thread_id,
        approved=True,
        borrower_name=borrower_name,
        loan_number=loan_number,
    )


@app.post("/workflows/{thread_id}/reject")
async def reject_workflow(thread_id: str, request: Request) -> dict:
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    borrower_name = payload.get("borrower_name")
    loan_number = payload.get("loan_number")
    return await resume_workflow(
        request,
        thread_id,
        approved=False,
        borrower_name=borrower_name,
        loan_number=loan_number,
    )


@app.get("/workflows/pending")
def list_pending_workflows(request: Request) -> dict:
    workflow = request.app.state.workflow
    sync_interrupted_checkpoints(workflow)
    runs = pending_runs()
    enriched_runs = []
    for run in runs:
        state = workflow.get_state({"configurable": {"thread_id": run["thread_id"]}})
        values = state.values or {}
        if values.get("borrower_extraction_result") is not None:
            run["borrower_extraction_result"] = values.get("borrower_extraction_result")
        if values.get("borrower_name") is not None:
            run["borrower_name"] = values.get("borrower_name")
        if values.get("loan_number") is not None:
            run["loan_number"] = values.get("loan_number")
        enriched_runs.append(run)
    return {"runs": enriched_runs}


@app.get("/workflows/completed")
def list_completed_workflows() -> dict:
    return {"runs": completed_runs()}
