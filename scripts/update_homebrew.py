#!/usr/bin/env python3
"""Generate a checksummed Homebrew formula from a stable public PyPI release.

Requires uv and packaging. Resolution/build happens without publishing credentials.
Four macOS/Linux resolution targets must agree on common dependency versions.
Resolution is not native installation evidence; see docs/homebrew.md.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PYTHON = "3.14"
PLATFORMS = ("aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu")


def stable_version(value: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("Expected a stable X.Y.Z version")
    return value


def metadata(name: str, version: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not re.fullmatch(r"[A-Za-z0-9_.+!-]+", version):
        raise ValueError("Invalid package identifier")
    for attempt in range(3):
        try:
            with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as response:
                return json.load(response)
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def source(info: dict) -> tuple[str, str]:
    artifacts = [a for a in info["urls"] if a["packagetype"] == "sdist" and not a.get("yanked")]
    if len(artifacts) != 1:
        raise ValueError("Expected exactly one non-yanked source distribution")
    artifact = artifacts[0]
    url, checksum = artifact["url"], artifact["digests"]["sha256"]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "files.pythonhosted.org"
            or not re.fullmatch(r"/packages/[A-Za-z0-9_./+-]+", parsed.path)
            or parsed.query or parsed.fragment or not re.fullmatch(r"[a-f0-9]{64}", checksum)):
        raise ValueError("Untrusted source URL or invalid SHA256")
    return url, checksum


def requirements(info: dict) -> list[str]:
    result = []
    for text in info["info"]["requires_dist"]:
        req = Requirement(text)
        # Distribution extras (test/release) must never enter the runtime formula.
        if req.marker and "extra" in str(req.marker):
            continue
        if canonicalize_name(req.name) == "psycopg":
            req.extras = {"c"}
        if req.url:
            raise ValueError("Direct URL dependencies are not supported")
        result.append(str(req))
    return result


def pins(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        req = Requirement(line)
        specs = list(req.specifier)
        if req.url or len(specs) != 1 or specs[0].operator != "==" or "*" in specs[0].version:
            raise ValueError(f"Dependency is not pinned: {req.name}")
        name = canonicalize_name(req.name)
        version = specs[0].version
        if name in result and result[name] != version:
            raise ValueError(f"Conflicting pins: {name}")
        result[name] = version
    return result


def resolve(info: dict, directory: Path) -> dict[str, str]:
    requirements_path = directory / "requirements.in"
    requirements_path.write_text("\n".join(requirements(info)) + "\n")
    common = {}
    constraints = directory / "constraints.txt"
    for index, platform in enumerate(PLATFORMS):
        output = directory / f"{platform}.txt"
        command = ["uv", "pip", "compile", str(requirements_path), "--python-version", PYTHON,
                   "--python-platform", platform, "--no-header", "--no-annotate", "-o", str(output)]
        if index:
            command += ["--constraint", str(constraints)]
        subprocess.run(command, check=True, timeout=600)
        for name, version in pins(output.read_text()).items():
            if name in common and common[name] != version:
                raise ValueError(f"Platform-dependent version for {name}")
            common[name] = version
        constraints.write_text("\n".join(f"{n}=={v}" for n, v in sorted(common.items())) + "\n")
    if "psycopg-binary" in common or common.get("psycopg-c") != common.get("psycopg"):
        raise ValueError("Expected a matching source-built Psycopg C driver")
    return common


def render(info: dict, resources: dict[str, tuple[str, str]]) -> str:
    url, checksum = source(info)
    blocks = []
    for name, (resource_url, sha256) in sorted(resources.items()):
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Invalid resource name")
        blocks.append(f'  resource "{name}" do\n    url "{resource_url}"\n    sha256 "{sha256}"\n  end\n')
    template = (Path(__file__).parent / "homebrew_formula.rb.in").read_text()
    return template.replace("@URL@", url).replace("@SHA256@", checksum).replace("@RESOURCES@", "\n".join(blocks))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", type=stable_version)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    info = metadata("contitext", args.version)
    if info["info"]["version"] != args.version:
        raise ValueError("PyPI version mismatch")
    with tempfile.TemporaryDirectory(prefix="contitext-homebrew-") as directory:
        resolved = resolve(info, Path(directory))
    def fetch(item):
        name, version = item
        return name, source(metadata(name, version))
    with ThreadPoolExecutor(max_workers=4) as pool:
        resources = dict(pool.map(fetch, sorted(resolved.items())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(info, resources))
    print(f"Generated Contitext {args.version} formula with {len(resources)} pinned resources.")


if __name__ == "__main__":
    main()
