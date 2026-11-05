# GAdkSample

This sample project demonstrates a LangGraph human-approval workflow for PDF document classification and borrower attribution. It combines a FastAPI workflow control service, a Gradio approval UI, and two separate document-processing APIs.

## Project layout

- `langgraph_four_node_workflow.py` — the six-node workflow used for the demo.
- `langgraph_workflow_api.py` — FastAPI service that starts, resumes, and lists workflows.
- `langgraph_gradio_app.py` — Gradio page for pending and completed runs.
- `workflow_run_registry.py` — SQLite registry used by the workflow API and Gradio app.
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
GEMINI_MODEL=gemini-2.5-flash
TESSERACT_CMD=C:\path\to\tesseract.exe
```

- `LANGGRAPH_API_URL` is used by the Gradio page to call the workflow API.
- `CLASSIFIER_API_URL` and `ATTRIBUTION_API_URL` are used by the workflow nodes when calling the document APIs.
- `TESSERACT_CMD` is optional but required for OCR on scanned PDFs.

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

- `POST /workflows` — starts a workflow run.
- `POST /workflows/{thread_id}/approve` — approves a paused run.
- `POST /workflows/{thread_id}/reject` — rejects a paused run.
- `GET /workflows/pending` — lists workflows waiting for approval.
- `GET /workflows/completed` — lists completed or finalized runs.

FastAPI documentation is available at <http://127.0.0.1:8000/docs>.

### 4) Start the Gradio approval page

```powershell
cd ..\GAdkSample
.\.venv\Scripts\python.exe langgraph_gradio_app.py
```

Open <http://127.0.0.1:7860> to review pending runs and completed history.

## Workflow behavior

The demo workflow does the following:

1. `pdf_classifier` uploads the sample PDF to the classifier API and stores the result in state.
2. `borrower_attribution` uploads the same PDF to the borrower attribution API and stores the extracted name.
3. `third` generates a random number between 1 and 100.
4. If the number is below 50, the workflow finishes in `fifth` and `fourth`.
5. If the number is 50 or higher, the workflow pauses in `sixth` for a human approval decision.
6. Approval continues, while rejection returns the workflow to the borrower-attribution stage.

The Mermaid graph uses readable conditional edge labels such as:

- `random number below 50`
- `random number 50 or higher`
- `approved, finish`
- `rejected, retry from node 2`

## File uploads and document APIs

The document APIs are multipart upload endpoints and accept PDF files.

- Classifier endpoint: `POST /classify` in `File_Classifier/classifier_api.py`
- Borrower attribution endpoint: `POST /extract-borrower-name` in `File_Attribution/attribution_api.py`

Each service validates the file extension, the PDF header, and the size before processing the document.

## Local database and workflow history

Workflow state and run history are stored in `GAdkSample/langgraph_approval.sqlite3`.

The registry table `workflow_runs` stores fields including:

- `thread_id`
- `status`
- `random_number`
- `BorrowerNm`
- `ClassifiedFile`
- `steps_json`
- `created_at`
- `updated_at`

The Gradio page shows the borrower name and classification in the completed table. LangGraph checkpoint rows and write rows are also kept in the same SQLite database and can be cleaned when you want to reset the workflow state.

## Run the standalone script

For a direct workflow run without the Gradio UI, execute:

```powershell
cd GAdkSample
.\.venv\Scripts\python.exe langgraph_four_node_workflow.py
```

This script creates a thread, executes the workflow, and saves the result to SQLite. If the random number triggers a human approval, the workflow pauses until the workflow API is used to approve or reject it.

## Notes

- The app is designed for local development and testing.
- `langgraph_approval.sqlite3` is local runtime state and is not a source-controlled artifact.
- If you change the default ports, make sure the same values are reflected in the `.env` files and API URLs.
