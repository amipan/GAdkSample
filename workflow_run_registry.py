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
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def pending_runs() -> list[dict]:
    with registry_connection() as connection:
        rows = connection.execute(
            """
            SELECT thread_id, random_number, steps_json, created_at
            FROM workflow_runs
            WHERE status = 'waiting_for_approval'
            ORDER BY created_at
            """
        ).fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "random_number": row["random_number"],
            "steps": json.loads(row["steps_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def completed_runs(limit: int = 100) -> list[dict]:
    with registry_connection() as connection:
        rows = connection.execute(
            """
            SELECT thread_id, status, random_number, steps_json, created_at, updated_at
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
                (thread_id, status, random_number, steps_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                status = excluded.status,
                random_number = excluded.random_number,
                steps_json = excluded.steps_json,
                updated_at = excluded.updated_at
            """,
            (
                thread_id,
                status,
                result.get("random_number"),
                json.dumps(result.get("steps", [])),
                now,
                now,
            ),
        )
