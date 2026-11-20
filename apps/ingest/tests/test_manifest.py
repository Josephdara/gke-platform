import hashlib
import json

import pytest

from ingest.manifest import ManifestError, parse_manifest
from ingest.source import LocalSource, SourceError, verify

ENTRY = {"path": "docs/a.md", "title": "A", "source": "https://example.test/a", "license": "CC BY 4.0",
         "attribution": "Example", "sha256": hashlib.sha256(b"hello").hexdigest(), "bytes": 5}


def manifest(*entries):
    return json.dumps({"revision": "r1", "files": list(entries)}).encode()


def test_valid_manifest():
    parsed = parse_manifest(manifest(ENTRY))
    assert parsed.revision == "r1"
    assert parsed.files[0].path == "docs/a.md"


@pytest.mark.parametrize("change", [
    {"license": ""}, {"attribution": None}, {"sha256": "abc"}, {"bytes": "5"},
    {"path": "../etc/passwd"}, {"path": "/abs.md"},
])
def test_invalid_entries_stop_the_run(change):
    with pytest.raises(ManifestError):
        parse_manifest(manifest({**ENTRY, **change}))


def test_duplicate_paths_and_bad_json_are_refused():
    with pytest.raises(ManifestError):
        parse_manifest(manifest(ENTRY, ENTRY))
    with pytest.raises(ManifestError):
        parse_manifest(b"not json")


def test_files_must_match_their_hash_size_and_limit(tmp_path):
    file = parse_manifest(manifest(ENTRY)).files[0]
    assert verify(file, b"hello", 100) == b"hello"
    with pytest.raises(SourceError, match="does not match"):
        verify(file, b"HELLO", 100)
    with pytest.raises(SourceError, match="size limit"):
        verify(file, b"hello", 4)


def test_local_source_stays_inside_its_directory(tmp_path):
    (tmp_path / "a.md").write_text("x")
    source = LocalSource(str(tmp_path))
    assert source.read("a.md") == b"x"
    with pytest.raises(SourceError):
        source.read("../outside.md")
