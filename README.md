# GAdkSample

This sample project demonstrates a LangGraph human-approval workflow for PDF document classification and borrower attribution. It combines a FastAPI workflow control service, a Gradio approval UI, and two separate document-processing APIs.

## Project layout

- `langgraph_four_node_workflow.py` — the LangGraph workflow used for the demo.
- `langgraph_workflow_api.py` — FastAPI service that starts, resumes, and lists workflows.
- `langgraph_gradio_app.py` — Gradio page for pending and completed runs.
- `workflow_run_registry.py` — SQLite registry used by the workflow API and Gradio app.
- `File_Classifier/` — PDF classifier API.
- `File_Attribution/` — borrower and loan-number extraction API.

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
2. `borrower_attribution` uploads the PDF to the attribution API and stores the borrower name, loan number, and extraction evidence.
3. The workflow pauses at `human_review`. The reviewer can correct the borrower name or loan number before approving.
4. Approval continues to `third`, which generates a random number between 1 and 100.
5. If the number is below 50, the workflow runs `fifth`; if it is 50 or higher, it runs `sixth`. Both branches finish through `fourth`.
6. Rejection returns the workflow to `borrower_attribution` and pauses again for review.

The graph uses readable conditional edge labels such as:

- `random number below 50`
- `random number 50 or higher`
- `approved, continue to node 3`
- `rejected, remain in borrower attribution`

## File uploads and document APIs

The document APIs are multipart upload endpoints and accept PDF files.

- Classifier endpoint: `POST /classify` in `File_Classifier/classifier_api.py`
- Borrower and loan-number extraction endpoint: `POST /extract-borrower-name` in `File_Attribution/attribution_api.py`

Each service validates the file extension, the PDF header, and the size before processing the document.

The attribution response is a named JSON object. It includes `borrower_name` and a nullable `loan_number`, plus separate evidence quotes and one-based page numbers. A loan number is returned only when it is explicitly labeled in the document; its exact text, including leading zeroes, is preserved. Extracted evidence is checked against the PDF text, and the response reports `validation_status` and any `validation_issues`. Scanned pages use OCR and require Tesseract.

## Local database and workflow history

Workflow state and run history are stored in `GAdkSample/langgraph_approval.sqlite3`.

The registry table `workflow_runs` stores fields including:

- `thread_id`
- `status`
- `random_number`
- `BorrowerNm`
- `LoanNumber`
- `ClassifiedFile`
- `steps_json`
- `created_at`
- `updated_at`

The Gradio pending-review page displays editable Borrower and Loan number fields on the same row, along with the full extraction result. The completed table includes both borrower and loan number. Existing registries gain the `LoanNumber` column on initialization. LangGraph checkpoint rows and write rows are also kept in the same SQLite database and can be cleaned when you want to reset the workflow state.

## Run the standalone script

For a direct workflow run without the Gradio UI, execute:

```powershell
cd GAdkSample
.\.venv\Scripts\python.exe langgraph_four_node_workflow.py
```

This script creates a thread, executes the workflow, and saves the result to SQLite. The workflow pauses for human review after extraction. After approval, it generates a random number and follows the corresponding branch; rejection returns it to borrower attribution for another review.

## Notes

- The app is designed for local development and testing.
- `langgraph_approval.sqlite3` is local runtime state and is not a source-controlled artifact.
- If you change the default ports, make sure the same values are reflected in the `.env` files and API URLs.
