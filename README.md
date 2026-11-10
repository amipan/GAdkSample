# GAdkSample

This sample project demonstrates a LangGraph human-approval workflow for PDF document classification and borrower attribution. It combines a FastAPI workflow control service, a Gradio approval UI, and two separate document-processing APIs.

## Project layout

- `langgraph_four_node_workflow.py` — the six-node workflow used for the demo.
- `langgraph_workflow_api.py` — FastAPI service that starts, resumes, and lists workflows.
- `langgraph_gradio_app.py` — Gradio page for pending and completed runs.
- `frontend/` — React page for pending approvals, history, and rejections.
- `watch_incoming_files.py` — monitors the incoming folder and starts workflows.
- `workflow_run_registry.py` — MySQL registry used by the workflow API and approval UI.
- `File_Classifier/` — PDF classifier API.
- `File_Attribution/` — borrower extraction API.

## Requirements

Create a virtual environment and install the project dependencies:

```powershell
cd GAdkSample
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If you are running the document-processing APIs, install their dependencies from their own folders as needed:

```powershell
cd ..\File_Classifier
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ..\File_Attribution
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Environment configuration

The workflow and UI read their settings from `.env` in the `GAdkSample` folder. A typical file looks like this:

```env
LANGGRAPH_API_URL=http://127.0.0.1:8000
CLASSIFIER_API_URL=http://127.0.0.1:8001
ATTRIBUTION_API_URL=http://127.0.0.1:8002
INCOMING_DIR=C:\path\to\GAdkSample\IncomingFile
INCOMING_STABLE_SECONDS=3
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=fullcircle
MYSQL_USER=root
MYSQL_PASSWORD=your-local-password
GEMINI_MODEL=gemini-2.5-flash
TESSERACT_CMD=C:\path\to\tesseract.exe
```

- `LANGGRAPH_API_URL` is used by the Gradio page to call the workflow API.
- `CLASSIFIER_API_URL` and `ATTRIBUTION_API_URL` are used by the workflow nodes when calling the document APIs.
- `INCOMING_DIR` is optional and defaults to `IncomingFile` next to the workflow API. The watcher and API must use the same directory on a shared filesystem. `INCOMING_STABLE_SECONDS` sets how long the file size and modification time must remain unchanged before submission (default: 3 seconds).
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD` configure both run-history and LangGraph checkpoint storage. Create the `fullcircle` database before starting the workflow API; the application creates its tables.
- `TESSERACT_CMD` is optional but required for OCR on scanned PDFs.
- `.env` contains local credentials and should remain ignored by Git.

## Start the services

### 1) Start the classifier API

```powershell
cd ..\File_Classifier
.\.venv\Scripts\python.exe -m uvicorn classifier_api:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001/docs> to inspect the classifier endpoint.

### 2) Start the borrower attribution API

```powershell
cd ..\File_Attribution
.\.venv\Scripts\python.exe -m uvicorn attribution_api:app --host 127.0.0.1 --port 8002
```

Open <http://127.0.0.1:8002/docs> to inspect the borrower attribution endpoint.

### 3) Start the workflow API

```powershell
cd ..\GAdkSample
.\.venv\Scripts\python.exe -m uvicorn langgraph_workflow_api:app --host 127.0.0.1 --port 8000
```

This API exposes the workflow management endpoints:

- `POST /workflows` — starts a workflow run with JSON containing `pdf_path` and, for the watcher, `processed_pdf_path` and `thread_id`.
- `POST /workflows/{thread_id}/approve` — approves a paused run.
- `POST /workflows/{thread_id}/reject` — rejects a paused run.
- `GET /workflows/pending` — lists workflows waiting for approval.
- `GET /workflows/completed` — lists completed or finalized runs.
- `GET /workflows/rejections` — lists rejected runs and their original PDF filenames.

FastAPI documentation is available at <http://127.0.0.1:8000/docs>.

### 4) Start the folder watcher

In a separate terminal, after starting the three APIs:

```powershell
cd C:\Users\amipa\AVidhyaCourse\GAdkSample
.\.venv\Scripts\python.exe watch_incoming_files.py
```

Drop PDFs directly into `IncomingFile`. The watcher detects existing files on startup as well as new files, waits for their size and modification time to remain unchanged, starts a workflow, and moves successfully submitted PDFs into `IncomingFile\ProcessedFiles`. Processed filenames include the workflow thread ID. Press Ctrl+C to stop the watcher.

The stability window is a heuristic, not proof that a copy has finished. For slow or interrupted transfers, increase `INCOMING_STABLE_SECONDS`, or copy under a non-PDF extension and rename to `.pdf` only after the copy completes. Run only one watcher against the folder.

If the API connection fails before a request is sent, the watcher retries. If the response is lost, times out, or returns an error, the watcher leaves the PDF and a dot-prefixed `.<filename>.workflow.json` marker in place and does not retry automatically. Stop the watcher and inspect the marker's `thread_id`, workflow API lists, checkpoints, and API logs before deciding whether the run started. If it started, retain the PDF at the marker's processed path for possible review retries; if it did not, remove the marker only after resolving the uncertain outcome. A marker with `status` `submitted` is used to retry a move after restart. `IncomingFile` is ignored by Git because it can contain sensitive documents.

### 5) Start the Gradio approval page

```powershell
cd ..\GAdkSample
.\.venv\Scripts\python.exe langgraph_gradio_app.py
```

Open <http://127.0.0.1:7860> to review pending runs and completed history.

The Gradio page also allows a manual start with the server-side path to a PDF directly in `IncomingFile`. Stop the watcher before starting manually to avoid processing the same file twice; manual starts do not move the PDF.

### 6) Start the React frontend

Install Node.js 20.19.x or 22.12+, then use a separate PowerShell terminal:

```powershell
cd C:\Users\amipa\AVidhyaCourse\GAdkSample\frontend
npm install
npm run dev
```

Open the URL Vite prints, usually <http://localhost:5173/>. The workflow API must be running on port 8000; the Vite development server forwards `/api` requests to it. Press Ctrl+C in the frontend terminal to stop it. See `frontend/README.md` for frontend-specific details.

## Workflow behavior

The demo workflow does the following:

1. `pdf_classifier` uploads the run's PDF to the classifier API.
2. `borrower_attribution` uploads the same PDF to the attribution API.
3. The workflow pauses for human review; rejection records the original PDF filename and ends the run, while approval continues.
4. `third` generates a random number and the workflow completes via `fifth` or `sixth` and `fourth`.

The Mermaid graph uses readable conditional edge labels such as:

- `random number below 50`
- `random number 50 or higher`
- `approved, finish`
- `rejected, record rejection`

## File uploads and document APIs

The document APIs are multipart upload endpoints and accept PDF files.

- Classifier endpoint: `POST /classify` in `File_Classifier/classifier_api.py`
- Borrower attribution endpoint: `POST /extract-borrower-name` in `File_Attribution/attribution_api.py`

Each service validates the file extension, the PDF header, and the size before processing the document.

## Local database and workflow history

Workflow state, checkpoint writes, pending interrupts, and run history are stored in the MySQL `fullcircle` database. The workflow API creates the required checkpoint and registry tables at startup.

The registry table `workflow_runs` stores fields including:

- `thread_id`
- `status`
- `random_number`
- `BorrowerNm`
- `LoanNumber`
- `ClassifiedFile`
- `steps_json`
- `result_json` — workflow summary and interrupt metadata, including the classification category but excluding detailed classification and extraction results.
- `created_at`
- `updated_at`

The `workflow_classification` table stores the full classifier response per workflow run, keyed by `thread_id`. The `workflow_field_extractions` table similarly stores the full field-extraction result. The `workflow_rejections` table records each rejected run's thread ID, original PDF filename, and rejection time. Existing classification objects in `result_json` are moved to the classification table at startup. LangGraph checkpoint and write tables are stored in the same MySQL database and retain workflow state.

## Run the standalone script

For a direct workflow run without the Gradio UI, execute:

```powershell
cd GAdkSample
.\.venv\Scripts\python.exe langgraph_four_node_workflow.py "C:\path\to\document.pdf"
```

This script creates a thread, executes the workflow, and saves the result and checkpoint to MySQL. If the workflow pauses for human approval, use the workflow API to approve or reject it.

## Notes

- The app is designed for local development and testing.
- If you change the default ports, make sure the same values are reflected in the `.env` files and API URLs.
