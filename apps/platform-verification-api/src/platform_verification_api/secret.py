"""Mounted JSON secret, reread when its content changes. The value is never logged or returned."""

import json
import logging
from pathlib import Path
import re

LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")


class SecretFormatError(ValueError):
    """The secret is not a JSON object with a valid label and a nonempty value."""


def parse_label(content: bytes) -> str:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise SecretFormatError("secret must be a JSON object")
    label, value = data.get("label"), data.get("value")
    if not (isinstance(label, str) and LABEL.fullmatch(label) and isinstance(value, str) and value):
        raise SecretFormatError("secret needs a valid label and a nonempty value")
    return label


class SecretFile:
    def __init__(self, path: str, logger: logging.Logger):
        self.path = Path(path)
        self.logger = logger
        self.label: str | None = None
        self.content: bytes | None = None
        self.unreadable = False

    def refresh(self) -> None:
        try:
            content = self.path.read_bytes()
        except OSError as exc:
            if not self.unreadable:
                self.unreadable = True
                self.failed(exc)
            return
        self.unreadable = False
        if content == self.content:
            return
        self.content = content
        try:
            label = parse_label(content)
        except ValueError as exc:
            self.failed(exc)
            return
        self.label = label
        self.logger.info("secret_loaded", extra={"secret_label": label})

    def failed(self, exc: Exception) -> None:
        # A bad version keeps the last valid label; only the exception class is logged.
        event = "secret_load_failed" if self.label is None else "secret_reload_failed"
        self.logger.error(event, extra={"error_type": type(exc).__name__})
