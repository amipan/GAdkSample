"""Start workflows for PDFs placed in the configured incoming directory."""

import json
import logging
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

load_dotenv(Path(__file__).with_name(".env"))

LOGGER = logging.getLogger("incoming_watcher")
INCOMING_DIR = Path(os.getenv("INCOMING_DIR") or Path(__file__).with_name("IncomingFile")).expanduser().resolve()
API_BASE_URL = (os.getenv("LANGGRAPH_API_URL") or "http://127.0.0.1:8000").rstrip("/")
STABLE_SECONDS = float(os.getenv("INCOMING_STABLE_SECONDS", "3"))
SCAN_SECONDS = 1.0


def signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def marker_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.workflow.json")


def write_marker(path: Path, data: dict, *, create: bool = False) -> None:
    with path.open("x" if create else "w", encoding="utf-8") as marker:
        json.dump(data, marker)
        marker.flush()
        os.fsync(marker.fileno())


def move_submitted_pdf(source: Path, marker: Path, data: dict) -> bool:
    destination = Path(data["processed_pdf_path"])
    expected_parent = (source.parent / "ProcessedFiles").resolve()
    if destination.resolve().parent != expected_parent or destination.suffix.lower() != ".pdf":
        LOGGER.error("Invalid processed destination in marker %s", marker)
        return False
    if not source.exists():
        if destination.is_file():
            marker.unlink(missing_ok=True)
            return True
        LOGGER.error("Both incoming and processed files are missing for %s", marker)
        return False
    if list(signature(source)) != data.get("signature"):
        LOGGER.error("Incoming file changed after submission; leaving it in place: %s", source)
        return False
    if destination.exists():
        LOGGER.error("Processed destination already exists; leaving source in place: %s", destination)
        return False
    try:
        source.rename(destination)
    except OSError:
        LOGGER.exception("Could not move submitted PDF; will retry: %s", source)
        return False
    marker.unlink(missing_ok=True)
    LOGGER.info("Moved submitted PDF to %s (thread %s)", destination, data["thread_id"])
    return True


def submit_pdf(source: Path, processed_dir: Path, api_url: str = API_BASE_URL) -> None:
    marker = marker_path(source)
    try:
        current_signature = signature(source)
    except OSError:
        return
    thread_id = str(uuid4())
    destination = processed_dir / f"{source.stem}_{thread_id}{source.suffix}"
    data = {
        "status": "attempting",
        "thread_id": thread_id,
        "source": str(source),
        "processed_pdf_path": str(destination),
        "signature": list(current_signature),
    }
    try:
        write_marker(marker, data, create=True)
    except FileExistsError:
        return
    except OSError:
        LOGGER.exception("Could not create submission marker for %s", source)
        return
    try:
        response = httpx.post(
            f"{api_url}/workflows",
            json={"pdf_path": str(source), "processed_pdf_path": str(destination), "thread_id": thread_id},
            timeout=httpx.Timeout(600.0, connect=5.0),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("thread_id") != thread_id:
            raise ValueError("Workflow API returned an unexpected thread ID")
        if result.get("status") not in {"waiting_for_approval", "completed"}:
            raise ValueError("Workflow API returned an unexpected workflow status")
    except httpx.ConnectError:
        marker.unlink(missing_ok=True)
        LOGGER.warning("Workflow API is unavailable; will retry %s", source)
        return
    except (httpx.HTTPError, ValueError):
        LOGGER.exception("Workflow submission outcome is uncertain; inspect marker before retrying %s", source)
        return
    data["status"] = "submitted"
    try:
        write_marker(marker, data)
        move_submitted_pdf(source, marker, data)
    except OSError:
        LOGGER.exception("Could not record or move submitted PDF; inspect marker: %s", marker)


class IncomingHandler(FileSystemEventHandler):
    def __init__(self, wake: threading.Event) -> None:
        self.wake = wake

    def on_any_event(self, event: FileSystemEvent) -> None:
        if not event.is_directory and event.event_type in {"created", "modified", "moved", "deleted"}:
            self.wake.set()


def scan_incoming(
    incoming: Path,
    processed: Path,
    observations: dict[Path, tuple[tuple[int, int, int], float]],
    now: float,
    api_url: str = API_BASE_URL,
    reported_markers: set[Path] | None = None,
) -> None:
    markers = set(incoming.glob(".*.workflow.json"))
    if reported_markers is not None:
        reported_markers.intersection_update(markers)
    for marker in markers:
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            source = Path(data["source"])
            if source.parent.resolve() != incoming or marker != marker_path(source):
                LOGGER.error("Invalid source in submission marker: %s", marker)
            elif data.get("status") == "submitted":
                move_submitted_pdf(source, marker, data)
            elif data.get("status") == "attempting":
                if reported_markers is None or marker not in reported_markers:
                    LOGGER.warning("Submission outcome unknown; inspect before retrying: %s", marker)
                    if reported_markers is not None:
                        reported_markers.add(marker)
        except (OSError, ValueError, KeyError, TypeError):
            LOGGER.exception("Could not inspect submission marker: %s", marker)

    files = {
        path for path in incoming.iterdir()
        if path.suffix.lower() == ".pdf" and path.is_file() and not path.is_symlink()
    }
    for old in observations.keys() - files:
        observations.pop(old, None)
    for path in files:
        if marker_path(path).exists():
            continue
        try:
            current = signature(path)
        except OSError:
            continue
        previous = observations.get(path)
        if previous is None or previous[0] != current:
            observations[path] = (current, now)
        elif current[0] > 0 and now - previous[1] >= STABLE_SECONDS:
            observations.pop(path, None)
            submit_pdf(path, processed, api_url)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    incoming = INCOMING_DIR
    processed = incoming / "ProcessedFiles"
    processed.mkdir(parents=True, exist_ok=True)
    wake = threading.Event()
    observer = Observer()
    observer.schedule(IncomingHandler(wake), str(incoming), recursive=False)
    observer.start()
    observations: dict[Path, tuple[tuple[int, int, int], float]] = {}
    reported_markers: set[Path] = set()
    LOGGER.info("Watching %s", incoming)
    try:
        while True:
            wake.clear()
            scan_incoming(incoming, processed, observations, time.monotonic(), reported_markers=reported_markers)
            wake.wait(SCAN_SECONDS)
    except KeyboardInterrupt:
        LOGGER.info("Stopping watcher")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()