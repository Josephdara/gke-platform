import asyncio
import json

import httpx

from loadgen.client import Assistant, Sample
from loadgen.evaluate import score
from loadgen.load import summarize
from loadgen.upload import upload

META = {"conversationId": "c1", "mode": "documentation", "promptVersion": "grounded-v2",
        "sources": [{"label": "S1", "title": "Deployments", "headingPath": "Rolling Back a Deployment > Checking", "score": 0.8}]}
DONE = {"status": "complete", "usage": {"promptTokens": 9, "completionTokens": 3},
        "citations": {"valid": ["S1"], "invalid": []}}


def sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def assistant(chat_body: bytes | None, status: int = 200) -> tuple[Assistant, list]:
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/session":
            return httpx.Response(204)
        return httpx.Response(status, content=chat_body or b"", headers={"x-request-id": "r1", "retry-after": "7"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://assistant.test")
    return Assistant("https://assistant.test", client), seen


def test_a_complete_stream_is_recorded_with_its_sources_and_the_headers_rag_api_requires():
    client, seen = assistant(sse(("meta", META), ("token", {"text": "Run "}), ("token", {"text": "undo [S1]."}), ("done", DONE)))

    async def scenario():
        await client.sign_in("bench", "secret")
        return await client.ask("How do I roll back?", keep_answer=True)
    sample = asyncio.run(scenario())
    assert (sample.outcome, sample.mode, sample.request_id, sample.answer) == ("complete", "documentation", "r1", "Run undo [S1].")
    assert sample.ttft_s is not None and sample.valid_citations == ["S1"] and sample.completion_tokens == 3
    assert all(r.headers["origin"] == "https://assistant.test" and r.headers["x-assistant-client"] == "1" for r in seen)


def test_a_stream_without_a_terminal_event_is_cut_and_a_refusal_keeps_its_status():
    cut, _ = assistant(sse(("meta", META), ("token", {"text": "Run"})))
    refused, _ = assistant(None, status=429)
    assert asyncio.run(cut.ask("q")).outcome == "cut"
    sample = asyncio.run(refused.ask("q"))
    assert (sample.outcome, sample.retry_after_s) == ("http:429", 7)


def test_summary_and_evaluation_checks():
    samples = [Sample("q", f"2026-11-22T10:00:0{n}Z", "complete", ttft_s=float(n), total_s=10.0 + n) for n in range(1, 5)]
    samples.append(Sample("q", "2026-11-22T10:00:09Z", "cut", request_id="r9"))
    summary = summarize(samples)
    assert summary["outcomes"] == {"complete": 4, "cut": 1} and summary["answered"] == 4
    assert summary["ttftSeconds"] == {"p50": 2.0, "p95": 4.0, "count": 4}
    assert summary["failed"] == [{"startedAt": "2026-11-22T10:00:09Z", "outcome": "cut", "requestId": "r9"}]

    answered = Sample("q", "t", "complete", sources=META["sources"], answer="Use undo.")
    question = {"kind": "answerable", "expected": [{"document": "Deployments", "section": "Rolling Back a Deployment"}]}
    assert score(question, answered) == {"answered": True, "cited": [], "retrievalHit": True, "retrievalRank": 1}
    invented = Sample("q", "t", "complete", answer="It is Bob [S1].")
    assert score({"kind": "unanswerable"}, invented)["noCitations"] is False


def test_upload_writes_each_file_under_the_prefix_as_the_workload_identity(tmp_path):
    run = tmp_path / "load-release-1808"
    run.mkdir()
    (run / "summary.json").write_text("{}")
    (run / "samples.jsonl").write_text("")
    seen = []

    def handle(request):
        if request.url.host == "metadata.google.internal":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append((request.url.params["name"], request.headers["authorization"]))
        return httpx.Response(200, json={})
    written = upload(run, "gs://evidence/inference/loadgen/2026-11-22", httpx.Client(transport=httpx.MockTransport(handle)))
    assert seen == [("inference/loadgen/2026-11-22/load-release-1808/samples.jsonl", "Bearer t"),
                    ("inference/loadgen/2026-11-22/load-release-1808/summary.json", "Bearer t")]
    assert len(written) == 2
