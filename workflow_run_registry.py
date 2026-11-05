"""SQLite registry for workflow runs shown in the Gradio approval page."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path


CHECKPOINT_DB_PATH = Path(__file__).with_name("langgraph_approval.sqlite3")


@contextmanager
def registry_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(CHECKPOINT_DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_registry() -> None:
    with registry_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                thread_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                random_number INTEGER,
                BorrowerNm TEXT,
                ClassifiedFile TEXT,
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(workflow_runs)")
        }
        if "BorrowerNm" not in columns:
            connection.execute("ALTER TABLE workflow_runs ADD COLUMN BorrowerNm TEXT")
        if "ClassifiedFile" not in columns:
            connection.execute("ALTER TABLE workflow_runs ADD COLUMN ClassifiedFile TEXT")


def pending_runs() -> list[dict]:
    with registry_connection() as connection:
        rows = connection.execute(
            """
                 SELECT thread_id, random_number, BorrowerNm, ClassifiedFile, steps_json,
                     created_at
            FROM workflow_runs
            WHERE status = 'waiting_for_approval'
            ORDER BY created_at
            """
        ).fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "random_number": row["random_number"],
            "borrower_name": row["BorrowerNm"],
            "classified_file": row["ClassifiedFile"],
            "steps": json.loads(row["steps_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def completed_runs(limit: int = 100) -> list[dict]:
    with registry_connection() as connection:
        rows = connection.execute(
            """
                        SELECT thread_id, status, random_number, BorrowerNm, ClassifiedFile,
                                     steps_json, created_at, updated_at
            FROM workflow_runs
            WHERE status IN ('completed', 'approved', 'rejected')
            ORDER BY updated_at DESC, thread_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "status": row["status"],
            "random_number": row["random_number"],
            "borrower_name": row["BorrowerNm"],
            "classified_file": row["ClassifiedFile"],
            "steps": json.loads(row["steps_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def save_run(thread_id: str, result: dict, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with registry_connection() as connection:
        connection.execute(
            """
            INSERT INTO workflow_runs
                (thread_id, status, random_number, BorrowerNm, ClassifiedFile,
                 steps_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                status = excluded.status,
                random_number = excluded.random_number,
                BorrowerNm = excluded.BorrowerNm,
                ClassifiedFile = excluded.ClassifiedFile,
                steps_json = excluded.steps_json,
                updated_at = excluded.updated_at
            """,
            (
                thread_id,
                status,
                result.get("random_number"),
                result.get("borrower_name"),
                (result.get("classification") or {}).get("category"),
                json.dumps(result.get("steps", [])),
                now,
                now,
            ),
        )
