"""Reads corpus files from Cloud Storage or a local directory and verifies each one."""

import hashlib
from pathlib import Path
from typing import Protocol
import urllib.parse

import httpx

from .manifest import CorpusFile

METADATA_TOKEN = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
STORAGE = "https://storage.googleapis.com"


class SourceError(Exception):
    """A file could not be read, or did not match the manifest."""


class CorpusSource(Protocol):
    def read(self, path: str) -> bytes: ...


def verify(file: CorpusFile, data: bytes, limit: int) -> bytes:
    if len(data) > limit:
        raise SourceError("file is larger than the size limit")
    if len(data) != file.bytes or hashlib.sha256(data).hexdigest() != file.sha256:
        raise SourceError("file does not match its manifest entry")
    return data


class LocalSource:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def read(self, path: str) -> bytes:
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root):
            raise SourceError("path leaves the corpus directory")
        try:
            return target.read_bytes()
        except OSError as exc:
            raise SourceError(type(exc).__name__) from None


def metadata_token(client: httpx.Client) -> str:
    response = client.get(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"})
    response.raise_for_status()
    return response.json()["access_token"]


class GcsSource:
    """gs://<bucket>/<prefix>/, read through the JSON API as the Pod's Workload Identity."""

    def __init__(self, url: str, client: httpx.Client):
        bucket, _, prefix = url.removeprefix("gs://").partition("/")
        self.bucket, self.prefix, self.client = bucket, prefix, client
        self.token: str | None = None

    def read(self, path: str) -> bytes:
        self.token = self.token or metadata_token(self.client)
        name = urllib.parse.quote(self.prefix + path, safe="")
        try:
            response = self.client.get(f"{STORAGE}/storage/v1/b/{self.bucket}/o/{name}",
                                       params={"alt": "media"}, headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as exc:
            raise SourceError(type(exc).__name__) from None
        if response.status_code != 200:
            raise SourceError(f"storage returned HTTP {response.status_code}")
        return response.content


def upload(client: httpx.Client, bucket: str, name: str, data: bytes, token: str | None = None) -> None:
    token = token or metadata_token(client)
    response = client.post(f"{STORAGE}/upload/storage/v1/b/{bucket}/o",
                           params={"uploadType": "media", "name": name}, content=data,
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    response.raise_for_status()


def open_source(url: str, client: httpx.Client) -> CorpusSource:
    return GcsSource(url, client) if url.startswith("gs://") else LocalSource(url)
