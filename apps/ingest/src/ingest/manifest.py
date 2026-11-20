"""The corpus manifest: every file's path, source, license, and SHA-256."""

from dataclasses import dataclass
import json
import re

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED = ("path", "title", "source", "license", "attribution", "sha256", "bytes")


class ManifestError(ValueError):
    """The manifest is malformed. The run stops, because nothing in it can be trusted."""


@dataclass(frozen=True)
class CorpusFile:
    path: str
    title: str
    source: str
    license: str
    attribution: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class Manifest:
    revision: str
    files: list[CorpusFile]


def parse_manifest(raw: bytes) -> Manifest:
    try:
        data = json.loads(raw)
        revision = data["revision"]
        entries = data["files"]
    except (ValueError, KeyError, TypeError):
        raise ManifestError("manifest must be JSON with a revision and a files list") from None
    if not isinstance(revision, str) or not revision or not isinstance(entries, list):
        raise ManifestError("manifest must be JSON with a revision and a files list")
    files, seen = [], set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or any(not entry.get(key) for key in REQUIRED):
            raise ManifestError(f"file {index} needs {', '.join(REQUIRED)}")
        path = entry["path"]
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/") or path in seen:
            raise ManifestError(f"file {index} has an unsafe or duplicate path")
        if not SHA256.fullmatch(str(entry["sha256"])) or not isinstance(entry["bytes"], int):
            raise ManifestError(f"file {index} needs a 64-character sha256 and an integer size")
        seen.add(path)
        files.append(CorpusFile(**{key: entry[key] for key in REQUIRED}))
    return Manifest(revision=revision, files=files)
