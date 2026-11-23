"""Uploads a run's files to Cloud Storage as the Pod's Workload Identity, for runs inside the cluster."""

from pathlib import Path
from urllib.parse import quote

import httpx

METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


def split(target: str) -> tuple[str, str]:
    if not target.startswith("gs://") or "/" not in target[5:]:
        raise ValueError("--upload must be gs://BUCKET/PREFIX/")
    bucket, prefix = target[5:].split("/", 1)
    return bucket, prefix if not prefix or prefix.endswith("/") else prefix + "/"


def upload(directory: Path, target: str, client: httpx.Client) -> list[str]:
    """Uploads every file in directory under target, keeping the directory's name. Returns the
    object names written."""
    bucket, prefix = split(target)
    token = client.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    written = []
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        name = f"{prefix}{directory.name}/{path.name}"
        response = client.post(f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o",
                               params={"uploadType": "media", "name": name}, content=path.read_bytes(),
                               headers={**headers, "Content-Type": "application/octet-stream"})
        response.raise_for_status()
        written.append(f"gs://{bucket}/{quote(name)}")
    return written
