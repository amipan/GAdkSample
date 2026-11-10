import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import langgraph_four_node_workflow as workflow
import langgraph_workflow_api as api
import watch_incoming_files as watcher


class Response:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


def document_api_response(url, **kwargs):
    content = kwargs["files"]["file"][1].read()
    if content != b"%PDF-original":
        raise AssertionError("Workflow did not use the original PDF")
    if url.endswith("/classify"):
        return Response({"category": "TEST"})
    return Response({"borrower_name": "Test", "loan_number": "001"})


class IncomingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.incoming = Path(self.directory.name).resolve()
        self.processed = self.incoming / "ProcessedFiles"
        self.processed.mkdir()
        self.source = self.incoming / "document.pdf"
        self.source.write_bytes(b"%PDF-original")

    def test_rejection_records_original_filename_and_ends(self):
        destination = self.processed / "document.pdf"
        graph = workflow.build_graph(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "test"}}
        with patch.object(workflow.httpx, "post", side_effect=document_api_response) as post, \
             patch.object(workflow, "save_rejection") as save_rejection:
            initial = graph.invoke(
                {"steps": [], "pdf_path": str(self.source), "processed_pdf_path": str(destination)},
                config,
            )
            self.assertTrue(initial.get("__interrupt__"))
            self.source.rename(destination)
            self.source.write_bytes(b"%PDF-another-file")
            rejected = graph.invoke(Command(resume={"approved": False}), config)
            self.assertFalse(rejected.get("__interrupt__"))
            self.assertFalse(rejected["approved"])
            self.assertEqual(post.call_count, 2)
            save_rejection.assert_called_once_with("test", self.source.name)

    def test_api_passes_validated_paths_to_workflow(self):
        graph = workflow.build_graph(checkpointer=InMemorySaver())
        destination = self.processed / "document.pdf"
        api.app.state.workflow = graph
        client = TestClient(api.app)
        self.addCleanup(client.close)
        with patch.dict(os.environ, {"INCOMING_DIR": str(self.incoming)}), \
             patch.object(workflow.httpx, "post", side_effect=document_api_response), \
             patch.object(api, "save_run"), \
             patch.object(api, "workflow_response", return_value={"status": "waiting_for_approval"}):
            response = client.post("/workflows", json={
                "pdf_path": str(self.source),
                "processed_pdf_path": str(destination),
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post("/workflows", json={"pdf_path": str(destination)}).status_code, 400)
            self.assertEqual(client.post("/workflows", json={}).status_code, 422)

    def test_approval_completes_without_recording_rejection(self):
        graph = workflow.build_graph(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "approval-test"}}
        with patch.object(workflow.httpx, "post", side_effect=document_api_response), \
             patch.object(workflow, "save_rejection") as save_rejection:
            initial = graph.invoke({"steps": [], "pdf_path": str(self.source)}, config)
            self.assertTrue(initial.get("__interrupt__"))
            approved = graph.invoke(Command(resume={"approved": True}), config)
            self.assertFalse(approved.get("__interrupt__"))
            self.assertTrue(approved["approved"])
            save_rejection.assert_not_called()

    def test_watcher_stability_success_and_timeout(self):
        observations = {}

        def accepted(_url, **kwargs):
            return Response({"thread_id": kwargs["json"]["thread_id"], "status": "waiting_for_approval"})

        with patch.object(watcher.httpx, "post", side_effect=accepted) as post:
            watcher.scan_incoming(self.incoming, self.processed, observations, 0.0)
            watcher.scan_incoming(self.incoming, self.processed, observations, 2.9)
            self.assertEqual(post.call_count, 0)
            watcher.scan_incoming(self.incoming, self.processed, observations, 3.1)
            self.assertEqual(post.call_count, 1)
            destination = Path(post.call_args.kwargs["json"]["processed_pdf_path"])
            self.assertTrue(destination.is_file())
            self.assertFalse(self.source.exists())
            watcher.scan_incoming(self.incoming, self.processed, observations, 4.1)
            self.assertEqual(post.call_count, 1)

        self.source.write_bytes(b"%PDF-original")
        with patch.object(watcher.httpx, "post", side_effect=httpx.ReadTimeout("uncertain")) as post:
            with self.assertLogs(watcher.LOGGER, level="ERROR"):
                watcher.submit_pdf(self.source, self.processed, "http://example.test")
            marker = watcher.marker_path(self.source)
            self.assertEqual(json.loads(marker.read_text())["status"], "attempting")
            watcher.submit_pdf(self.source, self.processed, "http://example.test")
            self.assertEqual(post.call_count, 1)
            self.assertTrue(self.source.exists())

    def test_watcher_recovers_a_submitted_move(self):
        destination = self.processed / "recovered.pdf"
        marker = watcher.marker_path(self.source)
        data = {
            "status": "submitted",
            "thread_id": "test",
            "source": str(self.source),
            "processed_pdf_path": str(destination),
            "signature": list(watcher.signature(self.source)),
        }
        watcher.write_marker(marker, data, create=True)
        watcher.scan_incoming(self.incoming, self.processed, {}, 0.0)
        self.assertTrue(destination.is_file())
        self.assertFalse(marker.exists())

    def test_watcher_starts_api_and_rejection_ends_after_move(self):
        graph = workflow.build_graph(checkpointer=InMemorySaver())
        api.app.state.workflow = graph
        client = TestClient(api.app)
        self.addCleanup(client.close)

        @contextmanager
        def fake_registry_connection():
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
            yield connection

        def post(url, **kwargs):
            if url.endswith("/workflows"):
                return client.post("/workflows", json=kwargs["json"])
            return document_api_response(url, **kwargs)

        def response(thread_id, result, status):
            return {"thread_id": thread_id, "status": status}

        with patch.dict(os.environ, {"INCOMING_DIR": str(self.incoming)}), \
             patch.object(watcher.httpx, "post", side_effect=post), \
             patch.object(api, "registry_connection", fake_registry_connection), \
             patch.object(api, "save_run"), \
             patch.object(workflow, "save_rejection") as save_rejection, \
             patch.object(api, "workflow_response", side_effect=response):
            watcher.submit_pdf(self.source, self.processed, "http://example.test")
            archived = list(self.processed.glob("*.pdf"))
            self.assertEqual(len(archived), 1)
            thread_id = archived[0].stem.rsplit("_", 1)[-1]
            config = {"configurable": {"thread_id": thread_id}}
            self.assertTrue(graph.get_state(config).tasks[0].interrupts)
            rejected = graph.invoke(Command(resume={"approved": False}), config)
            self.assertFalse(rejected.get("__interrupt__"))
            self.assertEqual(rejected["loan_number"], "001")
            save_rejection.assert_called_once_with(thread_id, self.source.name)


if __name__ == "__main__":
    unittest.main()