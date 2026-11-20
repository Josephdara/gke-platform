from ingest.chunk import chunk_sections
from ingest.parse import Section


def words(n, prefix="w"):
    return " ".join(f"{prefix}{i}" for i in range(n))


def count(texts):
    return [len(t.split()) for t in texts]


def test_paragraphs_are_packed_up_to_the_limit_with_overlap():
    section = Section("Probes", [words(25, "a"), words(25, "b"), words(25, "c")])
    chunks = chunk_sections([section], count, chunk_tokens=60, overlap_tokens=10)
    assert len(chunks) == 2
    assert chunks[0].text == f"{words(25, 'a')}\n\n{words(25, 'b')}"
    # The second chunk starts with the last 10 words of the first.
    assert chunks[1].text.startswith(" ".join(f"b{i}" for i in range(15, 25)))
    assert chunks[1].text.endswith(words(25, "c"))
    assert [c.ordinal for c in chunks] == [0, 1]
    assert all(c.heading_path == "Probes" for c in chunks)
    assert chunks[0].token_count == 50


def test_a_long_paragraph_is_split():
    chunks = chunk_sections([Section("Long", [words(200)])], count, chunk_tokens=60, overlap_tokens=10)
    assert len(chunks) >= 4
    assert all(c.token_count <= 60 + 10 for c in chunks)
    assert chunks[-1].text.endswith("w199")


def test_chunks_never_cross_headings():
    chunks = chunk_sections([Section("A", [words(5)]), Section("B", [words(5)])], count, 60, 10)
    assert [(c.heading_path, c.text) for c in chunks] == [("A", words(5)), ("B", words(5))]


def test_an_empty_document_has_no_chunks():
    assert chunk_sections([], count, 60, 10) == []
