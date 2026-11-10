"""MySQL registry for workflow runs shown in the approval UI."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import ntpath
import os
from collections.abc import Iterator
from pathlib import Path

from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver
import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

load_dotenv(Path(__file__).with_name(".env"))

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "fullcircle")


def _load_result(value: str | None) -> dict | None:
    if not value:
        return None
    return json.loads(value)


def _replace_namespace_hash_expression(query: str) -> str:
    return (
        query.replace(
            "UNHEX(MD5(%s))",
            "UNHEX(SUBSTRING(SHA2(%s, 256), 1, 32))",
        )
        .replace(
            "UNHEX(MD5(%(checkpoint_ns)s))",
            "UNHEX(SUBSTRING(SHA2(%(checkpoint_ns)s, 256), 1, 32))",
        )
    )


class WorkflowMySQLSaver(PyMySQLSaver):
    # This MySQL service lacks MD5() and rejects MD5 generated columns.
    MIGRATIONS = [
        migration.replace(
            "ADD COLUMN checkpoint_ns_hash BINARY(16) AS (UNHEX(MD5(checkpoint_ns))) STORED,",
            "ADD COLUMN checkpoint_ns_hash BINARY(16),",
        )
        for migration in PyMySQLSaver.MIGRATIONS
    ]
    UPSERT_CHECKPOINT_BLOBS_SQL = _replace_namespace_hash_expression(
        PyMySQLSaver.UPSERT_CHECKPOINT_BLOBS_SQL
    )
    UPSERT_CHECKPOINTS_SQL = _replace_namespace_hash_expression(
        PyMySQLSaver.UPSERT_CHECKPOINTS_SQL
    )
    UPSERT_CHECKPOINT_WRITES_SQL = _replace_namespace_hash_expression(
        PyMySQLSaver.UPSERT_CHECKPOINT_WRITES_SQL
    )
    INSERT_CHECKPOINT_WRITES_SQL = _replace_namespace_hash_expression(
        PyMySQLSaver.INSERT_CHECKPOINT_WRITES_SQL
    )

    @staticmethod
    def _select_sql(where: str) -> str:
        return PyMySQLSaver._select_sql(_replace_namespace_hash_expression(where))


def mysql_connection_kwargs() -> dict[str, str | int]:
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "charset": "utf8mb4",
    }


def _new_connection():
    return pymysql.connect(
        **mysql_connection_kwargs(),
        cursorclass=DictCursor,
    )


@contextmanager
def mysql_checkpointer() -> Iterator[PyMySQLSaver]:
    connection = pymysql.connect(**mysql_connection_kwargs(), autocommit=True)
    try:
        yield WorkflowMySQLSaver(connection)
    finally:
        connection.close()


@contextmanager
def registry_connection() -> Iterator[pymysql.Connection]:
    connection = _new_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_registry() -> None:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    thread_id VARCHAR(64) PRIMARY KEY,
                    status VARCHAR(32) NOT NULL,
                    random_number INTEGER,
                    BorrowerNm TEXT,
                    LoanNumber TEXT,
                    ClassifiedFile TEXT,
                    steps_json LONGTEXT NOT NULL,
                    result_json LONGTEXT NULL,
                    created_at VARCHAR(40) NOT NULL,
                    updated_at VARCHAR(40) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute("SHOW COLUMNS FROM workflow_runs")
            columns = {row["Field"] for row in cursor.fetchall()}
            migrations = {
                "BorrowerNm": "ALTER TABLE workflow_runs ADD COLUMN BorrowerNm TEXT",
                "LoanNumber": "ALTER TABLE workflow_runs ADD COLUMN LoanNumber TEXT",
                "ClassifiedFile": "ALTER TABLE workflow_runs ADD COLUMN ClassifiedFile TEXT",
                "result_json": "ALTER TABLE workflow_runs ADD COLUMN result_json LONGTEXT NULL",
            }
            for name, statement in migrations.items():
                if name not in columns:
                    cursor.execute(statement)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_field_extractions (
                    thread_id VARCHAR(64) PRIMARY KEY,
                    field_extraction_result LONGTEXT NOT NULL,
                    created_at VARCHAR(40) NOT NULL,
                    updated_at VARCHAR(40) NOT NULL,
                    CONSTRAINT fk_workflow_field_extractions_run
                        FOREIGN KEY (thread_id) REFERENCES workflow_runs(thread_id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_classification (
                    thread_id VARCHAR(64) PRIMARY KEY,
                    classification_result LONGTEXT NOT NULL,
                    created_at VARCHAR(40) NOT NULL,
                    updated_at VARCHAR(40) NOT NULL,
                    CONSTRAINT fk_workflow_classification_run
                        FOREIGN KEY (thread_id) REFERENCES workflow_runs(thread_id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_rejections (
                    thread_id VARCHAR(64) PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    rejected_at VARCHAR(40) NOT NULL,
                    CONSTRAINT fk_workflow_rejections_run
                        FOREIGN KEY (thread_id) REFERENCES workflow_runs(thread_id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute("SHOW COLUMNS FROM workflow_rejections")
            rejection_columns = {row["Field"] for row in cursor.fetchall()}
            if "file_path" in rejection_columns and "file_name" not in rejection_columns:
                cursor.execute(
                    """
                    SELECT rejections.thread_id, rejections.file_path, runs.result_json
                    FROM workflow_rejections AS rejections
                    JOIN workflow_runs AS runs ON runs.thread_id = rejections.thread_id
                    """
                )
                for row in cursor.fetchall():
                    try:
                        result = _load_result(row["result_json"]) or {}
                    except (TypeError, ValueError):
                        result = {}
                    source_path = result.get("pdf_path") if isinstance(result, dict) else None
                    if not isinstance(source_path, str):
                        source_path = None
                    file_name = ntpath.basename(source_path or row["file_path"])
                    if not source_path:
                        stem, extension = ntpath.splitext(file_name)
                        suffix = f"_{row['thread_id']}"
                        if stem.endswith(suffix):
                            file_name = stem[:-len(suffix)] + extension
                    cursor.execute(
                        "UPDATE workflow_rejections SET file_path = %s WHERE thread_id = %s",
                        (file_name, row["thread_id"]),
                    )
                cursor.execute(
                    "ALTER TABLE workflow_rejections CHANGE COLUMN file_path file_name TEXT NOT NULL"
                )
            cursor.execute(
                """
                SELECT runs.thread_id, runs.result_json, runs.created_at, runs.updated_at
                FROM workflow_runs AS runs
                LEFT JOIN workflow_classification AS classifications USING (thread_id)
                WHERE classifications.thread_id IS NULL
                    AND JSON_VALID(runs.result_json)
                    AND JSON_TYPE(JSON_EXTRACT(runs.result_json, '$.classification')) = 'OBJECT'
                FOR UPDATE
                """
            )
            for row in cursor.fetchall():
                result = json.loads(row["result_json"])
                classification = result["classification"]
                cursor.execute(
                    """
                    INSERT INTO workflow_classification
                        (thread_id, classification_result, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (row["thread_id"], json.dumps(classification, ensure_ascii=False),
                     row["created_at"], row["updated_at"]),
                )
                result["classification"] = classification.get("category")
                cursor.execute(
                    "UPDATE workflow_runs SET result_json = %s WHERE thread_id = %s",
                    (json.dumps(result, ensure_ascii=False), row["thread_id"]),
                )


def pending_runs() -> list[dict]:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT runs.thread_id, runs.random_number, runs.BorrowerNm,
                    runs.LoanNumber, runs.ClassifiedFile, runs.steps_json,
                    runs.result_json, runs.created_at,
                    extractions.field_extraction_result, classifications.classification_result
                FROM workflow_runs AS runs
                LEFT JOIN workflow_field_extractions AS extractions USING (thread_id)
                LEFT JOIN workflow_classification AS classifications USING (thread_id)
                WHERE runs.status = 'waiting_for_approval'
                ORDER BY runs.created_at
                """
            )
            rows = cursor.fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "random_number": row["random_number"],
            "borrower_name": row["BorrowerNm"],
            "loan_number": row["LoanNumber"],
            "classified_file": row["ClassifiedFile"],
            "steps": json.loads(row["steps_json"]),
            "result": _load_result(row["result_json"]),
            "field_extraction_result": _load_result(row["field_extraction_result"]),
            "classification_result": _load_result(row["classification_result"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def completed_runs(limit: int = 100) -> list[dict]:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT runs.thread_id, runs.status, runs.random_number,
                    runs.BorrowerNm, runs.LoanNumber, runs.ClassifiedFile,
                    runs.steps_json, runs.result_json, runs.created_at, runs.updated_at,
                    extractions.field_extraction_result, classifications.classification_result
                FROM workflow_runs AS runs
                LEFT JOIN workflow_field_extractions AS extractions USING (thread_id)
                LEFT JOIN workflow_classification AS classifications USING (thread_id)
                WHERE runs.status IN ('completed', 'approved', 'rejected')
                ORDER BY runs.updated_at DESC, runs.thread_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "status": row["status"],
            "random_number": row["random_number"],
            "borrower_name": row["BorrowerNm"],
            "loan_number": row["LoanNumber"],
            "classified_file": row["ClassifiedFile"],
            "steps": json.loads(row["steps_json"]),
            "result": _load_result(row["result_json"]),
            "field_extraction_result": _load_result(row["field_extraction_result"]),
            "classification_result": _load_result(row["classification_result"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def save_rejection(thread_id: str, file_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workflow_rejections (thread_id, file_name, rejected_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE file_name = VALUES(file_name)
                """,
                (thread_id, file_name, now),
            )


def rejected_runs(limit: int = 100) -> list[dict]:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rejections.thread_id, rejections.file_name, rejections.rejected_at,
                    runs.BorrowerNm, runs.LoanNumber, runs.ClassifiedFile
                FROM workflow_rejections AS rejections
                JOIN workflow_runs AS runs ON runs.thread_id = rejections.thread_id
                ORDER BY rejections.rejected_at DESC, rejections.thread_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "file_name": row["file_name"],
            "rejected_at": row["rejected_at"],
            "borrower_name": row["BorrowerNm"],
            "loan_number": row["LoanNumber"],
            "classified_file": row["ClassifiedFile"],
        }
        for row in rows
    ]


def field_extraction_result(thread_id: str) -> dict | None:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT field_extraction_result FROM workflow_field_extractions WHERE thread_id = %s",
                (thread_id,),
            )
            row = cursor.fetchone()
    return _load_result(row["field_extraction_result"]) if row else None


def classification_result(thread_id: str) -> dict | None:
    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT classification_result FROM workflow_classification WHERE thread_id = %s",
                (thread_id,),
            )
            row = cursor.fetchone()
    return _load_result(row["classification_result"]) if row else None


def save_run(thread_id: str, result: dict, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    classification = result.get("classification")
    serialized_result = {
        key: value
        for key, value in result.items()
        if key not in {"__interrupt__", "field_extraction_result", "classification"}
    }
    if classification is not None:
        serialized_result["classification"] = classification.get("category")
    if interrupts := result.get("__interrupt__"):
        interrupt_payloads = []
        for interrupt in interrupts:
            payload = getattr(interrupt, "value", interrupt)
            if isinstance(payload, dict):
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key != "field_extraction_result"
                }
            interrupt_payloads.append(payload)
        serialized_result["interrupts"] = interrupt_payloads

    with registry_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workflow_runs
                    (thread_id, status, random_number, BorrowerNm, LoanNumber,
                     ClassifiedFile, steps_json, result_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    random_number = VALUES(random_number),
                    BorrowerNm = VALUES(BorrowerNm),
                    LoanNumber = VALUES(LoanNumber),
                    ClassifiedFile = VALUES(ClassifiedFile),
                    steps_json = VALUES(steps_json),
                    result_json = VALUES(result_json),
                    updated_at = VALUES(updated_at)
                """,
                (
                    thread_id,
                    status,
                    result.get("random_number"),
                    result.get("borrower_name"),
                    result.get("loan_number"),
                    (classification or {}).get("category"),
                    json.dumps(result.get("steps", []), ensure_ascii=False),
                    json.dumps(serialized_result, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            if classification is not None:
                cursor.execute(
                    """
                    INSERT INTO workflow_classification
                        (thread_id, classification_result, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        classification_result = VALUES(classification_result),
                        updated_at = VALUES(updated_at)
                    """,
                    (
                        thread_id,
                        json.dumps(classification, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            extraction_result = result.get("field_extraction_result")
            if extraction_result is None:
                cursor.execute(
                    "DELETE FROM workflow_field_extractions WHERE thread_id = %s",
                    (thread_id,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO workflow_field_extractions
                        (thread_id, field_extraction_result, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        field_extraction_result = VALUES(field_extraction_result),
                        updated_at = VALUES(updated_at)
                    """,
                    (
                        thread_id,
                        json.dumps(extraction_result, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
