"""A run against a local corpus and an in-memory store: what gets loaded, skipped, and retired."""

import pytest

from ingest.embed import EmbeddingError
from ingest.main import run
from ingest.manifest import parse_manifest
from ingest.plan import DocumentState, plan
from ingest.source import LocalSource

from conftest import FakeStore, write_corpus
from fake_tei import FakeTei

A = "## Probes\n\nA failing liveness probe restarts the container.\n"
B = "## Services\n\nA Service gives Pods a stable address.\n"


def test_plan_decisions():
    files = parse_manifest(b'{"revision": "r", "files": [' + b",".join(
        f'{{"path": "{p}", "title": "t", "source": "s", "license": "l", "attribution": "a", "sha256": "{c * 64}", "bytes": 1}}'.encode()
        for p, c in [("same.md", "a"), ("edited.md", "b"), ("new.md", "c"), ("back.md", "d")]) + b"]}").files
    state = {"same.md": DocumentState("a" * 64, False), "edited.md": DocumentState("0" * 64, False),
             "back.md": DocumentState(None, True), "gone.md": DocumentState("e" * 64, False),
             "old.md": DocumentState(None, True)}
    assert [(a.kind, a.path) for a in plan(files, state)] == [
        ("unchanged", "same.md"), ("changed", "edited.md"), ("new", "new.md"), ("changed", "back.md"), ("retire", "gone.md")]


def test_first_run_loads_and_a_rerun_skips(settings, tmp_path):
    write_corpus(tmp_path / "corpus", {"a.md": A, "docs/b.md": B})
    store, tei = FakeStore(), FakeTei()
    first = run(settings, LocalSource(str(tmp_path / "corpus")), tei.client(), store)
    assert (first["new"], first["unchanged"], first["failed"]) == (2, 0, 0)
    assert first["chunksLoaded"] == 2
    calls = tei.embed_calls
    second = run(settings, LocalSource(str(tmp_path / "corpus")), tei.client(), store)
    assert (second["new"], second["unchanged"], second["chunksLoaded"]) == (0, 2, 0)
    assert tei.embed_calls == calls
    assert [r["status"] for r in store.runs] == ["succeeded", "succeeded"]


def test_a_changed_file_is_reloaded_and_a_removed_one_retired(settings, tmp_path):
    corpus = tmp_path / "corpus"
    write_corpus(corpus, {"a.md": A, "b.md": B})
    store = FakeStore()
    run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    write_corpus(corpus, {"a.md": A + "\nProbes can also run commands.\n"}, revision="rev-2")
    report = run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    assert (report["changed"], report["retired"], report["corpusRevision"]) == (1, 1, "rev-2")
    assert store.documents["b.md"]["retired"] is True and store.documents["b.md"]["chunks"] == []


def test_a_bad_file_fails_alone_and_keeps_its_previous_revision(settings, tmp_path):
    corpus = tmp_path / "corpus"
    write_corpus(corpus, {"a.md": A, "b.md": B})
    store = FakeStore()
    run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    previous = store.documents["a.md"]["active"]
    write_corpus(corpus, {"a.md": A + "\nEdited.\n", "b.md": B}, revision="rev-2")
    (corpus / "a.md").write_text("tampered after the manifest was written")
    report = run(settings, LocalSource(str(corpus)), FakeTei().client(), store)
    assert report["failed"] == 1 and report["unchanged"] == 1
    assert report["failures"] == [{"path": "a.md", "error": "SourceError", "detail": "file does not match its manifest entry"}]
    assert store.documents["a.md"]["active"] == previous
    assert store.runs[-1]["status"] == "failed"


def test_an_embeddings_outage_fails_each_file_without_loading(settings, tmp_path):
    write_corpus(tmp_path / "corpus", {"a.md": A})
    store = FakeStore()
    report = run(settings, LocalSource(str(tmp_path / "corpus")), FakeTei(fail=True).client(), store)
    assert report["failed"] == 1 and store.documents == {}


def test_a_heading_that_repeats_the_title_is_dropped(settings, tmp_path):
    write_corpus(tmp_path / "corpus", {"a.md": "# a.md\n\nIntro.\n\n## Probes\n\nText.\n"})
    store = FakeStore()
    run(settings, LocalSource(str(tmp_path / "corpus")), FakeTei().client(), store)
    assert [c.heading_path for c in store.documents["a.md"]["chunks"]] == ["", "Probes"]


def test_vectors_of_the_wrong_size_are_refused():
    with pytest.raises(EmbeddingError, match="384"):
        FakeTei(dimensions=128).client().embed(["text"])
