import argparse
import hashlib
import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
TABLE_NAME = "pdf_documents"


def store_pdf(pdf_path: Path) -> int:
    load_dotenv(BASE_DIR / ".env")

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if pdf_path.suffix.casefold() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {pdf_path}")

    database = os.getenv("MYSQL_DATABASE")
    user = os.getenv("MYSQL_USER")
    if not database or not user:
        raise ValueError(
            "Set MYSQL_DATABASE and MYSQL_USER in the environment or project .env file."
        )

    pdf_bytes = pdf_path.read_bytes()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user,
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=database,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    file_name VARCHAR(255) NOT NULL,
                    source_path TEXT NOT NULL,
                    file_size BIGINT UNSIGNED NOT NULL,
                    sha256 CHAR(64) NOT NULL,
                    pdf_data LONGBLOB NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_pdf_documents_sha256 (sha256)
                ) ENGINE=InnoDB
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                    (file_name, source_path, file_size, sha256, pdf_data)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    pdf_path.name,
                    str(pdf_path.resolve()),
                    len(pdf_bytes),
                    file_hash,
                    pdf_bytes,
                ),
            )
            record_id = cursor.lastrowid

        connection.commit()
        return record_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store a PDF file and its metadata in MySQL."
    )
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF file")
    args = parser.parse_args()

    try:
        record_id = store_pdf(args.pdf_path)
    except (OSError, ValueError, mysql.connector.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Stored {args.pdf_path} in MySQL table {TABLE_NAME} (id={record_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())