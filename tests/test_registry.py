"""Catch release mismatches and accidental credentials in public Registry metadata."""

import json
from pathlib import Path
import tomllib

from contitext import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_registry_package_ownership_and_version_match_distribution():
    manifest = json.loads((ROOT / "server.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    package, = manifest["packages"]
    assert manifest["version"] == package["version"] == project["version"] == __version__
    assert package["identifier"] == project["name"]
    assert manifest["repository"]["url"] == project["urls"]["Repository"]
    assert f"<!-- mcp-name: {manifest['name']} -->" in (ROOT / "README.md").read_text()
    assert package["registryType"] == "pypi"
    assert package["transport"] == {"type": "stdio"}
    assert "remotes" not in manifest
    required = {"DATABASE_URL", "CONTITEXT_AUTH_TOKENS", "CONTITEXT_MCP_TOKEN"}
    assert {item["name"] for item in package["environmentVariables"]} == required
    for item in package["environmentVariables"]:
        assert item["isRequired"] is True and item["isSecret"] is True
        assert not {"value", "default", "choices", "variables"}.intersection(item)
