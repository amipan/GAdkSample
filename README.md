# GAdkSample

A collection of Google ADK agent examples and document-processing utilities. The repository also includes a LangGraph workflow demo with human approval through a separate FastAPI service and Gradio page.

## Setup

From the `GAdkSample` directory, create a virtual environment and install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## LangGraph Approval Demo

Start the API and Gradio page in separate terminals, with both terminals using the `GAdkSample` directory.

Terminal 1, start FastAPI:

```powershell
.\.venv\Scripts\python.exe -m uvicorn langgraph_workflow_api:app --host 127.0.0.1 --port 8000
```

Terminal 2, start Gradio:

```powershell
.\.venv\Scripts\python.exe langgraph_gradio_app.py
```

Open the Gradio page at <http://127.0.0.1:7860>. FastAPI's interactive API documentation is at <http://127.0.0.1:8000/docs>.

The API provides these endpoints:

- `POST /workflows` starts a workflow.
- `POST /workflows/{thread_id}/approve` approves a paused workflow.
- `POST /workflows/{thread_id}/reject` rejects a paused workflow.
- `GET /workflows/pending` lists workflows awaiting approval.

The workflow branches on a random number from 1 to 100. Values below 50 finish without approval; values of 50 or higher pause at node six for a human decision.

Checkpoints and run information are stored in `langgraph_approval.sqlite3` in the project directory. Keep this file if you need to resume pending runs; it is local runtime data and is excluded from Git.

## Other Examples

The repository also contains Google ADK agents and PDF or financial-document examples in folders such as `borrower_agent`, `field_extractor_agent`, `financial_classifier`, `financial_workflow`, `my_agent`, and `pdf_store`.
