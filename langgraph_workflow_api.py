"""FastAPI endpoints for the MySQL-backed LangGraph workflow."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from langgraph_four_node_workflow import build_graph
from workflow_run_registry import (
    classification_result as get_classification_result,
    completed_runs,
    field_extraction_result as get_field_extraction_result,
    initialize_registry,
    mysql_checkpointer,
    pending_runs,
    rejected_runs,
    registry_connection,
    save_run,
)


def sync_interrupted_checkpoints(workflow) -> None:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT checkpoints.thread_id
                FROM checkpoints
                LEFT JOIN workflow_runs USING (thread_id)
                WHERE workflow_runs.thread_id IS NULL
                """
            )
            thread_ids = [row["thread_id"] for row in cursor.fetchall()]

    for thread_id in thread_ids:
        snapshot = workflow.get_state({"configurable": {"thread_id": thread_id}})
        if any(task.interrupts for task in snapshot.tasks):
            save_run(thread_id, snapshot.values, "waiting_for_approval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_registry()
    with mysql_checkpointer() as checkpointer:
        checkpointer.setup()
        app.state.workflow = build_graph(checkpointer=checkpointer)
        yield


app = FastAPI(title="LangGraph Workflow API", lifespan=lifespan)


class WorkflowStartRequest(BaseModel):
    pdf_path: str = Field(min_length=1)
    processed_pdf_path: str | None = None
    thread_id: UUID | None = None


def validate_workflow_paths(payload: WorkflowStartRequest) -> tuple[Path, Path | None]:
    incoming = Path(os.getenv("INCOMING_DIR") or Path(__file__).with_name("IncomingFile")).expanduser().resolve()
    requested = Path(payload.pdf_path).expanduser()
    try:
        source = requested.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail="Incoming PDF was not found.") from error
    if source.parent != incoming or not source.is_file() or source.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="PDF must be a file directly inside IncomingFile.")
    processed = None
    if payload.processed_pdf_path:
        processed = Path(payload.processed_pdf_path).expanduser().resolve()
        if processed.parent != (incoming / "ProcessedFiles").resolve() or processed.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Processed PDF must be directly inside IncomingFile/ProcessedFiles.")
        if processed.exists():
            raise HTTPException(status_code=409, detail="Processed PDF destination already exists.")
    return source, processed


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
        "field_extraction_result": get_field_extraction_result(thread_id),
        "classification_result": get_classification_result(thread_id),
        "classified_file": (result.get("classification") or {}).get("category"),
        "steps": result.get("steps", []),
        "interrupt": interrupt_payload,
    }


@app.post("/workflows")
def start_workflow(payload: WorkflowStartRequest, request: Request) -> dict:
    pdf_path, processed_pdf_path = validate_workflow_paths(payload)
    thread_id = str(payload.thread_id or uuid4())
    if payload.thread_id is not None:
        with registry_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT thread_id FROM workflow_runs WHERE thread_id = %s", (thread_id,))
                if cursor.fetchone() is not None:
                    raise HTTPException(status_code=409, detail="Workflow thread ID already exists.")
    result = request.app.state.workflow.invoke(
        {
            "steps": [],
            "pdf_path": str(pdf_path),
            "processed_pdf_path": str(processed_pdf_path) if processed_pdf_path else None,
        },
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
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM workflow_runs WHERE thread_id = %s",
                (thread_id,),
            )
            row = cursor.fetchone()

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
        status = "rejected"
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
        if values.get("borrower_name") is not None:
            run["borrower_name"] = values.get("borrower_name")
        if values.get("loan_number") is not None:
            run["loan_number"] = values.get("loan_number")
        enriched_runs.append(run)
    return {"runs": enriched_runs}


@app.get("/workflows/completed")
def list_completed_workflows() -> dict:
    return {"runs": completed_runs()}


@app.get("/workflows/rejections")
def list_rejected_workflows() -> dict:
    return {"runs": rejected_runs()}
