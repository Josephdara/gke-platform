from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def environment():
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "ENVIRONMENT": "test", "RELEASE_VERSION": "process-test", "APP_PORT": "8080", "LOG_LEVEL": "INFO"}


def wait_for(predicate, process, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        assert process.poll() is None, "Server exited before reaching the expected state"
        time.sleep(0.02)
    pytest.fail("Server did not reach the expected state before the timeout")


def test_cli_rejects_invalid_configuration():
    env = environment()
    env.pop("RELEASE_VERSION")
    result = subprocess.run([sys.executable, "-m", "platform_verification_api"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    error = json.loads(result.stderr)
    assert error["event"] == "configuration_error"
    assert "RELEASE_VERSION" in error["message"]
    assert result.stdout == ""


@pytest.mark.skipif(os.name != "posix", reason="This signal/inherited-socket test requires POSIX")
def test_sigterm_drains_inflight_request(tmp_path):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except OSError as exc:
            if exc.errno in (errno.EPERM, errno.EACCES):
                pytest.skip("Sandbox denies local socket binding; real-process shutdown remains unverified")
            raise
        listener.listen(128)
        port = listener.getsockname()[1]
        output = tmp_path / "server.jsonl"
        env = {**environment(), "TEST_SOCKET_FD": str(listener.fileno())}
        with output.open("w") as log:
            process = subprocess.Popen([sys.executable, str(ROOT / "tests" / "process_app.py")], env=env, stdout=log, stderr=log, pass_fds=(listener.fileno(),))
            try:
                wait_for(lambda: "Application startup complete" in output.read_text(), process)
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
                    assert client.get("/readyz").status_code == 200
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        request = pool.submit(client.get, "/test-slow")
                        wait_for(lambda: "test_request_started" in output.read_text(), process)
                        assert not request.done(), "Signal must arrive while a request is still running"
                        started = time.monotonic()
                        process.send_signal(signal.SIGTERM)
                        response = request.result(timeout=5)
                        assert response.status_code == 200
                        assert response.json() == {"status": "completed"}
                        process.wait(timeout=5)
                        assert time.monotonic() - started < 5
                        # Uvicorn can re-raise the captured signal after graceful cleanup.
                        assert process.returncode in (0, -signal.SIGTERM)
                records = [json.loads(line) for line in output.read_text().splitlines()]
                events = [record["event"] for record in records]
                assert "application_stopped" in events
                assert "Finished server process" in " ".join(events)
                request_log, = [record for record in records if record.get("path") == "/test-slow"]
                assert request_log["status"] == 200
                assert request_log["duration_ms"] >= 900
                assert events.index("application_stopped") > events.index("test_request_started")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
