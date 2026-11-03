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

Node one classifies the hardcoded PDF by uploading it to the separate `File_Classifier` service. Start that service first in a terminal:

```powershell
cd ..\File_Classifier
.\.venv\Scripts\python.exe -m uvicorn classifier_api:app --host 127.0.0.1 --port 8001
```

The classifier API uses `CLASSIFIER_API_URL`, which defaults to `http://127.0.0.1:8001`. If you change its port, set the same environment variable for the GAdkSample workflow API.

Then, from the `GAdkSample` directory, start the workflow-control API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn langgraph_workflow_api:app --host 127.0.0.1 --port 8000
```

In another terminal, also from `GAdkSample`, start the Gradio approval page:

```powershell
.\.venv\Scripts\python.exe langgraph_gradio_app.py
```

Open the Gradio page at <http://127.0.0.1:7860>. FastAPI's interactive API documentation is at <http://127.0.0.1:8000/docs>.

The API provides these endpoints:

- `POST /workflows` starts a workflow.
- `POST /workflows/{thread_id}/approve` approves a paused workflow.
- `POST /workflows/{thread_id}/reject` rejects a paused workflow.
- `GET /workflows/pending` lists workflows awaiting approval.
- `GET /workflows/completed` lists finalized workflows, newest first.

The workflow branches on a random number from 1 to 100. Values below 50 finish without approval; values of 50 or higher pause at node six for a human decision.

Checkpoints and run information are stored in `langgraph_approval.sqlite3` in the project directory. Keep this file if you need to resume pending runs; it is local runtime data and is excluded from Git.

### Run the standalone LangGraph script

With the `File_Classifier` API running on port 8001, run this from `GAdkSample`:

```powershell
.\.venv\Scripts\python.exe langgraph_four_node_workflow.py
```

Node one prints the classifier API response and saves it in graph state. If the random-number branch reaches node six, the run is checkpointed in SQLite. To review or resume it in Gradio, the GAdkSample workflow-control API and approval page must also be running.

## Other Examples

The repository also contains Google ADK agents and PDF or financial-document examples in folders such as `borrower_agent`, `field_extractor_agent`, `financial_classifier`, `financial_workflow`, `my_agent`, and `pdf_store`.
