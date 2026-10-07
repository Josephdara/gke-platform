"""Downloads the validation tools for CI, each checked against a pinned SHA-256.

Usage: python pipeline/install_tools.py <directory>
"""

import hashlib
import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

TOOLS = {
    "helm": (
        "https://get.helm.sh/helm-v4.2.1-linux-amd64.tar.gz",
        "479dca836e5b45e8bd222400c5591b0e3a647378f03ff96597180db97c17fdae",
        "linux-amd64/helm",
    ),
    "kubeconform": (
        "https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz",
        "9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883",
        "kubeconform",
    ),
    "kyverno": (
        "https://github.com/kyverno/kyverno/releases/download/v1.19.1/kyverno-cli_v1.19.1_linux_x86_64.tar.gz",
        "b38228f367fc0fdc2b08f4c83ea50ac5f16c60ff8d62d76a66157c33c47b70ae",
        "kyverno",
    ),
    "terraform": (
        "https://releases.hashicorp.com/terraform/1.16.4/terraform_1.16.4_linux_amd64.zip",
        "dc94af0eef1147718ad7c8daea792ed199e3e0492eec180d0adafa2a65a879df",
        "terraform",
    ),
    "trivy": (
        "https://github.com/aquasecurity/trivy/releases/download/v0.74.0/trivy_0.74.0_Linux-64bit.tar.gz",
        "2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a",
        "trivy",
    ),
}


def main(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected, member) in TOOLS.items():
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            sys.exit(f"{name}: downloaded SHA-256 {actual} does not match the pinned {expected}")
        if url.endswith(".zip"):
            binary = zipfile.ZipFile(io.BytesIO(data)).read(member)
        else:
            binary = tarfile.open(fileobj=io.BytesIO(data)).extractfile(member).read()
        path = directory / name
        path.write_bytes(binary)
        path.chmod(0o755)
        print(f"{name}: {url.rsplit('/', 1)[1]} verified")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
