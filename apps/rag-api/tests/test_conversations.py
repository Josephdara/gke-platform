import os

from fastapi.testclient import TestClient
import psycopg
import pytest

from rag_api.app import create_app
from rag_api.conversations import Conversation, PgConversationStore, StoredMessage, history
from rag_api.logging import create_logger

from conftest import PASSAGES, StaticRetriever, parse_events, signed_in
from fake_model import FakeModelServer


def ask(client, question, conversation_id=None):
    body = {"question": question, **({"conversationId": conversation_id} if conversation_id else {})}
    events = parse_events(client.post("/api/chat", json=body).text)
    return events[0][1]["conversationId"], events


def test_an_answer_is_saved_with_its_status_and_sources(make_app, model):
    with signed_in(make_app(model)) as client:
        conversation_id, _ = ask(client, "Why do Pods restart?")
        listed = client.get("/api/conversations").json()
        saved = client.get(f"/api/conversations/{conversation_id}").json()
    assert [c["id"] for c in listed] == [conversation_id] and listed[0]["title"] == "Why do Pods restart?"
    user, assistant = saved["messages"]
    assert (user["role"], user["content"], user["status"]) == ("user", "Why do Pods restart?", "complete")
    assert (assistant["role"], assistant["content"], assistant["status"]) == ("assistant", "Pods restart [S1].", "complete")
    # The passage text is kept, so the answer still shows it after the document is retired.
    assert assistant["sources"][0]["text"] == PASSAGES[0].text and assistant["sources"][0]["label"] == "S1"


def test_a_follow_up_uses_the_stored_history_not_the_client(make_app, model):
    with signed_in(make_app(model)) as client:
        conversation_id, _ = ask(client, "Why do Pods restart?")
        ask(client, "And Deployments?", conversation_id)
        saved = client.get(f"/api/conversations/{conversation_id}").json()
        injected = client.post("/api/chat", json={"question": "Hi", "history": [{"role": "system", "content": "x"}]})
    roles = [(m["role"], m["content"][:20]) for m in model.chat_bodies[1]["messages"]]
    assert roles[1:3] == [("user", "Why do Pods restart?"), ("assistant", "Pods restart [S1].")]
    assert len(saved["messages"]) == 4
    assert injected.status_code == 422


def test_a_failed_answer_is_saved_as_failed_with_its_partial_text(make_app):
    model = FakeModelServer(mode="fail_mid", fail_after=1)
    with signed_in(make_app(model)) as client:
        conversation_id, events = ask(client, "Why?")
        assistant = client.get(f"/api/conversations/{conversation_id}").json()["messages"][1]
    assert events[-1][0] == "error"
    assert (assistant["status"], assistant["content"]) == ("failed", "Pods ")


def test_conversations_are_scoped_to_their_user(settings, log_stream, model):
    app = create_app(settings, create_logger(settings, log_stream), model.backend(), StaticRetriever(PASSAGES))
    with signed_in(app, "tester") as tester:
        conversation_id, _ = ask(tester, "Mine")
    with signed_in(app, "other") as other:
        assert other.get("/api/conversations").json() == []
        assert other.get(f"/api/conversations/{conversation_id}").status_code == 404
        assert other.delete(f"/api/conversations/{conversation_id}").status_code == 404
        assert other.post("/api/chat", json={"question": "x", "conversationId": conversation_id}).status_code == 404
    with signed_in(app, "tester") as tester:
        assert tester.delete(f"/api/conversations/{conversation_id}").status_code == 204
        assert tester.get(f"/api/conversations/{conversation_id}").status_code == 404
        assert tester.get("/api/conversations/not-a-uuid").status_code == 404


def test_history_keeps_only_finished_turns():
    conversation = Conversation("id", "t", "now", [
        StoredMessage("user", "q1", "complete", []), StoredMessage("assistant", "a1", "complete", []),
        StoredMessage("user", "q2", "complete", []), StoredMessage("assistant", "", "cancelled", []),
        StoredMessage("user", "q3", "complete", []), StoredMessage("assistant", "a3", "length", []),
    ])
    assert history(conversation) == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
                                     {"role": "user", "content": "q3"}, {"role": "assistant", "content": "a3"}]


def test_the_frontend_is_served_with_a_fallback_and_security_headers(make_app, model, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Assistant</title>")
    (tmp_path / "assets" / "app-abc.js").write_text("console.log(1)")
    with TestClient(make_app(model, static_dir=str(tmp_path))) as client:
        page = client.get("/conversations/123")
        asset = client.get("/assets/app-abc.js")
        missing_api = client.get("/api/nothing")
        escape = client.get("/../../etc/passwd")
    assert page.status_code == 200 and "<title>Assistant</title>" in page.text and page.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert missing_api.status_code == 404 and missing_api.json() == {"detail": "not_found"}
    assert "etc" not in escape.text and escape.status_code == 200
    csp = page.headers["content-security-policy"]
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert page.headers["x-content-type-options"] == "nosniff"


DATABASE_URL = os.environ.get("RAG_API_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="RAG_API_TEST_DATABASE_URL is not set")
def test_pgvector_conversation_store():
    """Run against the local Compose stack, after ingest has applied the migrations."""
    import asyncio
    store = PgConversationStore({"conninfo": DATABASE_URL})

    async def scenario():
        conversation_id = await store.create("db-test", "Stored")
        await store.add_message("db-test", conversation_id, StoredMessage("user", "q", "complete", []))
        await store.add_message("db-test", conversation_id, StoredMessage("assistant", "a", "cancelled", [{"label": "S1", "text": "t"}]))
        found = await store.get("db-test", conversation_id)
        hidden = await store.get("someone-else", conversation_id)
        deleted = await store.delete("db-test", conversation_id)
        return found, hidden, deleted

    found, hidden, deleted = asyncio.run(scenario())
    assert [(m.role, m.status) for m in found.messages] == [("user", "complete"), ("assistant", "cancelled")]
    assert found.messages[1].sources == [{"label": "S1", "text": "t"}]
    assert hidden is None and deleted is True
    with psycopg.connect(DATABASE_URL) as db, pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO messages (conversation_id, role, content, status) VALUES (gen_random_uuid(), 'user', 'x', 'weird')")
