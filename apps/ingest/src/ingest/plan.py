"""Decides what a run does to each document, from the manifest and the database's state."""

from dataclasses import dataclass

from .manifest import CorpusFile


@dataclass(frozen=True)
class DocumentState:
    active_revision: str | None
    retired: bool


@dataclass(frozen=True)
class Action:
    # unchanged: same SHA-256 as the active revision, skipped. new: not in the database.
    # changed: a different SHA-256, or a retired document that is back. retire: no longer listed.
    kind: str
    path: str
    file: CorpusFile | None = None


def plan(files: list[CorpusFile], state: dict[str, DocumentState]) -> list[Action]:
    actions = []
    for file in files:
        current = state.get(file.path)
        if current is None:
            actions.append(Action("new", file.path, file))
        elif current.retired or current.active_revision != file.sha256:
            actions.append(Action("changed", file.path, file))
        else:
            actions.append(Action("unchanged", file.path, file))
    listed = {file.path for file in files}
    for path, current in sorted(state.items()):
        if path not in listed and not current.retired:
            actions.append(Action("retire", path))
    return actions
