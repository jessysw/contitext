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
    required = {"DATABASE_URL", "CONTITEXT_MCP_TOKEN"}
    secret = required | {"CONTITEXT_AUTH_TOKENS"}
    assert {item["name"] for item in package["environmentVariables"]} == secret | {"CONTITEXT_AUTH_MODE", "CONTITEXT_COMPATIBILITY_WORKSPACE"}
    for item in package["environmentVariables"]:
        assert item["isRequired"] == (item["name"] in required)
        assert item["isSecret"] == (item["name"] in secret)
        assert not {"value", "default", "choices", "variables"}.intersection(item)
