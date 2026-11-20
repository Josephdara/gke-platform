import errno
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from conftest import AUTH_ENV, HEADERS, PASSWORDS

ROOT = Path(__file__).resolve().parents[1]


def environment():
    return {
        **os.environ,
        "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT / 'tests'}",
        "ENVIRONMENT": "test", "RELEASE_VERSION": "process-test", "MODEL_URL": "http://model", "LOG_LEVEL": "INFO",
        **AUTH_ENV,
    }


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
    env.pop("MODEL_URL")
    result = subprocess.run([sys.executable, "-m", "rag_api"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "MODEL_URL" in json.loads(result.stderr)["message"]


@pytest.mark.skipif(os.name != "posix", reason="This signal/inherited-socket test requires POSIX")
def test_sigterm_lets_an_active_stream_finish(tmp_path):
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
            process = subprocess.Popen([sys.executable, str(ROOT / "tests" / "process_app.py")], env=env,
                                       stdout=log, stderr=log, pass_fds=(listener.fileno(),))
            try:
                wait_for(lambda: "Application startup complete" in output.read_text(), process)
                body = []
                first_token = threading.Event()

                def stream():
                    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10, headers=HEADERS) as client:
                        signed = client.post("/api/session", json={"username": "tester", "password": PASSWORDS["tester"]})
                        assert signed.status_code == 204
                        with client.stream("POST", "/api/chat", json={"question": "Why?"}) as response:
                            for line in response.iter_lines():
                                body.append(line)
                                if line.startswith("event: token"):
                                    first_token.set()

                reader = threading.Thread(target=stream)
                reader.start()
                assert first_token.wait(5), "The stream never produced a token"
                process.send_signal(signal.SIGTERM)
                reader.join(timeout=10)
                process.wait(timeout=10)
                assert process.returncode in (0, -signal.SIGTERM)
                events = [line for line in body if line.startswith("event: ")]
                assert events[-1] == "event: done"
                assert events.count("event: done") + events.count("event: error") == 1
                logs = [json.loads(line) for line in output.read_text().splitlines()]
                assert [r["outcome"] for r in logs if r["event"] == "chat_completed"] == ["complete"]
                names = [r["event"] for r in logs]
                assert names.index("application_stopped") > names.index("chat_completed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
