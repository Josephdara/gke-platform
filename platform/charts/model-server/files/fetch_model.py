"""Downloads a model's files from Cloud Storage and verifies each one.

Runs as the model-server init container. It gets an access token for the
Pod's own Kubernetes service account from the GKE metadata server, downloads
every file listed in MODEL_FILES into MODEL_DIR, then checks each file's size
and SHA-256. Any mismatch, missing file, or timeout exits non-zero, so the
model server never starts with the wrong model. Standard library only.
"""

import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
OBJECT_URL = "https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}?alt=media"
CHUNK = 8 * 1024 * 1024


def log(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def token(timeout):
    request = urllib.request.Request(TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["access_token"]


def download(bucket, name, path, access_token, deadline):
    url = OBJECT_URL.format(bucket=bucket, name=urllib.parse.quote(name, safe=""))
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = path + ".part"
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(CHUNK):
            if time.monotonic() > deadline:
                raise TimeoutError("download deadline reached")
            out.write(chunk)
    os.replace(partial, path)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    bucket = os.environ["MODEL_BUCKET"]
    prefix = os.environ["MODEL_PREFIX"]
    target = os.environ["MODEL_DIR"]
    files = json.loads(os.environ["MODEL_FILES"])
    deadline = time.monotonic() + int(os.environ["DOWNLOAD_TIMEOUT_SECONDS"])

    started = time.monotonic()
    access_token = token(timeout=10)
    for entry in files:
        path = os.path.join(target, entry["path"])
        begin = time.monotonic()
        download(bucket, prefix + entry["path"], path, access_token, deadline)
        log("downloaded", file=entry["path"], bytes=os.path.getsize(path), seconds=round(time.monotonic() - begin, 2))
    download_seconds = time.monotonic() - started

    checked = time.monotonic()
    for entry in files:
        path = os.path.join(target, entry["path"])
        size = os.path.getsize(path)
        actual = sha256(path)
        if size != entry["sizeBytes"] or actual != entry["sha256"]:
            log("mismatch", file=entry["path"], bytes=size, expected_bytes=entry["sizeBytes"], sha256=actual, expected_sha256=entry["sha256"])
            return 1
    log("verified", files=len(files), download_seconds=round(download_seconds, 2), checksum_seconds=round(time.monotonic() - checked, 2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - report any failure as one line and fail the container
        log("failed", error=type(error).__name__, detail=str(error))
        sys.exit(1)
